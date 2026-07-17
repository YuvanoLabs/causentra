"""Python-first, framework-neutral agent runtime instrumentation."""

from __future__ import annotations

import contextvars
import re
import secrets
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Generic, Literal, TypeVar

from .model import CostBasis, model_attributes
from .propagation import extract_trace_context, inject_trace_context
from .providers import provider_response_attributes
from .redaction import default_redactor
from .relationships import RelationshipKind, relationship_attributes
from .types import (
    SCHEMA_VERSION,
    EventAttributes,
    EventExporter,
    EventStatus,
    Redactor,
    RuntimeErrorContext,
    RuntimeEvent,
    TraceContext,
)
from .validation import validate_attributes, validate_event


@dataclass(frozen=True, slots=True)
class _ActiveContext:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    session_id: str | None


_SESSION_ID = re.compile(r"^[0-9a-f]{32}$")
_ResponseT = TypeVar("_ResponseT")


class CausentraRuntime:
    """Capture nested agent operations without changing application behavior.

    Context managers are both synchronous and asynchronous, making the same API
    usable in normal functions, coroutines, tasks, and notebook environments.
    """

    def __init__(
        self,
        service_name: str,
        exporter: EventExporter,
        *,
        session_id: str | None = None,
        redactor: Redactor = default_redactor,
        include_error_message: bool = False,
        on_error: Callable[[RuntimeErrorContext], None] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not service_name.strip() or len(service_name) > 256:
            raise ValueError("service_name must be non-empty and at most 256 characters")
        if session_id is not None and not _SESSION_ID.fullmatch(session_id):
            raise ValueError("session_id must be 32 lowercase hexadecimal characters")
        self._service_name = service_name
        self._exporter = exporter
        self._session_id = session_id
        self._redactor = redactor
        self._include_error_message = include_error_message
        self._on_error = on_error or (lambda _context: None)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sequences: dict[str, int] = {}
        self._sequence_lock = threading.Lock()
        self._active: contextvars.ContextVar[_ActiveContext | None] = contextvars.ContextVar(
            f"causentra_context_{id(self)}", default=None
        )

    def current_context(self) -> TraceContext | None:
        value = self._active.get()
        if value is None:
            return None
        return TraceContext(value.trace_id, value.span_id, value.parent_span_id, value.session_id)

    def trace(self, name: str, *, attributes: EventAttributes | None = None) -> _Operation:
        return _Operation(self, name, "trace", attributes or {})

    def trace_from_carrier(
        self,
        name: str,
        carrier: Mapping[str, str],
        *,
        attributes: EventAttributes | None = None,
    ) -> _Operation:
        return _Operation(
            self, name, "trace", attributes or {}, remote=extract_trace_context(carrier)
        )

    def span(self, name: str, *, attributes: EventAttributes | None = None) -> _Operation:
        return _Operation(self, name, "span", attributes or {})

    def agent(self, name: str, *, attributes: EventAttributes | None = None) -> _Operation:
        return _Operation(self, name, "agent", attributes or {})

    def tool(self, name: str, *, attributes: EventAttributes | None = None) -> _Operation:
        return _Operation(self, name, "tool", attributes or {})

    def model(
        self,
        name: str,
        *,
        provider_name: str | None = None,
        request_model: str | None = None,
        response_model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_input_tokens: int | None = None,
        cost_usd: float | None = None,
        cost_basis: CostBasis | None = None,
        attributes: EventAttributes | None = None,
    ) -> _Operation:
        canonical = model_attributes(
            provider_name=provider_name,
            request_model=request_model,
            response_model=response_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cost_usd=cost_usd,
            cost_basis=cost_basis,
        )
        return _Operation(self, name, "model", {**(attributes or {}), **canonical})

    def provider_model(
        self,
        name: str,
        *,
        provider_name: str,
        request_model: str | None = None,
        cost_usd: float | None = None,
        cost_basis: CostBasis | None = None,
        attributes: EventAttributes | None = None,
    ) -> ProviderModelOperation[Any]:
        """Create a provider-aware model operation with response observation."""

        start_attributes = model_attributes(
            provider_name=provider_name,
            request_model=request_model,
            cost_usd=cost_usd,
            cost_basis=cost_basis,
        )
        operation = _Operation(self, name, "model", {**(attributes or {}), **start_attributes})
        return ProviderModelOperation(
            self, operation, provider_name=provider_name, request_model=request_model
        )

    def call_model(
        self,
        name: str,
        operation: Callable[[], _ResponseT],
        *,
        provider_name: str,
        request_model: str | None = None,
        cost_usd: float | None = None,
        cost_basis: CostBasis | None = None,
        attributes: EventAttributes | None = None,
    ) -> _ResponseT:
        """Run and observe a synchronous provider call without changing its result."""

        with self.provider_model(
            name,
            provider_name=provider_name,
            request_model=request_model,
            cost_usd=cost_usd,
            cost_basis=cost_basis,
            attributes=attributes,
        ) as observer:
            response = operation()
            observer.observe_response(response)
            return response

    async def call_model_async(
        self,
        name: str,
        operation: Callable[[], Awaitable[_ResponseT]],
        *,
        provider_name: str,
        request_model: str | None = None,
        cost_usd: float | None = None,
        cost_basis: CostBasis | None = None,
        attributes: EventAttributes | None = None,
    ) -> _ResponseT:
        """Run and observe an asynchronous provider call without changing its result."""

        async with self.provider_model(
            name,
            provider_name=provider_name,
            request_model=request_model,
            cost_usd=cost_usd,
            cost_basis=cost_basis,
            attributes=attributes,
        ) as observer:
            response = await operation()
            observer.observe_response(response)
            return response

    def relationship(
        self,
        kind: RelationshipKind,
        from_agent: str,
        to_agent: str,
        *,
        relationship_id: str | None = None,
        attributes: EventAttributes | None = None,
    ) -> _Operation:
        canonical = relationship_attributes(kind, from_agent, to_agent, relationship_id)
        return _Operation(
            self,
            f"{from_agent} to {to_agent}",
            f"agent.{kind}",
            {**(attributes or {}), **canonical},
        )

    def handoff(self, from_agent: str, to_agent: str, **kwargs: Any) -> _Operation:
        return self.relationship("handoff", from_agent, to_agent, **kwargs)

    def delegation(self, from_agent: str, to_agent: str, **kwargs: Any) -> _Operation:
        return self.relationship("delegation", from_agent, to_agent, **kwargs)

    def record(
        self,
        name: str,
        *,
        event_type: str = "custom.event",
        status: EventStatus = "unset",
        attributes: EventAttributes | None = None,
    ) -> bool:
        context = self._active.get()
        if context is None:
            return False
        self._emit(context, event_type, name, status, attributes or {})
        return True

    def inject_trace_context(
        self, carrier: Mapping[str, str] | None = None, *, sampled: bool = True
    ) -> dict[str, str] | None:
        context = self.current_context()
        return None if context is None else inject_trace_context(context, carrier, sampled=sampled)

    def flush(self, timeout: float | None = None) -> bool:
        return self._exporter.flush(timeout)

    def shutdown(self, timeout: float | None = 5.0) -> None:
        self._exporter.shutdown(timeout)

    def _emit(
        self,
        context: _ActiveContext,
        event_type: str,
        name: str,
        status: EventStatus,
        attributes: EventAttributes,
        duration_ms: float | None = None,
    ) -> None:
        operation: Literal["export", "redact"] = "redact"
        try:
            validate_attributes(attributes)
            redacted = self._redactor(attributes)
            validate_attributes(redacted)
            event = RuntimeEvent(
                schema_version=SCHEMA_VERSION,
                event_id=secrets.token_hex(16),
                trace_id=context.trace_id,
                span_id=context.span_id,
                parent_span_id=context.parent_span_id,
                session_id=context.session_id,
                sequence=self._next_sequence(context.trace_id),
                timestamp=self._now()
                .astimezone(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
                type=event_type,
                name=name,
                status=status,
                duration_ms=duration_ms,
                service_name=self._service_name,
                attributes=redacted,
            )
            validate_event(event)
            operation = "export"
            self._exporter.emit(event)
        except BaseException as error:
            with suppress(BaseException):
                self._on_error(RuntimeErrorContext(operation, error, 1))

    def _next_sequence(self, trace_id: str) -> int:
        with self._sequence_lock:
            value = self._sequences.get(trace_id, 0)
            self._sequences[trace_id] = value + 1
            return value

    def _forget_trace(self, trace_id: str) -> None:
        with self._sequence_lock:
            self._sequences.pop(trace_id, None)


class _Operation:
    def __init__(
        self,
        runtime: CausentraRuntime,
        name: str,
        family: str,
        attributes: EventAttributes,
        remote: TraceContext | None = None,
    ) -> None:
        if not name.strip() or len(name) > 256:
            raise ValueError("operation name must be non-empty and at most 256 characters")
        self._runtime = runtime
        self._name = name
        self._family = family
        self._attributes = attributes
        self._remote = remote
        self._context: _ActiveContext | None = None
        self._token: contextvars.Token[_ActiveContext | None] | None = None
        self._started = 0.0
        self._owns_trace = False
        self._end_attributes: EventAttributes = {}

    def __enter__(self) -> TraceContext:
        parent = self._runtime._active.get()
        if self._family == "trace" or parent is None:
            self._owns_trace = True
            trace_id = self._remote.trace_id if self._remote else secrets.token_hex(16)
            parent_id = self._remote.span_id if self._remote else None
            span_id = secrets.token_hex(8)
            family = "trace"
        else:
            trace_id = parent.trace_id
            parent_id = parent.span_id
            span_id = secrets.token_hex(8)
            family = self._family
        session = parent.session_id if parent else self._runtime._session_id
        self._context = _ActiveContext(trace_id, span_id, parent_id, session)
        self._started = time.perf_counter()
        self._runtime._emit(self._context, f"{family}.start", self._name, "unset", self._attributes)
        self._token = self._runtime._active.set(self._context)
        return TraceContext(trace_id, span_id, parent_id, session)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del traceback
        assert self._context is not None and self._token is not None
        family = "trace" if self._owns_trace else self._family
        attributes: EventAttributes = {}
        if exc_type is not None:
            attributes["error.type"] = exc_type.__name__[:128]
            if self._runtime._include_error_message and exc_value is not None:
                attributes["error.message"] = str(exc_value)[:1_024]
        attributes = {**self._end_attributes, **attributes}
        self._runtime._emit(
            self._context,
            f"{family}.end",
            self._name,
            "error" if exc_type else "ok",
            attributes,
            max(0.0, (time.perf_counter() - self._started) * 1_000),
        )
        self._runtime._active.reset(self._token)
        if self._owns_trace:
            self._runtime._forget_trace(self._context.trace_id)
        return False

    async def __aenter__(self) -> TraceContext:
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        return self.__exit__(exc_type, exc_value, traceback)

    def add_end_attributes(self, attributes: EventAttributes) -> None:
        """Attach facts learned only after an operation response is available."""

        self._end_attributes.update(attributes)


class ProviderModelOperation(Generic[_ResponseT]):
    """Model-call observer returned by :meth:`CausentraRuntime.provider_model`."""

    def __init__(
        self,
        runtime: CausentraRuntime,
        operation: _Operation,
        *,
        provider_name: str,
        request_model: str | None,
    ) -> None:
        self._runtime = runtime
        self._operation = operation
        self._provider_name = provider_name
        self._request_model = request_model
        self.context: TraceContext | None = None

    def __enter__(self) -> ProviderModelOperation[_ResponseT]:
        self.context = self._operation.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        return self._operation.__exit__(exc_type, exc_value, traceback)

    async def __aenter__(self) -> ProviderModelOperation[_ResponseT]:
        self.context = await self._operation.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        return await self._operation.__aexit__(exc_type, exc_value, traceback)

    def observe_response(self, response: _ResponseT) -> bool:
        """Extract allowlisted facts; malformed telemetry remains fail-open."""

        try:
            attributes = provider_response_attributes(
                self._provider_name,
                response,
                request_model=self._request_model,
            )
            self._operation.add_end_attributes(attributes)
            return True
        except BaseException as error:
            with suppress(BaseException):
                self._runtime._on_error(RuntimeErrorContext("adapter", error, 1))
            return False

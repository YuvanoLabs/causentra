"""Google ADK plugin that emits privacy-safe Causentra lifecycles.

The adapter uses ADK's public ``BasePlugin`` callbacks. It deliberately ignores
user messages, prompt contents, tool arguments, tool results, and model output.
Returning ``None`` from every observation callback preserves ADK behavior.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from ..adapter import AdapterEventBridge
from ..types import EventAttributes, EventExporter, Redactor, TraceContext

try:  # Keeps the dependency-free base package importable.
    from google.adk.plugins import BasePlugin as _BasePlugin
except ImportError:  # pragma: no cover - exercised by dependency-free installs

    class _BasePlugin:  # type: ignore[no-redef]
        def __init__(self, name: str) -> None:
            self.name = name


@dataclass(slots=True)
class _Operation:
    trace_id: str
    span_id: str
    parent_span_id: str
    name: str
    started: float
    attributes: EventAttributes
    key: str


class GoogleADKPlugin(_BasePlugin):  # type: ignore[misc]
    """Observe a Google ADK ``App`` without capturing application payloads."""

    def __init__(
        self,
        service_name: str,
        exporter: EventExporter,
        *,
        name: str = "causentra",
        redactor: Redactor | None = None,
        on_error: Any = None,
        parent_context: TraceContext | None = None,
        shutdown_on_close: bool = False,
    ) -> None:
        super().__init__(name=name)
        options: dict[str, Any] = {"parent_context": parent_context, "on_error": on_error}
        if redactor is not None:
            options["redactor"] = redactor
        self._bridge = AdapterEventBridge(service_name, exporter, **options)
        self._shutdown_on_close = shutdown_on_close
        self._roots: dict[str, tuple[str, float, str | None]] = {}
        self._operations: dict[tuple[str, str, str], list[_Operation]] = defaultdict(list)
        self._active_agents: dict[str, list[_Operation]] = defaultdict(list)
        self._counter = 0
        self._lock = threading.RLock()

    async def on_user_message_callback(
        self, *, invocation_context: Any, user_message: Any
    ) -> None:
        """Ignore message content and allow the original message to proceed."""

        del invocation_context, user_message
        return None

    async def before_run_callback(self, *, invocation_context: Any) -> None:
        invocation_id = _invocation_id(invocation_context)
        self._ensure_root(invocation_id, invocation_context)
        return None

    async def on_event_callback(self, *, invocation_context: Any, event: Any) -> None:
        """Observe no event bodies; detailed lifecycles use dedicated callbacks."""

        del invocation_context, event
        return None

    async def after_run_callback(self, *, invocation_context: Any) -> None:
        invocation_id = _invocation_id(invocation_context)
        self._finish_pending(invocation_id)
        with self._lock:
            root = self._roots.pop(invocation_id, None)
        if root is not None:
            root_span, started, session_id = root
            self._bridge.emit(
                external_trace_id=invocation_id,
                external_span_id=root_span,
                external_session_id=session_id,
                event_type="trace.end",
                name=_root_name(invocation_context),
                status="ok",
                duration_ms=(time.monotonic() - started) * 1_000,
                attributes={"framework.name": "google-adk"},
            )
        return None

    async def before_agent_callback(self, *, agent: Any, callback_context: Any) -> None:
        invocation_id = _context_invocation_id(callback_context)
        root = self._ensure_root(invocation_id, callback_context)
        operation = self._start(
            invocation_id,
            "agent",
            _context_key(callback_context, "agent"),
            _text(agent, "name", "agent"),
            root,
            {"framework.name": "google-adk", "framework.operation.family": "agent"},
        )
        with self._lock:
            self._active_agents[invocation_id].append(operation)
        return None

    async def after_agent_callback(self, *, agent: Any, callback_context: Any) -> None:
        del agent
        invocation_id = _context_invocation_id(callback_context)
        operation = self._end_by_prefix(invocation_id, "agent", callback_context, None)
        if operation is not None:
            with self._lock:
                active = self._active_agents.get(invocation_id, [])
                if operation in active:
                    active.remove(operation)
        return None

    async def before_model_callback(
        self, *, callback_context: Any, llm_request: Any
    ) -> None:
        invocation_id = _context_invocation_id(callback_context)
        root = self._ensure_root(invocation_id, callback_context)
        model = _optional_text(llm_request, "model")
        attributes: EventAttributes = {
            "framework.name": "google-adk",
            "framework.operation.family": "model",
        }
        if model is not None:
            attributes["gen_ai.request.model"] = model
        self._start(
            invocation_id,
            "model",
            _context_key(callback_context, "model"),
            model or "model",
            self._parent(invocation_id, root),
            attributes,
        )
        return None

    async def after_model_callback(
        self, *, callback_context: Any, llm_response: Any
    ) -> None:
        invocation_id = _context_invocation_id(callback_context)
        attributes = _model_response_attributes(llm_response)
        self._end_by_prefix(invocation_id, "model", callback_context, None, attributes)
        return None

    async def on_model_error_callback(
        self, *, callback_context: Any, llm_request: Any, error: Exception
    ) -> None:
        del llm_request
        invocation_id = _context_invocation_id(callback_context)
        self._end_by_prefix(invocation_id, "model", callback_context, error)
        return None

    async def before_tool_callback(
        self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any
    ) -> None:
        del tool_args
        invocation_id = _context_invocation_id(tool_context)
        root = self._ensure_root(invocation_id, tool_context)
        tool_name = _text(tool, "name", type(tool).__name__)
        self._start(
            invocation_id,
            "tool",
            _context_key(tool_context, "tool"),
            tool_name,
            self._parent(invocation_id, root),
            {
                "framework.name": "google-adk",
                "framework.operation.family": "tool",
            },
        )
        return None

    async def after_tool_callback(
        self,
        *,
        tool: Any,
        tool_args: dict[str, Any],
        tool_context: Any,
        result: dict[str, Any],
    ) -> None:
        del tool, tool_args, result
        invocation_id = _context_invocation_id(tool_context)
        self._end_by_prefix(invocation_id, "tool", tool_context, None)
        return None

    async def on_tool_error_callback(
        self,
        *,
        tool: Any,
        tool_args: dict[str, Any],
        tool_context: Any,
        error: Exception,
    ) -> None:
        del tool, tool_args
        invocation_id = _context_invocation_id(tool_context)
        self._end_by_prefix(invocation_id, "tool", tool_context, error)
        return None

    async def close(self) -> None:
        if self._shutdown_on_close:
            self._bridge.shutdown(5.0)
        else:
            self._bridge.flush(5.0)

    def flush(self, timeout: float | None = None) -> bool:
        return bool(self._bridge.flush(timeout))

    def shutdown(self, timeout: float | None = 5.0) -> None:
        self._bridge.shutdown(timeout)

    def _ensure_root(self, invocation_id: str, context: Any) -> str:
        with self._lock:
            existing = self._roots.get(invocation_id)
            if existing is not None:
                return existing[0]
            root_span = f"{invocation_id}:root"
            session_id = _session_id(context)
            self._roots[invocation_id] = (root_span, time.monotonic(), session_id)
        self._bridge.emit(
            external_trace_id=invocation_id,
            external_span_id=root_span,
            external_session_id=session_id,
            event_type="trace.start",
            name=_root_name(context),
            attributes={"framework.name": "google-adk"},
        )
        return root_span

    def _start(
        self,
        invocation_id: str,
        family: str,
        key: str,
        name: str,
        parent_span_id: str,
        attributes: EventAttributes,
    ) -> _Operation:
        with self._lock:
            self._counter += 1
            span_id = f"{key}:{self._counter}"
            operation = _Operation(
                invocation_id,
                span_id,
                parent_span_id,
                name[:256],
                time.monotonic(),
                attributes,
                key,
            )
            self._operations[(invocation_id, family, key)].append(operation)
        self._bridge.emit(
            external_trace_id=invocation_id,
            external_span_id=span_id,
            external_parent_span_id=parent_span_id,
            event_type=f"{family}.start",
            name=operation.name,
            attributes=attributes,
        )
        return operation

    def _end_by_prefix(
        self,
        invocation_id: str,
        family: str,
        context: Any,
        error: BaseException | None,
        extra: EventAttributes | None = None,
    ) -> _Operation | None:
        with self._lock:
            key = _context_key(context, family) if context is not None else ""
            operation_key = (invocation_id, family, key)
            operations = self._operations.get(operation_key, [])
            operation = operations.pop() if operations else None
            if not operations:
                self._operations.pop(operation_key, None)
            if operation is None:
                candidates = [
                    (candidate_key, candidate_operations[-1])
                    for candidate_key, candidate_operations in self._operations.items()
                    if candidate_key[0] == invocation_id
                    and candidate_key[1] == family
                    and candidate_operations
                ]
                if candidates:
                    fallback_key, operation = max(
                        candidates, key=lambda candidate: candidate[1].started
                    )
                    fallback_operations = self._operations[fallback_key]
                    fallback_operations.pop()
                    if not fallback_operations:
                        self._operations.pop(fallback_key, None)
        if operation is None:
            return None
        attributes = dict(operation.attributes)
        attributes.update(extra or {})
        if error is not None:
            attributes["error.type"] = type(error).__name__[:128]
        self._bridge.emit(
            external_trace_id=invocation_id,
            external_span_id=operation.span_id,
            external_parent_span_id=operation.parent_span_id,
            event_type=f"{family}.end",
            name=operation.name,
            status="error" if error is not None else "ok",
            duration_ms=(time.monotonic() - operation.started) * 1_000,
            attributes=attributes,
        )
        return operation

    def _parent(self, invocation_id: str, fallback: str) -> str:
        with self._lock:
            active = self._active_agents.get(invocation_id, [])
            return active[-1].span_id if active else fallback

    def _finish_pending(self, invocation_id: str) -> None:
        with self._lock:
            families = [
                family
                for trace_id, family, _key in self._operations
                if trace_id == invocation_id
            ]
        for family in families:
            while self._end_by_prefix(
                invocation_id,
                family,
                None,
                RuntimeError("ADK lifecycle ended without a matching callback"),
            ):
                pass
        with self._lock:
            self._active_agents.pop(invocation_id, None)


def create_google_adk_plugin(
    service_name: str, exporter: EventExporter, **kwargs: Any
) -> GoogleADKPlugin:
    """Create a plugin for ``App(..., plugins=[plugin])``."""

    return GoogleADKPlugin(service_name, exporter, **kwargs)


def _invocation_id(context: Any) -> str:
    value = getattr(context, "invocation_id", None)
    return str(value) if value else f"adk-invocation:{id(context)}"


def _context_invocation_id(context: Any) -> str:
    value = getattr(context, "invocation_id", None)
    if value:
        return str(value)
    invocation_context = getattr(context, "_invocation_context", None)
    return _invocation_id(invocation_context or context)


def _context_key(context: Any, family: str) -> str:
    call_id = getattr(context, "function_call_id", None)
    node_path = getattr(context, "node_path", None)
    return f"{family}:{call_id or node_path or id(context)}"


def _root_name(context: Any) -> str:
    agent = getattr(context, "agent", None)
    agent_name = _optional_text(agent, "name") or _optional_text(context, "agent_name")
    return f"{agent_name or 'google-adk'}-run"[:256]


def _session_id(context: Any) -> str | None:
    session = getattr(context, "session", None)
    value = getattr(session, "id", None)
    return str(value) if value else None


def _text(value: Any, key: str, fallback: str) -> str:
    candidate = getattr(value, key, None)
    return candidate[:256] if isinstance(candidate, str) and candidate else fallback[:256]


def _optional_text(value: Any, key: str) -> str | None:
    candidate = getattr(value, key, None)
    return candidate[:256] if isinstance(candidate, str) and candidate else None


def _model_response_attributes(response: Any) -> EventAttributes:
    result: EventAttributes = {}
    model = _optional_text(response, "model_version")
    if model is not None:
        result["gen_ai.response.model"] = model
    usage = getattr(response, "usage_metadata", None)
    for source, target in (
        ("prompt_token_count", "gen_ai.usage.input_tokens"),
        ("candidates_token_count", "gen_ai.usage.output_tokens"),
        ("total_token_count", "gen_ai.usage.total_tokens"),
        ("cached_content_token_count", "gen_ai.usage.cache_read_tokens"),
        ("thoughts_token_count", "gen_ai.usage.reasoning_tokens"),
    ):
        value = getattr(usage, source, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[target] = value
    finish_reason = getattr(response, "finish_reason", None)
    if finish_reason is not None:
        reason = getattr(finish_reason, "value", finish_reason)
        if isinstance(reason, str) and reason:
            result["gen_ai.response.finish_reason"] = reason[:128]
    return result

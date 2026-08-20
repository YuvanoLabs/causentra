"""Semantic Kernel invocation filter with payload-deny-by-default telemetry."""

from __future__ import annotations

import contextvars
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ..adapter import AdapterEventBridge
from ..types import EventAttributes, EventExporter, Redactor, TraceContext

_active_operation: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "causentra_semantic_kernel_operation", default=None
)


class SemanticKernelFilterAdapter:
    """Instrument Semantic Kernel functions through its public filter API.

    Function arguments, rendered prompts, function results, and exception
    messages are never read. The filter always delegates exactly once and
    re-raises application exceptions unchanged.
    """

    def __init__(
        self,
        service_name: str,
        exporter: EventExporter,
        *,
        redactor: Redactor | None = None,
        on_error: Any = None,
        parent_context: TraceContext | None = None,
    ) -> None:
        options: dict[str, Any] = {"parent_context": parent_context, "on_error": on_error}
        if redactor is not None:
            options["redactor"] = redactor
        self._bridge = AdapterEventBridge(service_name, exporter, **options)
        self._counter = 0
        self._lock = threading.Lock()

    def install(self, kernel: Any) -> SemanticKernelFilterAdapter:
        """Register this adapter on a ``semantic_kernel.Kernel`` instance."""

        try:
            from semantic_kernel.filters import FilterTypes
        except ImportError as error:  # pragma: no cover - optional dependency guard
            raise ImportError(
                "Semantic Kernel support requires causentra[semantic-kernel]"
            ) from error
        kernel.add_filter(FilterTypes.FUNCTION_INVOCATION, self.function_invocation_filter)
        return self

    async def function_invocation_filter(
        self,
        context: Any,
        next: Callable[[Any], Awaitable[None]],
    ) -> None:
        """Wrap one function invocation without inspecting arguments or results."""

        function = getattr(context, "function", None)
        function_name = _text(function, "name", "function")
        plugin_name = _optional_text(function, "plugin_name")
        name = f"{plugin_name}.{function_name}" if plugin_name else function_name
        parent = _active_operation.get()
        owns_trace = parent is None
        with self._lock:
            self._counter += 1
            sequence = self._counter
        trace_id = parent[0] if parent else f"semantic-kernel:{sequence}:{id(context)}"
        root_span = f"{trace_id}:root"
        parent_span = parent[1] if parent else root_span
        span_id = f"semantic-kernel:function:{sequence}:{id(context)}"
        attributes: EventAttributes = {
            "framework.name": "semantic-kernel",
            "framework.operation.family": "tool",
            "semantic_kernel.function.name": function_name,
        }
        if plugin_name is not None:
            attributes["semantic_kernel.plugin.name"] = plugin_name
        is_prompt = getattr(function, "is_prompt", None)
        if isinstance(is_prompt, bool):
            attributes["semantic_kernel.function.is_prompt"] = is_prompt
        is_streaming = getattr(context, "is_streaming", None)
        if isinstance(is_streaming, bool):
            attributes["semantic_kernel.function.is_streaming"] = is_streaming
        started = time.monotonic()
        if owns_trace:
            self._bridge.emit(
                external_trace_id=trace_id,
                external_span_id=root_span,
                event_type="trace.start",
                name=f"{name}-invocation",
                attributes={"framework.name": "semantic-kernel"},
            )
        self._bridge.emit(
            external_trace_id=trace_id,
            external_span_id=span_id,
            external_parent_span_id=parent_span,
            event_type="tool.start",
            name=name,
            attributes=attributes,
        )
        token = _active_operation.set((trace_id, span_id))
        failure: BaseException | None = None
        try:
            await next(context)
        except BaseException as error:
            failure = error
            raise
        finally:
            _active_operation.reset(token)
            finished_attributes = dict(attributes)
            if failure is not None:
                finished_attributes["error.type"] = type(failure).__name__[:128]
            duration = (time.monotonic() - started) * 1_000
            self._bridge.emit(
                external_trace_id=trace_id,
                external_span_id=span_id,
                external_parent_span_id=parent_span,
                event_type="tool.end",
                name=name,
                status="error" if failure is not None else "ok",
                duration_ms=duration,
                attributes=finished_attributes,
            )
            if owns_trace:
                self._bridge.emit(
                    external_trace_id=trace_id,
                    external_span_id=root_span,
                    event_type="trace.end",
                    name=f"{name}-invocation",
                    status="error" if failure is not None else "ok",
                    duration_ms=duration,
                    attributes={"framework.name": "semantic-kernel"},
                )

    def flush(self, timeout: float | None = None) -> bool:
        return bool(self._bridge.flush(timeout))

    def shutdown(self, timeout: float | None = 5.0) -> None:
        self._bridge.shutdown(timeout)


def install_semantic_kernel_filters(
    kernel: Any,
    service_name: str,
    exporter: EventExporter,
    **kwargs: Any,
) -> SemanticKernelFilterAdapter:
    """Create and install a privacy-safe function filter on ``kernel``."""

    return SemanticKernelFilterAdapter(service_name, exporter, **kwargs).install(kernel)


def _text(value: Any, key: str, fallback: str) -> str:
    candidate = getattr(value, key, None)
    return candidate[:256] if isinstance(candidate, str) and candidate else fallback


def _optional_text(value: Any, key: str) -> str | None:
    candidate = getattr(value, key, None)
    return candidate[:256] if isinstance(candidate, str) and candidate else None

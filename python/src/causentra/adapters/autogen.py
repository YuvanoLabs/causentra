"""Microsoft AutoGen OpenTelemetry bridge with a strict attribute allowlist."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from ..adapter import AdapterEventBridge
from ..types import EventAttributes, EventExporter, EventStatus, JsonValue, Redactor, TraceContext

_ALLOWED_ATTRIBUTES = frozenset(
    {
        "error.type",
        "gen_ai.agent.id",
        "gen_ai.agent.name",
        "gen_ai.operation.name",
        "gen_ai.request.model",
        "gen_ai.response.finish_reasons",
        "gen_ai.response.model",
        "gen_ai.system",
        "gen_ai.tool.call.id",
        "gen_ai.tool.name",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "messaging.destination",
        "messaging.message.envelope.size",
        "messaging.message.type",
        "messaging.operation",
    }
)


class AutoGenSpanExporter:
    """Consume completed AutoGen spans through the official OTel SDK boundary.

    AutoGen supplies this exporter through a ``TracerProvider``. Span events,
    exception messages, agent descriptions, prompts, message bodies, and tool
    arguments are intentionally discarded.
    """

    def __init__(
        self,
        service_name: str,
        exporter: EventExporter,
        *,
        redactor: Redactor | None = None,
        on_error: Any = None,
        parent_context: TraceContext | None = None,
        max_trace_history: int = 10_000,
    ) -> None:
        if max_trace_history <= 0:
            raise ValueError("max_trace_history must be positive")
        options: dict[str, Any] = {"parent_context": parent_context, "on_error": on_error}
        if redactor is not None:
            options["redactor"] = redactor
        self._bridge = AdapterEventBridge(service_name, exporter, **options)
        self._open_traces: dict[str, tuple[str, datetime]] = {}
        self._closed_traces: OrderedDict[str, None] = OrderedDict()
        self._max_trace_history = max_trace_history
        self._lock = threading.RLock()
        self._closed = False

    def export(self, spans: Sequence[Any]) -> Any:
        """Export a batch using the ``opentelemetry.sdk.trace.SpanExporter`` contract."""

        if self._closed:
            return _span_export_result(False)
        success = True
        for span in spans:
            try:
                self._export_span(span)
            except BaseException:
                success = False
        return _span_export_result(success)

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return bool(self._bridge.flush(max(0.0, timeout_millis / 1_000)))

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._lock:
            traces = list(self._open_traces.items())
            self._open_traces.clear()
        now = datetime.now(timezone.utc)
        for trace_id, (name, started) in traces:
            self._bridge.emit(
                external_trace_id=trace_id,
                external_span_id=f"{trace_id}:root",
                event_type="trace.end",
                name=name,
                status="unset",
                timestamp=now,
                duration_ms=max(0.0, (now - started).total_seconds() * 1_000),
                attributes={"framework.name": "autogen"},
            )
        self._bridge.flush(5.0)

    def _export_span(self, span: Any) -> None:
        context = getattr(span, "context", None)
        trace_id = _hex_identifier(getattr(context, "trace_id", None), 32)
        span_id = _hex_identifier(getattr(context, "span_id", None), 16)
        parent_context = getattr(span, "parent", None)
        parent_id = _optional_hex_identifier(getattr(parent_context, "span_id", None), 16)
        started = _timestamp(getattr(span, "start_time", None))
        ended = _timestamp(getattr(span, "end_time", None))
        attributes = _attributes(span)
        family = _family(attributes, str(getattr(span, "name", "autogen-operation")))
        name = _operation_name(span, attributes)
        root_span = f"{trace_id}:root"
        with self._lock:
            if trace_id not in self._open_traces and trace_id not in self._closed_traces:
                self._open_traces[trace_id] = (f"{name}-trace", started)
                start_trace = True
            else:
                start_trace = False
        if start_trace:
            self._bridge.emit(
                external_trace_id=trace_id,
                external_span_id=root_span,
                event_type="trace.start",
                name=f"{name}-trace",
                timestamp=started,
                attributes={"framework.name": "autogen"},
            )
        self._bridge.emit(
            external_trace_id=trace_id,
            external_span_id=span_id,
            external_parent_span_id=parent_id or root_span,
            event_type=f"{family}.start",
            name=name,
            timestamp=started,
            attributes=attributes,
        )
        status = _status(span)
        self._bridge.emit(
            external_trace_id=trace_id,
            external_span_id=span_id,
            external_parent_span_id=parent_id or root_span,
            event_type=f"{family}.end",
            name=name,
            status=status,
            timestamp=ended,
            duration_ms=max(0.0, (ended - started).total_seconds() * 1_000),
            attributes=attributes,
        )
        if parent_id is None:
            with self._lock:
                root = self._open_traces.pop(trace_id, (f"{name}-trace", started))
                self._closed_traces[trace_id] = None
                self._closed_traces.move_to_end(trace_id)
                while len(self._closed_traces) > self._max_trace_history:
                    self._closed_traces.popitem(last=False)
            self._bridge.emit(
                external_trace_id=trace_id,
                external_span_id=root_span,
                event_type="trace.end",
                name=root[0],
                status=status,
                timestamp=ended,
                duration_ms=max(0.0, (ended - root[1]).total_seconds() * 1_000),
                attributes={"framework.name": "autogen"},
            )


def create_autogen_tracer_provider(
    service_name: str,
    exporter: EventExporter,
    *,
    batch: bool = True,
    **kwargs: Any,
) -> Any:
    """Create a provider for AutoGen's ``tracer_provider=`` constructor argument."""

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    except ImportError as error:  # pragma: no cover - optional dependency guard
        raise ImportError("AutoGen support requires causentra[autogen]") from error
    span_exporter = AutoGenSpanExporter(service_name, exporter, **kwargs)
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    processor = (
        BatchSpanProcessor(span_exporter) if batch else SimpleSpanProcessor(span_exporter)
    )
    provider.add_span_processor(processor)
    return provider


def _attributes(span: Any) -> EventAttributes:
    raw = getattr(span, "attributes", None)
    result: EventAttributes = {"framework.name": "autogen"}
    scope = getattr(span, "instrumentation_scope", None)
    scope_name = getattr(scope, "name", None)
    if isinstance(scope_name, str) and scope_name:
        result["framework.instrumentation.name"] = scope_name[:256]
    if not isinstance(raw, Mapping):
        return result
    for key in _ALLOWED_ATTRIBUTES:
        if key not in raw:
            continue
        value = _json_attribute(raw[key])
        if value is not None:
            result[key] = value
    return result


def _json_attribute(value: Any) -> JsonValue | None:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Iterable) and not isinstance(value, Mapping | bytes | bytearray):
        converted: list[JsonValue] = []
        for item in value:
            if isinstance(item, str | int | float | bool) or item is None:
                converted.append(item)
        return converted[:64]
    return None


def _family(attributes: EventAttributes, name: str) -> str:
    operation = attributes.get("gen_ai.operation.name")
    if operation in {"execute_tool"}:
        return "tool"
    if operation in {"create_agent", "invoke_agent"}:
        return "agent"
    if operation in {"chat", "embeddings", "generate_content", "text_completion"}:
        return "model"
    if "messaging.operation" in attributes or name.startswith("autogen "):
        return "agent.message"
    return "span"


def _operation_name(span: Any, attributes: EventAttributes) -> str:
    for key in ("gen_ai.tool.name", "gen_ai.agent.name"):
        candidate = attributes.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate[:256]
    candidate = getattr(span, "name", None)
    return candidate[:256] if isinstance(candidate, str) and candidate else "autogen-operation"


def _status(span: Any) -> EventStatus:
    status = getattr(span, "status", None)
    code = getattr(status, "status_code", None)
    name = getattr(code, "name", None)
    if name == "ERROR":
        return "error"
    if name == "OK":
        return "ok"
    return "unset"


def _timestamp(value: Any) -> datetime:
    if isinstance(value, int) and value >= 0:
        return datetime.fromtimestamp(value / 1_000_000_000, timezone.utc)
    return datetime.now(timezone.utc)


def _hex_identifier(value: Any, width: int) -> str:
    if isinstance(value, int) and value > 0:
        return f"{value:0{width}x}"[-width:]
    return ("0" * (width - 1)) + "1"


def _optional_hex_identifier(value: Any, width: int) -> str | None:
    return _hex_identifier(value, width) if isinstance(value, int) and value > 0 else None


def _span_export_result(success: bool) -> Any:
    try:
        from opentelemetry.sdk.trace.export import SpanExportResult
    except ImportError:  # pragma: no cover - only reached without OTel SDK
        return 0 if success else 1
    return SpanExportResult.SUCCESS if success else SpanExportResult.FAILURE

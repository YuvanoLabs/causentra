"""OpenAI Agents SDK tracing processor with privacy-safe field selection."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from ..adapter import AdapterEventBridge
from ..relationships import relationship_attributes
from ..types import EventAttributes, EventExporter, Redactor, TraceContext

try:  # Keeps the base package dependency-free.
    from agents.tracing import TracingProcessor as _TracingProcessor
except ImportError:  # pragma: no cover - exercised by dependency-free installs

    class _TracingProcessor:  # type: ignore[no-redef]
        pass


class OpenAIAgentsTracingProcessor(_TracingProcessor):  # type: ignore[misc]
    """Translate official SDK trace callbacks without capturing prompts/results."""

    def __init__(
        self,
        service_name: str,
        exporter: EventExporter,
        *,
        redactor: Redactor | None = None,
        on_error: Any = None,
        parent_context: TraceContext | None = None,
        include_error_message: bool = False,
    ) -> None:
        options: dict[str, Any] = {"parent_context": parent_context, "on_error": on_error}
        if redactor is not None:
            options["redactor"] = redactor
        self._bridge = AdapterEventBridge(service_name, exporter, **options)
        self._include_error_message = include_error_message
        self._starts: dict[str, float] = {}
        self._lock = threading.Lock()

    def on_trace_start(self, trace: Any) -> None:
        trace_id = str(trace.trace_id)
        with self._lock:
            self._starts[trace_id] = time.monotonic()
        self._bridge.emit(
            external_trace_id=trace_id,
            external_span_id=f"{trace_id}:root",
            external_session_id=_optional(trace, "group_id"),
            event_type="trace.start",
            name=_text(getattr(trace, "name", None), "openai-agents-run"),
            attributes={"framework.name": "openai-agents"},
        )

    def on_trace_end(self, trace: Any) -> None:
        trace_id = str(trace.trace_id)
        with self._lock:
            started = self._starts.pop(trace_id, None)
        self._bridge.emit(
            external_trace_id=trace_id,
            external_span_id=f"{trace_id}:root",
            external_session_id=_optional(trace, "group_id"),
            event_type="trace.end",
            name=_text(getattr(trace, "name", None), "openai-agents-run"),
            status="ok",
            duration_ms=None if started is None else (time.monotonic() - started) * 1_000,
            attributes={"framework.name": "openai-agents"},
        )

    def on_span_start(self, span: Any) -> None:
        data = getattr(span, "span_data", None)
        framework_type = _text(getattr(data, "type", None), "custom")
        family = _family(framework_type)
        self._bridge.emit(
            external_trace_id=str(span.trace_id),
            external_span_id=str(span.span_id),
            external_parent_span_id=_optional(span, "parent_id") or f"{span.trace_id}:root",
            event_type=_lifecycle(framework_type, family, "start"),
            name=_span_name(data),
            timestamp=_timestamp(getattr(span, "started_at", None)),
            attributes=_span_attributes(span, data),
        )

    def on_span_end(self, span: Any) -> None:
        data = getattr(span, "span_data", None)
        framework_type = _text(getattr(data, "type", None), "custom")
        family = _family(framework_type)
        error = getattr(span, "error", None)
        attributes = _span_attributes(span, data)
        if error is not None:
            attributes["error.type"] = type(error).__name__[:128]
            if self._include_error_message:
                message = getattr(error, "message", None) or str(error)
                attributes["error.message"] = str(message)[:1_024]
        self._bridge.emit(
            external_trace_id=str(span.trace_id),
            external_span_id=str(span.span_id),
            external_parent_span_id=_optional(span, "parent_id") or f"{span.trace_id}:root",
            event_type=_lifecycle(framework_type, family, "end"),
            name=_span_name(data),
            timestamp=_timestamp(getattr(span, "ended_at", None)),
            duration_ms=_duration(
                getattr(span, "started_at", None), getattr(span, "ended_at", None)
            ),
            status="error" if error is not None else "ok",
            attributes=attributes,
        )

    def force_flush(self) -> None:
        self._bridge.flush()

    def shutdown(self) -> None:
        self._bridge.shutdown(5.0)


def create_openai_agents_processor(
    service_name: str, exporter: EventExporter, **kwargs: Any
) -> OpenAIAgentsTracingProcessor:
    """Create a processor for ``agents.add_trace_processor(processor)``."""

    return OpenAIAgentsTracingProcessor(service_name, exporter, **kwargs)


def _family(value: str) -> str:
    if value == "agent":
        return "agent"
    if value in {"generation", "response", "transcription", "speech", "speech_group"}:
        return "model"
    if value in {"function", "mcp_tools"}:
        return "tool"
    return "span"


def _lifecycle(framework_type: str, family: str, phase: str) -> str:
    return f"agent.handoff.{phase}" if framework_type == "handoff" else f"{family}.{phase}"


def _span_name(data: Any) -> str:
    for key in ("name", "model", "server", "type"):
        candidate = getattr(data, key, None)
        if isinstance(candidate, str) and candidate:
            return candidate[:256]
    return "openai-agents-operation"


def _span_attributes(span: Any, data: Any) -> EventAttributes:
    framework_type = _text(getattr(data, "type", None), "custom")
    result: EventAttributes = {
        "framework.name": "openai-agents",
        "framework.span.type": framework_type,
    }
    model = getattr(data, "model", None)
    if isinstance(model, str):
        result["gen_ai.request.model"] = model
    triggered = getattr(data, "triggered", None)
    if isinstance(triggered, bool):
        result["guardrail.triggered"] = triggered
    from_agent = _agent_name(getattr(data, "from_agent", None))
    to_agent = _agent_name(getattr(data, "to_agent", None))
    if from_agent and to_agent:
        result.update(relationship_attributes("handoff", from_agent, to_agent, str(span.span_id)))
    usage = getattr(data, "usage", None)
    for key, canonical in (
        ("input_tokens", "gen_ai.usage.input_tokens"),
        ("output_tokens", "gen_ai.usage.output_tokens"),
    ):
        value = getattr(usage, key, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[canonical] = value
    return result


def _agent_name(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value[:256]
    name = getattr(value, "name", None)
    return name[:256] if isinstance(name, str) and name else None


def _optional(value: Any, key: str) -> str | None:
    item = getattr(value, key, None)
    return str(item) if item is not None else None


def _text(value: Any, fallback: str) -> str:
    return value[:256] if isinstance(value, str) and value else fallback


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration(start: Any, end: Any) -> float | None:
    left, right = _timestamp(start), _timestamp(end)
    if left is None or right is None:
        return None
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return max(0.0, (right - left).total_seconds() * 1_000)

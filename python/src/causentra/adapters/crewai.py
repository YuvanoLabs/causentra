"""CrewAI event-bus listener with cross-framework lifecycle normalization."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..adapter import AdapterEventBridge
from ..types import EventAttributes, EventExporter, Redactor, TraceContext

try:  # Keeps the dependency-free base package importable.
    from crewai.events import (  # type: ignore[import-untyped]
        BaseEventListener as _BaseEventListener,
    )
except ImportError:  # pragma: no cover - exercised by dependency-free installs

    class _BaseEventListener:  # type: ignore[no-redef]
        def __init__(self) -> None:
            return None


@dataclass(slots=True)
class _Operation:
    trace_id: str
    span_id: str
    parent_span_id: str
    family: str
    name: str
    started_at: datetime | None
    started: float
    attributes: EventAttributes
    owns_trace: bool


class CrewAIEventListener(_BaseEventListener):  # type: ignore[misc]
    """Translate CrewAI events while excluding prompts, inputs, and outputs."""

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
        self._starts: dict[str, _Operation] = {}
        self._event_traces: dict[str, str] = {}
        self._trace_roots: dict[str, tuple[str, datetime | None, float, str]] = {}
        self._registrations: list[tuple[Any, Any, Any]] = []
        self._lock = threading.RLock()
        super().__init__()

    def setup_listeners(self, crewai_event_bus: Any) -> None:
        """Register against CrewAI's public singleton event bus."""

        try:
            from crewai.events.types.agent_events import (  # type: ignore[import-untyped]
                AgentExecutionCompletedEvent,
                AgentExecutionErrorEvent,
                AgentExecutionStartedEvent,
                LiteAgentExecutionCompletedEvent,
                LiteAgentExecutionErrorEvent,
                LiteAgentExecutionStartedEvent,
            )
            from crewai.events.types.crew_events import (  # type: ignore[import-untyped]
                CrewKickoffCompletedEvent,
                CrewKickoffFailedEvent,
                CrewKickoffStartedEvent,
            )
            from crewai.events.types.llm_events import (  # type: ignore[import-untyped]
                LLMCallCompletedEvent,
                LLMCallFailedEvent,
                LLMCallStartedEvent,
            )
            from crewai.events.types.task_events import (  # type: ignore[import-untyped]
                TaskCompletedEvent,
                TaskFailedEvent,
                TaskStartedEvent,
            )
            from crewai.events.types.tool_usage_events import (  # type: ignore[import-untyped]
                ToolUsageErrorEvent,
                ToolUsageFinishedEvent,
                ToolUsageStartedEvent,
            )
        except ImportError as error:  # pragma: no cover - optional dependency guard
            raise ImportError("CrewAI support requires causentra[crewai]") from error

        registrations = (
            (CrewKickoffStartedEvent, self._on_crew_started),
            (CrewKickoffCompletedEvent, self._on_crew_completed),
            (CrewKickoffFailedEvent, self._on_crew_failed),
            (AgentExecutionStartedEvent, self._on_agent_started),
            (AgentExecutionCompletedEvent, self._on_agent_completed),
            (AgentExecutionErrorEvent, self._on_agent_failed),
            (LiteAgentExecutionStartedEvent, self._on_agent_started),
            (LiteAgentExecutionCompletedEvent, self._on_agent_completed),
            (LiteAgentExecutionErrorEvent, self._on_agent_failed),
            (TaskStartedEvent, self._on_task_started),
            (TaskCompletedEvent, self._on_task_completed),
            (TaskFailedEvent, self._on_task_failed),
            (ToolUsageStartedEvent, self._on_tool_started),
            (ToolUsageFinishedEvent, self._on_tool_completed),
            (ToolUsageErrorEvent, self._on_tool_failed),
            (LLMCallStartedEvent, self._on_model_started),
            (LLMCallCompletedEvent, self._on_model_completed),
            (LLMCallFailedEvent, self._on_model_failed),
        )
        for event_type, handler in registrations:
            crewai_event_bus.on(event_type)(handler)
            self._registrations.append((crewai_event_bus, event_type, handler))

    def shutdown(self, timeout: float | None = 5.0) -> None:
        """Unregister handlers and shut down the configured exporter."""

        for bus, event_type, handler in self._registrations:
            bus.off(event_type, handler)
        self._registrations.clear()
        self._bridge.shutdown(timeout)

    def flush(self, timeout: float | None = None) -> bool:
        return bool(self._bridge.flush(timeout))

    def _on_crew_started(self, source: Any, event: Any) -> None:
        del source
        event_id = _event_id(event)
        name = _text(event, "crew_name", "crew")
        timestamp = _timestamp(event)
        with self._lock:
            if event_id in self._trace_roots:
                return
            self._trace_roots[event_id] = (event_id, timestamp, time.monotonic(), name)
            self._event_traces[event_id] = event_id
        self._bridge.emit(
            external_trace_id=event_id,
            external_span_id=event_id,
            event_type="trace.start",
            name=name,
            timestamp=timestamp,
            attributes={"framework.name": "crewai"},
        )

    def _on_crew_completed(self, source: Any, event: Any) -> None:
        del source
        attributes: EventAttributes = {"framework.name": "crewai"}
        total = getattr(event, "total_tokens", None)
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
            attributes["gen_ai.usage.total_tokens"] = total
        self._end_trace(event, "ok", attributes)

    def _on_crew_failed(self, source: Any, event: Any) -> None:
        del source
        self._end_trace(
            event,
            "error",
            {"framework.name": "crewai", "error.type": "CrewKickoffError"},
        )

    def _on_agent_started(self, source: Any, event: Any) -> None:
        del source
        self._start(event, "agent", _agent_name(event), _agent_attributes(event))

    def _on_agent_completed(self, source: Any, event: Any) -> None:
        del source
        self._end(event, "agent", None)

    def _on_agent_failed(self, source: Any, event: Any) -> None:
        del source
        self._end(event, "agent", RuntimeError("CrewAI agent execution failed"))

    def _on_task_started(self, source: Any, event: Any) -> None:
        del source
        self._start(event, "agent.task", _task_name(event), _task_attributes(event))

    def _on_task_completed(self, source: Any, event: Any) -> None:
        del source
        self._end(event, "agent.task", None)

    def _on_task_failed(self, source: Any, event: Any) -> None:
        del source
        self._end(event, "agent.task", RuntimeError("CrewAI task execution failed"))

    def _on_tool_started(self, source: Any, event: Any) -> None:
        del source
        self._start(event, "tool", _text(event, "tool_name", "tool"), _tool_attributes(event))

    def _on_tool_completed(self, source: Any, event: Any) -> None:
        del source
        extra: EventAttributes = {}
        cached = getattr(event, "from_cache", None)
        if isinstance(cached, bool):
            extra["tool.cache.hit"] = cached
        self._end(event, "tool", None, extra)

    def _on_tool_failed(self, source: Any, event: Any) -> None:
        del source
        self._end(event, "tool", RuntimeError("CrewAI tool execution failed"))

    def _on_model_started(self, source: Any, event: Any) -> None:
        del source
        model = _optional_text(event, "model")
        attributes: EventAttributes = {"framework.name": "crewai"}
        if model is not None:
            attributes["gen_ai.request.model"] = model
        self._start(event, "model", model or "model", attributes)

    def _on_model_completed(self, source: Any, event: Any) -> None:
        del source
        self._end(event, "model", None, _usage_attributes(getattr(event, "usage", None)))

    def _on_model_failed(self, source: Any, event: Any) -> None:
        del source
        self._end(event, "model", RuntimeError("CrewAI model call failed"))

    def _start(
        self, event: Any, family: str, name: str, attributes: EventAttributes
    ) -> None:
        event_id = _event_id(event)
        timestamp = _timestamp(event)
        with self._lock:
            if event_id in self._starts:
                return
            trace_id = self._resolve_trace(event)
            owns_trace = trace_id is None
            if trace_id is None:
                trace_id = event_id
                root_span = f"{trace_id}:root"
                self._trace_roots[trace_id] = (
                    root_span,
                    timestamp,
                    time.monotonic(),
                    f"{name}-run",
                )
            else:
                root_span = self._trace_roots[trace_id][0]
            parent_event_id = _optional_text(event, "parent_event_id")
            parent_span = parent_event_id if parent_event_id in self._event_traces else root_span
            operation = _Operation(
                trace_id,
                event_id,
                parent_span,
                family,
                name[:256],
                timestamp,
                time.monotonic(),
                attributes,
                owns_trace,
            )
            self._starts[event_id] = operation
            self._event_traces[event_id] = trace_id
        if owns_trace:
            self._bridge.emit(
                external_trace_id=trace_id,
                external_span_id=root_span,
                event_type="trace.start",
                name=f"{name}-run",
                timestamp=timestamp,
                attributes={"framework.name": "crewai"},
            )
        self._bridge.emit(
            external_trace_id=trace_id,
            external_span_id=event_id,
            external_parent_span_id=parent_span,
            event_type=f"{family}.start",
            name=name,
            timestamp=timestamp,
            attributes=attributes,
        )

    def _end(
        self,
        event: Any,
        family: str,
        error: BaseException | None,
        extra: EventAttributes | None = None,
    ) -> None:
        start_id = _optional_text(event, "started_event_id")
        with self._lock:
            operation = self._starts.pop(start_id or "", None)
        if operation is None or operation.family != family:
            return
        attributes = dict(operation.attributes)
        attributes.update(extra or {})
        if error is not None:
            attributes["error.type"] = type(error).__name__[:128]
        timestamp = _timestamp(event)
        duration = _duration(operation.started_at, timestamp, operation.started)
        self._bridge.emit(
            external_trace_id=operation.trace_id,
            external_span_id=operation.span_id,
            external_parent_span_id=operation.parent_span_id,
            event_type=f"{operation.family}.end",
            name=operation.name,
            status="error" if error is not None else "ok",
            timestamp=timestamp,
            duration_ms=duration,
            attributes=attributes,
        )
        self._remember_event(event, operation.trace_id)
        if operation.owns_trace:
            self._close_trace(operation.trace_id, timestamp, error is not None)

    def _end_trace(self, event: Any, status: str, attributes: EventAttributes) -> None:
        start_id = _optional_text(event, "started_event_id")
        trace_id = start_id or self._resolve_trace(event)
        if trace_id is None:
            return
        with self._lock:
            root = self._trace_roots.pop(trace_id, None)
        if root is None:
            return
        timestamp = _timestamp(event)
        self._bridge.emit(
            external_trace_id=trace_id,
            external_span_id=root[0],
            event_type="trace.end",
            name=root[3],
            status="error" if status == "error" else "ok",
            timestamp=timestamp,
            duration_ms=_duration(root[1], timestamp, root[2]),
            attributes=attributes,
        )
        self._cleanup_trace(trace_id)

    def _close_trace(
        self, trace_id: str, timestamp: datetime | None, failed: bool
    ) -> None:
        with self._lock:
            root = self._trace_roots.pop(trace_id, None)
        if root is None:
            return
        self._bridge.emit(
            external_trace_id=trace_id,
            external_span_id=root[0],
            event_type="trace.end",
            name=root[3],
            status="error" if failed else "ok",
            timestamp=timestamp,
            duration_ms=_duration(root[1], timestamp, root[2]),
            attributes={"framework.name": "crewai"},
        )
        self._cleanup_trace(trace_id)

    def _resolve_trace(self, event: Any) -> str | None:
        for key in ("started_event_id", "parent_event_id", "triggered_by_event_id"):
            event_id = _optional_text(event, key)
            if event_id and event_id in self._event_traces:
                return self._event_traces[event_id]
            if event_id and event_id in self._trace_roots:
                return event_id
        return None

    def _remember_event(self, event: Any, trace_id: str) -> None:
        with self._lock:
            self._event_traces[_event_id(event)] = trace_id

    def _cleanup_trace(self, trace_id: str) -> None:
        with self._lock:
            self._event_traces = {
                event_id: mapped
                for event_id, mapped in self._event_traces.items()
                if mapped != trace_id
            }
            self._starts = {
                event_id: operation
                for event_id, operation in self._starts.items()
                if operation.trace_id != trace_id
            }


def create_crewai_listener(
    service_name: str, exporter: EventExporter, **kwargs: Any
) -> CrewAIEventListener:
    """Create and auto-register a CrewAI event listener."""

    return CrewAIEventListener(service_name, exporter, **kwargs)


def _event_id(event: Any) -> str:
    value = getattr(event, "event_id", None)
    return str(value) if value else f"crewai-event:{id(event)}"


def _timestamp(event: Any) -> datetime | None:
    value = getattr(event, "timestamp", None)
    return value if isinstance(value, datetime) else None


def _duration(start: datetime | None, end: datetime | None, monotonic: float) -> float:
    if start is not None and end is not None:
        return max(0.0, (end - start).total_seconds() * 1_000)
    return max(0.0, (time.monotonic() - monotonic) * 1_000)


def _text(value: Any, key: str, fallback: str) -> str:
    candidate = getattr(value, key, None)
    return candidate[:256] if isinstance(candidate, str) and candidate else fallback


def _optional_text(value: Any, key: str) -> str | None:
    candidate = getattr(value, key, None)
    return candidate[:256] if isinstance(candidate, str) and candidate else None


def _agent_name(event: Any) -> str:
    agent = getattr(event, "agent", None)
    role = _optional_text(agent, "role") or _optional_text(event, "agent_role")
    if role:
        return role
    info = getattr(event, "agent_info", None)
    if isinstance(info, dict):
        candidate = info.get("role") or info.get("name")
        if isinstance(candidate, str) and candidate:
            return candidate[:256]
    return "agent"


def _agent_attributes(event: Any) -> EventAttributes:
    result: EventAttributes = {"framework.name": "crewai"}
    agent_id = _optional_text(event, "agent_id")
    if agent_id is not None:
        result["gen_ai.agent.id"] = agent_id
    return result


def _task_name(event: Any) -> str:
    task = getattr(event, "task", None)
    return _optional_text(task, "name") or _optional_text(event, "task_name") or "task"


def _task_attributes(event: Any) -> EventAttributes:
    result: EventAttributes = {"framework.name": "crewai"}
    task_id = _optional_text(event, "task_id")
    if task_id is not None:
        result["causentra.task.id"] = task_id
    return result


def _tool_attributes(event: Any) -> EventAttributes:
    result: EventAttributes = {"framework.name": "crewai"}
    attempt = getattr(event, "run_attempts", None)
    if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt >= 0:
        result["tool.attempt"] = attempt
    return result


def _usage_attributes(usage: Any) -> EventAttributes:
    if not isinstance(usage, dict):
        return {}
    result: EventAttributes = {}
    for sources, target in (
        (("input_tokens", "prompt_tokens"), "gen_ai.usage.input_tokens"),
        (("output_tokens", "completion_tokens"), "gen_ai.usage.output_tokens"),
        (("total_tokens",), "gen_ai.usage.total_tokens"),
    ):
        value = next((usage[key] for key in sources if key in usage), None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[target] = value
    return result

"""Opt-in bounded aggregation for repeated, payload-free operation lifecycles."""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass

from .types import EventExporter, RuntimeEvent


@dataclass(frozen=True, slots=True)
class LoopAggregationPolicy:
    """Conservatively aggregate consecutive empty repeated operation pairs.

    The policy affects telemetry delivery only; it never changes application
    execution, return values, errors, or the runtime's instrumentation calls.
    First occurrences remain exact. Later matching pairs become one normal
    ``custom.loop.aggregated`` event at trace completion with a sequence range
    and repeat count for safe downstream replay/inspection.
    """

    threshold: int = 3
    max_groups_per_trace: int = 128
    families: frozenset[str] = frozenset({"agent", "model", "span", "tool"})

    def __post_init__(self) -> None:
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, int):
            raise ValueError("aggregation threshold must be an integer")
        if self.threshold < 2:
            raise ValueError("aggregation threshold must be at least 2")
        if (
            isinstance(self.max_groups_per_trace, bool)
            or not isinstance(self.max_groups_per_trace, int)
            or self.max_groups_per_trace <= 0
        ):
            raise ValueError("max_groups_per_trace must be a positive integer")
        if not self.families or any(
            value not in {"agent", "model", "span", "tool"} for value in self.families
        ):
            raise ValueError("families must be a non-empty subset of agent/model/span/tool")


@dataclass(slots=True)
class _AggregateGroup:
    source: RuntimeEvent
    count: int
    first_sequence: int
    last_sequence: int


class LoopAggregationExporter:
    """Wrap an exporter and compress safely recognizable repeated leaf pairs.

    Any payload-bearing, nested, interrupted, or non-consecutive lifecycle is
    passed through exactly. State is bounded per trace and released at trace
    completion or shutdown.
    """

    def __init__(self, exporter: EventExporter, policy: LoopAggregationPolicy) -> None:
        self._exporter = exporter
        self._policy = policy
        self._pending: dict[tuple[str, str], RuntimeEvent] = {}
        self._counts: dict[tuple[str, str | None, str, str], int] = {}
        self._groups: dict[tuple[str, str | None, str, str], _AggregateGroup] = {}
        self._group_counts: dict[str, int] = {}
        self._lock = threading.RLock()
        self._closed = False

    def emit(self, event: RuntimeEvent) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("loop aggregation exporter is closed")
            if event.type == "trace.end":
                self._flush_trace(event.trace_id)
                self._exporter.emit(event)
                return
            if _is_aggregate_start(event, self._policy):
                self._flush_pending_trace(event.trace_id)
                self._pending[(event.trace_id, event.span_id)] = event
                return
            pending = self._pending.get((event.trace_id, event.span_id))
            if pending is not None and _is_matching_end(pending, event):
                self._pending.pop((event.trace_id, event.span_id), None)
                self._complete_pair(pending, event)
                return
            self._flush_pending_trace(event.trace_id)
            self._exporter.emit(event)

    def flush(self, timeout: float | None = None) -> bool:
        return self._exporter.flush(timeout)

    def shutdown(self, timeout: float | None = None) -> None:
        with self._lock:
            if not self._closed:
                for trace_id in tuple(
                    set(self._group_counts) | {trace_id for trace_id, _span in self._pending}
                ):
                    self._flush_trace(trace_id)
                self._closed = True
        self._exporter.shutdown(timeout)

    def _complete_pair(self, start: RuntimeEvent, end: RuntimeEvent) -> None:
        family = start.type.removesuffix(".start")
        key = (start.trace_id, start.parent_span_id, family, start.name)
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        if count < self._policy.threshold:
            self._exporter.emit(start)
            self._exporter.emit(end)
            return
        group = self._groups.get(key)
        if group is None:
            group_count = self._group_counts.get(start.trace_id, 0)
            if group_count >= self._policy.max_groups_per_trace:
                self._exporter.emit(start)
                self._exporter.emit(end)
                return
            self._group_counts[start.trace_id] = group_count + 1
            self._groups[key] = _AggregateGroup(start, count, start.sequence, end.sequence)
            return
        group.count = count
        group.last_sequence = end.sequence

    def _flush_pending_trace(self, trace_id: str) -> None:
        pending = [
            (key, event)
            for key, event in self._pending.items()
            if key[0] == trace_id
        ]
        for key, event in sorted(pending, key=lambda item: item[1].sequence):
            self._pending.pop(key, None)
            self._exporter.emit(event)

    def _flush_trace(self, trace_id: str) -> None:
        self._flush_pending_trace(trace_id)
        groups = [
            (key, group) for key, group in self._groups.items() if key[0] == trace_id
        ]
        for key, group in sorted(groups, key=lambda item: item[1].first_sequence):
            self._groups.pop(key, None)
            self._exporter.emit(_aggregate_event(group))
        for key in tuple(self._counts):
            if key[0] == trace_id:
                self._counts.pop(key, None)
        self._group_counts.pop(trace_id, None)


def _is_aggregate_start(event: RuntimeEvent, policy: LoopAggregationPolicy) -> bool:
    family = event.type.removesuffix(".start")
    return event.type == f"{family}.start" and family in policy.families


def _is_matching_end(start: RuntimeEvent, end: RuntimeEvent) -> bool:
    return (
        end.type == f"{start.type.removesuffix('.start')}.end"
        and end.name == start.name
        and end.trace_id == start.trace_id
        and end.span_id == start.span_id
    )


def _aggregate_event(group: _AggregateGroup) -> RuntimeEvent:
    source = group.source
    family = source.type.removesuffix(".start")
    return RuntimeEvent(
        schema_version="1.0",
        event_id=secrets.token_hex(16),
        trace_id=source.trace_id,
        span_id=source.span_id,
        parent_span_id=source.parent_span_id,
        session_id=source.session_id,
        sequence=group.first_sequence,
        timestamp=source.timestamp,
        type="custom.loop.aggregated",
        name="loop aggregate",
        status="unset",
        service_name=source.service_name,
        attributes={
            "causentra.loop.family": family,
            "causentra.loop.operation": source.name,
            "causentra.loop.repeat_count": group.count,
            "causentra.loop.represented_event_count": group.count * 2,
            "causentra.loop.first_sequence": group.first_sequence,
            "causentra.loop.last_sequence": group.last_sequence,
        },
    )

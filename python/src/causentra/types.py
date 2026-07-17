"""Public wire and extension contracts shared by the Python runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeAlias, runtime_checkable

SCHEMA_VERSION: Literal["1.0"] = "1.0"

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
EventAttributes: TypeAlias = dict[str, JsonValue]
EventStatus: TypeAlias = Literal["unset", "ok", "error"]


@dataclass(frozen=True, slots=True)
class TraceContext:
    """Canonical correlation identifiers for the active operation."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """Versioned language-neutral event persisted and transported by Causentra."""

    schema_version: Literal["1.0"]
    event_id: str
    trace_id: str
    span_id: str
    sequence: int
    timestamp: str
    type: str
    name: str
    status: EventStatus
    service_name: str
    attributes: EventAttributes
    parent_span_id: str | None = None
    session_id: str | None = None
    duration_ms: float | None = None

    def to_wire(self) -> dict[str, Any]:
        """Return the exact camel-case JSON representation used by schema 1.0."""

        value: dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "eventId": self.event_id,
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "type": self.type,
            "name": self.name,
            "status": self.status,
            "serviceName": self.service_name,
            "attributes": self.attributes,
        }
        if self.parent_span_id is not None:
            value["parentSpanId"] = self.parent_span_id
        if self.session_id is not None:
            value["sessionId"] = self.session_id
        if self.duration_ms is not None:
            value["durationMs"] = self.duration_ms
        return value


@dataclass(frozen=True, slots=True)
class RuntimeErrorContext:
    """Contained instrumentation failure delivered to an application callback."""

    operation: Literal["export", "redact", "adapter"]
    error: BaseException
    dropped_events: int


@runtime_checkable
class EventExporter(Protocol):
    """Minimal synchronous exporter boundary used by runtime hot paths."""

    def emit(self, event: RuntimeEvent) -> None: ...

    def flush(self, timeout: float | None = None) -> bool: ...

    def shutdown(self, timeout: float | None = None) -> None: ...


Redactor: TypeAlias = Callable[[EventAttributes], EventAttributes]

"""Strict RuntimeEvent 1.0 validation with no third-party dependency."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from .types import RuntimeEvent

_HEX_32 = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID = re.compile(r"^(?:[0-9a-f]{16}|[0-9a-f]{32})$")
_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+$")
MAX_ATTRIBUTES_BYTES = 65_536
_REQUIRED_WIRE_FIELDS = frozenset(
    {
        "schemaVersion",
        "eventId",
        "traceId",
        "spanId",
        "sequence",
        "timestamp",
        "type",
        "name",
        "status",
        "serviceName",
        "attributes",
    }
)
_OPTIONAL_WIRE_FIELDS = frozenset({"parentSpanId", "sessionId", "durationMs"})


class EventValidationError(ValueError):
    """Raised when an event cannot cross the public wire boundary."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


def event_from_wire(value: Mapping[str, Any]) -> RuntimeEvent:
    """Parse the strict schema 1.0 JSON representation without coercion."""

    fields = set(value)
    missing = _REQUIRED_WIRE_FIELDS - fields
    if missing:
        raise EventValidationError(sorted(missing)[0], "is required")
    unknown = fields - _REQUIRED_WIRE_FIELDS - _OPTIONAL_WIRE_FIELDS
    if unknown:
        raise EventValidationError(sorted(unknown)[0], "is not supported by schema 1.0")
    for field in (
        "schemaVersion",
        "eventId",
        "traceId",
        "spanId",
        "timestamp",
        "type",
        "name",
        "status",
        "serviceName",
    ):
        if not isinstance(value[field], str):
            raise EventValidationError(field, "must be a string")
    for field in ("parentSpanId", "sessionId"):
        if field in value and not isinstance(value[field], str):
            raise EventValidationError(field, "must be a string")
    sequence = value["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise EventValidationError("sequence", "must be an integer")
    duration = value.get("durationMs")
    if duration is not None and (
        isinstance(duration, bool) or not isinstance(duration, int | float)
    ):
        raise EventValidationError("durationMs", "must be a number")
    attributes = value["attributes"]
    if not isinstance(attributes, dict):
        raise EventValidationError("attributes", "must be an object")
    event = RuntimeEvent(
        schema_version=cast(Any, value["schemaVersion"]),
        event_id=cast(str, value["eventId"]),
        trace_id=cast(str, value["traceId"]),
        span_id=cast(str, value["spanId"]),
        parent_span_id=cast(str | None, value.get("parentSpanId")),
        session_id=cast(str | None, value.get("sessionId")),
        sequence=sequence,
        timestamp=cast(str, value["timestamp"]),
        type=cast(str, value["type"]),
        name=cast(str, value["name"]),
        status=cast(Any, value["status"]),
        duration_ms=None if duration is None else float(duration),
        service_name=cast(str, value["serviceName"]),
        attributes=cast(dict[str, Any], attributes),
    )
    validate_event(event)
    return event


def validate_event(event: RuntimeEvent) -> None:
    """Validate one immutable runtime event or raise a field-specific error."""

    if event.schema_version != "1.0":
        raise EventValidationError("schemaVersion", "must equal 1.0")
    _identifier(event.event_id, _HEX_32, "eventId")
    _identifier(event.trace_id, _HEX_32, "traceId")
    _identifier(event.span_id, _SPAN_ID, "spanId")
    if event.parent_span_id is not None:
        _identifier(event.parent_span_id, _SPAN_ID, "parentSpanId")
    if event.session_id is not None:
        _identifier(event.session_id, _HEX_32, "sessionId")
    if event.sequence < 0:
        raise EventValidationError("sequence", "must be non-negative")
    try:
        datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise EventValidationError("timestamp", "must be ISO-8601") from error
    if not _EVENT_TYPE.fullmatch(event.type) or len(event.type) > 128:
        raise EventValidationError("type", "must be a dot-namespaced lifecycle type")
    _bounded_text(event.name, "name", 256)
    _bounded_text(event.service_name, "serviceName", 256)
    if event.status not in ("unset", "ok", "error"):
        raise EventValidationError("status", "is unsupported")
    if event.duration_ms is not None and (
        not math.isfinite(event.duration_ms) or event.duration_ms < 0
    ):
        raise EventValidationError("durationMs", "must be finite and non-negative")
    validate_attributes(event.attributes)


def validate_attributes(attributes: dict[str, Any]) -> None:
    """Validate JSON compatibility, key bounds, numeric safety, and byte size."""

    if not isinstance(attributes, dict):
        raise EventValidationError("attributes", "must be an object")
    _json_value(attributes, "attributes", 0)
    try:
        encoded = json.dumps(attributes, separators=(",", ":"), ensure_ascii=False).encode()
    except (TypeError, ValueError) as error:
        raise EventValidationError("attributes", "must be JSON-compatible") from error
    if len(encoded) > MAX_ATTRIBUTES_BYTES:
        raise EventValidationError("attributes", "exceeds 64 KiB")


def _json_value(value: Any, field: str, depth: int) -> None:
    if depth > 16:
        raise EventValidationError(field, "exceeds maximum nesting depth")
    if value is None or isinstance(value, str | bool):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > 9_007_199_254_740_991:
            raise EventValidationError(field, "integer exceeds interoperable safe range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EventValidationError(field, "number must be finite")
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item, field, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 256:
                raise EventValidationError(field, "keys must be non-empty strings up to 256 chars")
            _json_value(item, field, depth + 1)
        return
    raise EventValidationError(field, f"unsupported value type {type(value).__name__}")


def _identifier(value: str, pattern: re.Pattern[str], field: str) -> None:
    if not pattern.fullmatch(value):
        raise EventValidationError(field, "has invalid canonical format")


def _bounded_text(value: str, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise EventValidationError(field, f"must be non-empty and at most {maximum} chars")

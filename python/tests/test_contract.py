from __future__ import annotations

import json
from pathlib import Path

import pytest

from causentra.types import RuntimeEvent
from causentra.validation import EventValidationError, event_from_wire, validate_event

FIXTURES = Path(__file__).parents[2] / "packages" / "sdk" / "fixtures" / "v1"


def _event(value: dict[str, object]) -> RuntimeEvent:
    return RuntimeEvent(
        schema_version=value["schemaVersion"],  # type: ignore[arg-type]
        event_id=value["eventId"],  # type: ignore[arg-type]
        trace_id=value["traceId"],  # type: ignore[arg-type]
        span_id=value["spanId"],  # type: ignore[arg-type]
        parent_span_id=value.get("parentSpanId"),  # type: ignore[arg-type]
        session_id=value.get("sessionId"),  # type: ignore[arg-type]
        sequence=value["sequence"],  # type: ignore[arg-type]
        timestamp=value["timestamp"],  # type: ignore[arg-type]
        type=value["type"],  # type: ignore[arg-type]
        name=value["name"],  # type: ignore[arg-type]
        status=value["status"],  # type: ignore[arg-type]
        duration_ms=value.get("durationMs"),  # type: ignore[arg-type]
        service_name=value["serviceName"],  # type: ignore[arg-type]
        attributes=value["attributes"],  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("path", sorted((FIXTURES / "valid").glob("*.json")))
def test_typescript_wire_fixtures_are_valid_in_python(path: Path) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    event = _event(value)
    validate_event(event)
    assert event.to_wire() == value


@pytest.mark.parametrize("path", sorted((FIXTURES / "invalid").glob("*.json")))
def test_typescript_invalid_fixtures_are_rejected_in_python(path: Path) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    with pytest.raises(EventValidationError):
        validate_event(_event(value["event"]))


def test_wire_parser_rejects_coercion_and_unknown_fields() -> None:
    path = next(iter(sorted((FIXTURES / "valid").glob("*.json"))))
    value = json.loads(path.read_text(encoding="utf-8"))
    assert event_from_wire(value).to_wire() == value
    value["sequence"] = True
    with pytest.raises(EventValidationError, match="sequence"):
        event_from_wire(value)
    value["sequence"] = 0
    value["unexpected"] = "field"
    with pytest.raises(EventValidationError, match="unexpected"):
        event_from_wire(value)

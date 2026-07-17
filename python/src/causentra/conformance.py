"""Small adapter conformance checks usable by community integrations."""

from __future__ import annotations

from collections.abc import Iterable

from .types import RuntimeEvent
from .validation import validate_event


def adapter_conformance_errors(events: Iterable[RuntimeEvent]) -> tuple[str, ...]:
    """Return lifecycle, privacy, ordering, and schema defects."""

    values = list(events)
    errors: list[str] = []
    if not values:
        return ("adapter emitted no events",)
    for event in values:
        try:
            validate_event(event)
        except ValueError as error:
            errors.append(str(error))
    by_trace: dict[str, list[RuntimeEvent]] = {}
    for event in values:
        by_trace.setdefault(event.trace_id, []).append(event)
        if _contains_unredacted_secret(event.attributes):
            errors.append(f"{event.event_id}: sensitive attribute value survived redaction")
    for trace_id, trace_events in by_trace.items():
        sequences = [event.sequence for event in trace_events]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            errors.append(f"{trace_id}: sequences are not unique and monotonic")
        types = {event.type for event in trace_events}
        if "trace.start" not in types or "trace.end" not in types:
            errors.append(f"{trace_id}: missing trace lifecycle boundary")
    return tuple(errors)


def assert_adapter_conformant(events: Iterable[RuntimeEvent]) -> None:
    errors = adapter_conformance_errors(events)
    if errors:
        raise AssertionError("; ".join(errors))


def _contains_unredacted_secret(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.lower().replace("-", "_").replace(".", "_")
            safe_token_count = (
                normalized.startswith("gen_ai_usage_")
                and normalized.endswith(("_tokens", "_token_count"))
                and isinstance(item, int | float)
                and not isinstance(item, bool)
                and item >= 0
            )
            sensitive = not safe_token_count and any(
                marker in normalized
                for marker in (
                    "authorization",
                    "api_key",
                    "password",
                    "secret",
                    "access_token",
                    "refresh_token",
                    "bearer_token",
                    "session_token",
                    "id_token",
                )
            )
            if sensitive and item != "[REDACTED]":
                return True
            if _contains_unredacted_secret(item):
                return True
    elif isinstance(value, list):
        return any(_contains_unredacted_secret(item) for item in value)
    return False

"""Deterministic, offline evaluation over privacy-safe RuntimeEvent bundles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .types import EventAttributes, RuntimeEvent
from .validation import event_from_wire


@dataclass(frozen=True, slots=True)
class EvaluationRule:
    """A simple reproducible trace assertion with no model or network dependency."""

    rule_id: str
    required_event_types: frozenset[str] = frozenset()
    maximum_error_events: int | None = None
    maximum_duration_ms: float | None = None
    minimum_event_count: int | None = None

    def __post_init__(self) -> None:
        if not self.rule_id or len(self.rule_id) > 128:
            raise ValueError("rule_id must be non-empty and at most 128 characters")
        if any(not value or len(value) > 128 for value in self.required_event_types):
            raise ValueError("required_event_types must contain bounded non-empty strings")
        for name in ("maximum_error_events", "minimum_event_count"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer")
        if self.maximum_duration_ms is not None and (
            isinstance(self.maximum_duration_ms, bool)
            or not isinstance(self.maximum_duration_ms, int | float)
            or self.maximum_duration_ms < 0
        ):
            raise ValueError("maximum_duration_ms must be a non-negative number")


@dataclass(frozen=True, slots=True)
class EvaluationFinding:
    rule_id: str
    passed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class TraceEvaluation:
    """Stable score and findings tied to the exact evaluated trace identity."""

    trace_id: str
    rule_set_id: str
    score: float
    findings: tuple[EvaluationFinding, ...]
    evaluated_event_ids: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return all(finding.passed for finding in self.findings)

    def score_attributes(self) -> EventAttributes:
        """Return safe attributes for a caller-created ``evaluation.score`` event."""

        return {
            "causentra.evaluation.rule_set_id": self.rule_set_id,
            "causentra.evaluation.score": self.score,
            "causentra.evaluation.passed": self.passed,
            "causentra.evaluation.event_count": len(self.evaluated_event_ids),
            "causentra.evaluation.failed_rule_ids": [
                finding.rule_id for finding in self.findings if not finding.passed
            ],
        }


def evaluate_trace(
    events: Iterable[RuntimeEvent],
    rules: Sequence[EvaluationRule],
    *,
    rule_set_id: str,
) -> TraceEvaluation:
    """Evaluate one trace deterministically using explicit rules only.

    Rule order does not affect scoring or generated attributes. Callers should
    store the returned ``score_attributes`` through ``runtime.record`` with
    ``event_type='evaluation.score'`` when they want the result in telemetry.
    """

    if not rule_set_id or len(rule_set_id) > 128:
        raise ValueError("rule_set_id must be non-empty and at most 128 characters")
    values = tuple(events)
    if not values:
        raise ValueError("an evaluation requires at least one event")
    trace_ids = {event.trace_id for event in values}
    if len(trace_ids) != 1:
        raise ValueError("an evaluation bundle must contain exactly one trace ID")
    if len({rule.rule_id for rule in rules}) != len(rules):
        raise ValueError("evaluation rule IDs must be unique")
    ordered_rules = tuple(sorted(rules, key=lambda rule: rule.rule_id))
    event_types = {event.type for event in values}
    error_count = sum(event.status == "error" for event in values)
    duration = sum(event.duration_ms or 0.0 for event in values)
    findings: list[EvaluationFinding] = []
    for rule in ordered_rules:
        failures: list[str] = []
        missing = sorted(rule.required_event_types - event_types)
        if missing:
            failures.append(f"missing event types: {','.join(missing)}")
        if rule.maximum_error_events is not None and error_count > rule.maximum_error_events:
            failures.append("error event limit exceeded")
        if rule.maximum_duration_ms is not None and duration > rule.maximum_duration_ms:
            failures.append("duration limit exceeded")
        if rule.minimum_event_count is not None and len(values) < rule.minimum_event_count:
            failures.append("minimum event count not reached")
        findings.append(
            EvaluationFinding(
                rule.rule_id,
                not failures,
                "ok" if not failures else "; ".join(failures),
            )
        )
    score = 1.0 if not findings else sum(finding.passed for finding in findings) / len(findings)
    return TraceEvaluation(
        trace_id=next(iter(trace_ids)),
        rule_set_id=rule_set_id,
        score=score,
        findings=tuple(findings),
        evaluated_event_ids=tuple(sorted(event.event_id for event in values)),
    )


def evaluate_trace_bundle(
    bundle: Mapping[str, Any], rules: Sequence[EvaluationRule], *, rule_set_id: str
) -> TraceEvaluation:
    """Parse an exported ``{traceId, events}`` bundle and evaluate it offline."""

    if type(bundle) is not dict or set(bundle) != {"traceId", "events"}:
        raise ValueError("trace bundle must contain only traceId and events")
    if not isinstance(bundle["traceId"], str) or not isinstance(bundle["events"], list):
        raise ValueError("trace bundle has invalid fields")
    if not all(isinstance(event, dict) for event in bundle["events"]):
        raise ValueError("trace bundle events must be objects")
    result = evaluate_trace(
        (event_from_wire(event) for event in bundle["events"]),
        rules,
        rule_set_id=rule_set_id,
    )
    if result.trace_id != bundle["traceId"]:
        raise ValueError("trace bundle traceId does not match its events")
    return result


def evaluation_id(evaluation: TraceEvaluation) -> str:
    """Return a deterministic identifier for deduplicating an evaluation result."""

    value = {
        "traceId": evaluation.trace_id,
        "ruleSetId": evaluation.rule_set_id,
        "score": evaluation.score,
        "findings": [
            {"ruleId": finding.rule_id, "passed": finding.passed, "reason": finding.reason}
            for finding in evaluation.findings
        ],
        "eventIds": list(evaluation.evaluated_event_ids),
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:32]

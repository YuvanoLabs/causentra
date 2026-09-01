from __future__ import annotations

from datetime import date

import pytest

from causentra import (
    CausentraRuntime,
    EvaluationRule,
    MemoryExporter,
    ModelPriceRate,
    PriceCatalog,
    RuntimeEvent,
    evaluate_trace,
    evaluate_trace_bundle,
    evaluation_id,
)


def _events() -> tuple[RuntimeEvent, ...]:
    exporter = MemoryExporter()
    runtime = CausentraRuntime("evaluation-test", exporter)
    with runtime.trace("workflow"), runtime.tool("lookup"):
        pass
    return exporter.events


def test_offline_evaluation_is_repeatable_and_privacy_safe() -> None:
    events = _events()
    rules = (
        EvaluationRule("must-call-tool", required_event_types=frozenset({"tool.start"})),
        EvaluationRule("no-errors", maximum_error_events=0, minimum_event_count=4),
    )
    first = evaluate_trace(events, rules, rule_set_id="release-smoke-v1")
    second = evaluate_trace(
        tuple(reversed(events)), tuple(reversed(rules)), rule_set_id="release-smoke-v1"
    )
    assert first == second
    assert first.score == 1.0
    assert evaluation_id(first) == evaluation_id(second)
    attributes = first.score_attributes()
    assert attributes["causentra.evaluation.passed"] is True
    assert "workflow" not in str(attributes)


def test_trace_bundle_evaluation_rejects_mismatched_or_invalid_bundle() -> None:
    events = _events()
    bundle = {
        "traceId": events[0].trace_id,
        "events": [event.to_wire() for event in events],
    }
    result = evaluate_trace_bundle(bundle, (), rule_set_id="empty-rules")
    assert result.score == 1.0
    invalid = {**bundle, "traceId": "0" * 32}
    with pytest.raises(ValueError, match="does not match"):
        evaluate_trace_bundle(invalid, (), rule_set_id="empty-rules")
    malformed = {**bundle, "events": [*bundle["events"], "not-an-event"]}
    with pytest.raises(ValueError, match="must be objects"):
        evaluate_trace_bundle(malformed, (), rule_set_id="empty-rules")
    with pytest.raises(ValueError, match="exactly one trace ID"):
        evaluate_trace((events[0], _events()[0]), (), rule_set_id="x")


def test_versioned_price_catalog_is_explicit_effective_dated_and_never_guesses() -> None:
    catalog = PriceCatalog(
        "catalog-2026-08",
        (
            ModelPriceRate(
                "openai", "gpt-example", date(2026, 1, 1), 1_000_000, 2_000_000
            ),
            ModelPriceRate(
                "openai", "gpt-example", date(2026, 8, 1), 3_000_000, 4_000_000
            ),
        ),
    )
    january = catalog.estimate(
        provider_name="OpenAI",
        model="gpt-example",
        input_tokens=1_000_000,
        output_tokens=2_000_000,
        on=date(2026, 7, 31),
    )
    assert january is not None and january.cost_usd == 5.0
    august = catalog.estimate(
        provider_name="openai",
        model="gpt-example",
        input_tokens=1_000_000,
        output_tokens=2_000_000,
        on=date(2026, 8, 1),
    )
    assert august is not None and august.cost_usd == 11.0
    assert august.attributes() == {
        "causentra.cost.usd": 11.0,
        "causentra.cost.basis": "catalog_estimate",
        "causentra.cost.catalog.version": "catalog-2026-08",
        "causentra.cost.catalog.effective_from": "2026-08-01",
    }
    assert (
        catalog.estimate(provider_name="openai", model="unknown", on=date(2026, 8, 1))
        is None
    )
    assert catalog.estimate(
        provider_name="openai", model="gpt-example", cache_read_input_tokens=1, on=date(2026, 8, 1)
    ) is None

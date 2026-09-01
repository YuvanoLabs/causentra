from __future__ import annotations

from causentra import (
    CausentraRuntime,
    LoopAggregationExporter,
    LoopAggregationPolicy,
    MemoryExporter,
)


def test_loop_aggregation_bounds_repeated_leaf_lifecycles_and_preserves_summary() -> None:
    memory = MemoryExporter()
    runtime = CausentraRuntime(
        "aggregation-test",
        LoopAggregationExporter(memory, LoopAggregationPolicy(threshold=3)),
    )
    with runtime.trace("workflow"):
        for _ in range(5):
            with runtime.tool("repeat"):
                pass
    events = memory.events
    starts = [event for event in events if event.type == "tool.start"]
    ends = [event for event in events if event.type == "tool.end"]
    aggregate = next(event for event in events if event.type == "custom.loop.aggregated")
    assert len(starts) == len(ends) == 2
    assert aggregate.attributes == {
        "causentra.loop.family": "tool",
        "causentra.loop.operation": "repeat",
        "causentra.loop.repeat_count": 5,
        "causentra.loop.represented_event_count": 10,
        "causentra.loop.first_sequence": 5,
        "causentra.loop.last_sequence": 10,
    }
    assert events[-1].type == "trace.end"
    assert len(events) == 7


def test_loop_aggregation_preserves_payload_bearing_or_nested_operations_exactly() -> None:
    memory = MemoryExporter()
    runtime = CausentraRuntime(
        "aggregation-test",
        LoopAggregationExporter(memory, LoopAggregationPolicy(threshold=2)),
    )
    with runtime.trace("workflow"):
        for _ in range(3):
            with runtime.tool("repeat"):
                runtime.record("detail", attributes={"safe": True})
    events = memory.events
    assert len([event for event in events if event.type == "tool.start"]) == 3
    assert len([event for event in events if event.type == "tool.end"]) == 3
    assert len([event for event in events if event.type == "custom.event"]) == 3
    assert not [event for event in events if event.type == "custom.loop.aggregated"]


def test_loop_aggregation_rejects_invalid_bounds() -> None:
    for kwargs in ({"threshold": 1}, {"max_groups_per_trace": 0}, {"families": frozenset()}):
        try:
            LoopAggregationPolicy(**kwargs)
        except ValueError:
            continue
        raise AssertionError("invalid aggregation policy was accepted")

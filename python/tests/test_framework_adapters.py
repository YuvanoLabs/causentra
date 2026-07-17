from __future__ import annotations

from types import SimpleNamespace

from causentra import MemoryExporter, assert_adapter_conformant
from causentra.adapters.langgraph import LangGraphCallbackHandler
from causentra.adapters.openai_agents import OpenAIAgentsTracingProcessor


def test_openai_agents_processor_maps_handoff_without_payload_capture() -> None:
    exporter = MemoryExporter()
    processor = OpenAIAgentsTracingProcessor("openai-app", exporter)
    trace = SimpleNamespace(trace_id="trace-1", group_id="session-1", name="workflow")
    data = SimpleNamespace(
        type="handoff",
        from_agent=SimpleNamespace(name="triage"),
        to_agent=SimpleNamespace(name="specialist"),
        input="must never be captured",
    )
    span = SimpleNamespace(
        trace_id="trace-1",
        span_id="span-1",
        parent_id=None,
        started_at="2026-07-16T10:00:00Z",
        ended_at="2026-07-16T10:00:00.025Z",
        error=None,
        span_data=data,
    )
    processor.on_trace_start(trace)
    processor.on_span_start(span)
    processor.on_span_end(span)
    processor.on_trace_end(trace)
    assert_adapter_conformant(exporter.events)
    start = exporter.events[1]
    assert start.type == "agent.handoff.start"
    assert start.attributes["causentra.agent.from.name"] == "triage"
    assert "input" not in start.attributes


def test_langgraph_callback_maps_nested_run_without_inputs_or_outputs() -> None:
    exporter = MemoryExporter()
    handler = LangGraphCallbackHandler("graph-app", exporter, include_metadata=True)
    handler.on_chain_start(
        {"id": ["langgraph", "CheckoutGraph"]},
        {"customer": "private"},
        run_id="root-run",
        tags=["production"],
        metadata={"tenant": "private"},
    )
    handler.on_tool_start(
        {"name": "inventory"},
        "private query",
        run_id="tool-run",
        parent_run_id="root-run",
    )
    handler.on_tool_end("private output", run_id="tool-run")
    handler.on_chain_end({"answer": "private"}, run_id="root-run")
    assert_adapter_conformant(exporter.events)
    assert [event.type for event in exporter.events] == [
        "trace.start",
        "agent.start",
        "tool.start",
        "tool.end",
        "agent.end",
        "trace.end",
    ]
    serialized = str([event.attributes for event in exporter.events])
    assert "private" not in serialized
    assert exporter.events[1].attributes["framework.metadata.keys"] == ["tenant"]

from __future__ import annotations

from causentra import AdapterEventBridge, MemoryExporter, assert_adapter_conformant


def test_bridge_normalizes_external_ids_and_is_conformant() -> None:
    exporter = MemoryExporter()
    bridge = AdapterEventBridge("framework", exporter)
    common = {"external_trace_id": "framework-trace", "external_span_id": "root"}
    assert bridge.emit(**common, event_type="trace.start", name="run")
    assert bridge.emit(
        external_trace_id="framework-trace",
        external_span_id="child",
        external_parent_span_id="root",
        event_type="agent.start",
        name="agent",
        attributes={"authorization": "Bearer value"},
    )
    assert bridge.emit(
        external_trace_id="framework-trace",
        external_span_id="child",
        external_parent_span_id="root",
        event_type="agent.end",
        name="agent",
        status="ok",
    )
    assert bridge.emit(**common, event_type="trace.end", name="run", status="ok")
    assert_adapter_conformant(exporter.events)
    assert exporter.events[1].attributes["authorization"] == "[REDACTED]"

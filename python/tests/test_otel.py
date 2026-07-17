from __future__ import annotations

import pytest

from causentra import CausentraRuntime
from causentra.otel import OpenTelemetryEventExporter


def test_projects_nested_runtime_lifecycles_to_real_otel_spans() -> None:
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    exporter = OpenTelemetryEventExporter(
        provider.get_tracer("test"),
        force_flush=provider.force_flush,
        shutdown_provider=provider.shutdown,
    )
    runtime = CausentraRuntime("otel-app", exporter)
    with (
        runtime.trace("workflow"),
        runtime.agent("planner"),
        runtime.tool("search"),
    ):
        pass
    runtime.shutdown()
    spans = memory.get_finished_spans()
    assert {span.name for span in spans} == {"workflow", "planner", "search"}
    search = next(span for span in spans if span.name == "search")
    planner = next(span for span in spans if span.name == "planner")
    assert search.parent and search.parent.span_id == planner.context.span_id
    assert search.attributes["causentra.event.type"] == "tool.start"

from __future__ import annotations

import pytest

from causentra import MemoryExporter, assert_adapter_conformant


def test_real_openai_agents_trace_processor_contract() -> None:
    agents = pytest.importorskip("agents")
    from causentra.adapters.openai_agents import OpenAIAgentsTracingProcessor

    exporter = MemoryExporter()
    processor = OpenAIAgentsTracingProcessor("openai-real", exporter)
    agents.set_trace_processors([processor])
    try:
        with (
            agents.trace("real-workflow", group_id="real-session"),
            agents.custom_span("real-operation", data={"private": "not captured"}),
        ):
            pass
        processor.force_flush()
    finally:
        agents.set_trace_processors([])
    assert_adapter_conformant(exporter.events)
    assert [event.type for event in exporter.events] == [
        "trace.start",
        "span.start",
        "span.end",
        "trace.end",
    ]
    assert "private" not in str([event.attributes for event in exporter.events])


def test_real_langgraph_compiled_graph_callback_contract() -> None:
    pytest.importorskip("langgraph")
    from langgraph.graph import END, START, StateGraph

    from causentra.adapters.langgraph import LangGraphCallbackHandler

    exporter = MemoryExporter()
    handler = LangGraphCallbackHandler("langgraph-real", exporter)
    builder = StateGraph(dict)
    builder.add_node("work", lambda state: {**state, "done": True})
    builder.add_edge(START, "work")
    builder.add_edge("work", END)
    graph = builder.compile(name="real-graph")
    result = graph.invoke({}, config={"callbacks": [handler]})
    assert result == {"done": True}
    assert_adapter_conformant(exporter.events)
    assert {event.type for event in exporter.events} >= {
        "trace.start",
        "agent.start",
        "agent.end",
        "trace.end",
    }


def test_real_crewai_event_bus_accepts_listener() -> None:
    crewai_events = pytest.importorskip("crewai.events")
    from causentra.adapters.crewai import CrewAIEventListener

    listener = CrewAIEventListener("crewai-real", MemoryExporter())
    try:
        assert isinstance(listener, crewai_events.BaseEventListener)
        assert len(listener._registrations) == 18
    finally:
        listener.shutdown()


def test_real_google_adk_runner_accepts_plugin() -> None:
    pytest.importorskip("google.adk")
    from google.adk import Runner
    from google.adk.agents import Agent
    from google.adk.apps import App
    from google.adk.plugins import BasePlugin
    from google.adk.sessions import InMemorySessionService

    from causentra.adapters.google_adk import GoogleADKPlugin

    plugin = GoogleADKPlugin("adk-real", MemoryExporter())
    app = App(
        name="adapter-test",
        root_agent=Agent(name="coordinator"),
        plugins=[plugin],
    )
    runner = Runner(
        app=app,
        session_service=InMemorySessionService(),
    )
    assert isinstance(plugin, BasePlugin)
    assert runner is not None


def test_real_semantic_kernel_accepts_function_filter() -> None:
    semantic_kernel = pytest.importorskip("semantic_kernel")
    from causentra.adapters.semantic_kernel import SemanticKernelFilterAdapter

    kernel = semantic_kernel.Kernel()
    adapter = SemanticKernelFilterAdapter("semantic-kernel-real", MemoryExporter())
    assert adapter.install(kernel) is adapter
    assert len(kernel.function_invocation_filters) == 1
    assert kernel.function_invocation_filters[0][1] == adapter.function_invocation_filter


def test_real_autogen_runtime_accepts_tracer_provider() -> None:
    autogen_core = pytest.importorskip("autogen_core")
    from causentra.adapters.autogen import create_autogen_tracer_provider

    provider = create_autogen_tracer_provider(
        "autogen-real", MemoryExporter(), batch=False
    )
    runtime = autogen_core.SingleThreadedAgentRuntime(tracer_provider=provider)
    assert runtime is not None
    provider.shutdown()

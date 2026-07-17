from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from causentra import MemoryExporter, assert_adapter_conformant
from causentra.adapters.autogen import AutoGenSpanExporter
from causentra.adapters.crewai import CrewAIEventListener
from causentra.adapters.google_adk import GoogleADKPlugin
from causentra.adapters.semantic_kernel import SemanticKernelFilterAdapter


def test_crewai_listener_maps_nested_lifecycles_without_payloads() -> None:
    exporter = MemoryExporter()
    listener = CrewAIEventListener("crew-app", exporter)
    now = datetime.now(timezone.utc)
    listener._on_crew_started(
        None,
        SimpleNamespace(event_id="crew-1", timestamp=now, crew_name="research-crew"),
    )
    listener._on_agent_started(
        None,
        SimpleNamespace(
            event_id="agent-1",
            parent_event_id="crew-1",
            timestamp=now + timedelta(milliseconds=1),
            agent=SimpleNamespace(role="researcher", goal="private prompt"),
            task_prompt="private prompt",
        ),
    )
    listener._on_model_started(
        None,
        SimpleNamespace(
            event_id="model-1",
            parent_event_id="agent-1",
            timestamp=now + timedelta(milliseconds=2),
            model="gpt-test",
            messages="private prompt",
        ),
    )
    listener._on_model_completed(
        None,
        SimpleNamespace(
            event_id="model-end",
            started_event_id="model-1",
            timestamp=now + timedelta(milliseconds=5),
            response="private response",
            usage={"prompt_tokens": 2, "completion_tokens": 3},
        ),
    )
    listener._on_agent_completed(
        None,
        SimpleNamespace(
            event_id="agent-end",
            started_event_id="agent-1",
            timestamp=now + timedelta(milliseconds=6),
            output="private response",
        ),
    )
    listener._on_crew_completed(
        None,
        SimpleNamespace(
            event_id="crew-end",
            started_event_id="crew-1",
            timestamp=now + timedelta(milliseconds=7),
            total_tokens=5,
            output="private response",
        ),
    )
    assert [event.type for event in exporter.events] == [
        "trace.start",
        "agent.start",
        "model.start",
        "model.end",
        "agent.end",
        "trace.end",
    ]
    assert_adapter_conformant(exporter.events)
    assert "private" not in str([event.attributes for event in exporter.events])
    listener.shutdown()


async def _google_adk_scenario() -> None:
    exporter = MemoryExporter()
    plugin = GoogleADKPlugin("adk-app", exporter)
    session = SimpleNamespace(id="session-1")
    invocation = SimpleNamespace(
        invocation_id="invocation-1",
        session=session,
        agent=SimpleNamespace(name="coordinator"),
    )
    context = SimpleNamespace(
        invocation_id="invocation-1",
        session=session,
        node_path="coordinator",
        function_call_id=None,
    )
    assert await plugin.before_run_callback(invocation_context=invocation) is None
    assert (
        await plugin.before_agent_callback(
            agent=SimpleNamespace(name="coordinator"), callback_context=context
        )
        is None
    )
    request = SimpleNamespace(model="gemini-test", contents=["private prompt"])
    assert (
        await plugin.before_model_callback(callback_context=context, llm_request=request) is None
    )
    response = SimpleNamespace(
        model_version="gemini-test-1",
        content="private response",
        usage_metadata=SimpleNamespace(
            prompt_token_count=4,
            candidates_token_count=6,
            total_token_count=10,
        ),
        finish_reason="STOP",
    )
    assert (
        await plugin.after_model_callback(callback_context=context, llm_response=response) is None
    )
    context.function_call_id = "call-1"
    tool = SimpleNamespace(name="inventory")
    assert (
        await plugin.before_tool_callback(
            tool=tool, tool_args={"secret": "private"}, tool_context=context
        )
        is None
    )
    assert (
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={"secret": "private"},
            tool_context=context,
            result={"private": "result"},
        )
        is None
    )
    assert (
        await plugin.after_agent_callback(
            agent=SimpleNamespace(name="coordinator"), callback_context=context
        )
        is None
    )
    assert await plugin.after_run_callback(invocation_context=invocation) is None
    assert_adapter_conformant(exporter.events)
    assert [event.type for event in exporter.events] == [
        "trace.start",
        "agent.start",
        "model.start",
        "model.end",
        "tool.start",
        "tool.end",
        "agent.end",
        "trace.end",
    ]
    assert "private" not in str([event.attributes for event in exporter.events])


def test_google_adk_plugin_observes_callbacks_without_modifying_values() -> None:
    asyncio.run(_google_adk_scenario())


async def _semantic_kernel_scenario() -> None:
    exporter = MemoryExporter()
    adapter = SemanticKernelFilterAdapter("sk-app", exporter)
    context = SimpleNamespace(
        function=SimpleNamespace(
            name="lookup", plugin_name="inventory", is_prompt=False, prompt="private"
        ),
        arguments={"secret": "private"},
        result=None,
        is_streaming=False,
    )
    calls = 0

    async def invoke(value: Any) -> None:
        nonlocal calls
        calls += 1
        value.result = {"private": "output"}

    await adapter.function_invocation_filter(context, invoke)
    assert calls == 1
    assert_adapter_conformant(exporter.events)
    assert [event.type for event in exporter.events] == [
        "trace.start",
        "tool.start",
        "tool.end",
        "trace.end",
    ]
    assert "private" not in str([event.attributes for event in exporter.events])


def test_semantic_kernel_filter_delegates_once_and_excludes_payloads() -> None:
    asyncio.run(_semantic_kernel_scenario())


def test_autogen_otel_exporter_whitelists_attributes_and_correlates_parent() -> None:
    exporter = MemoryExporter()
    adapter = AutoGenSpanExporter("autogen-app", exporter)
    start = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)
    span = SimpleNamespace(
        context=SimpleNamespace(trace_id=0x1234, span_id=0x5678),
        parent=None,
        start_time=start,
        end_time=start + 4_000_000,
        name="invoke_agent coordinator",
        status=SimpleNamespace(status_code=SimpleNamespace(name="OK")),
        instrumentation_scope=SimpleNamespace(name="autogen-core"),
        attributes={
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.system": "autogen",
            "gen_ai.agent.name": "coordinator",
            "gen_ai.agent.description": "private instructions",
            "gen_ai.prompt": "private prompt",
        },
        events=[SimpleNamespace(name="private exception", attributes={})],
    )
    adapter.export([span])
    assert_adapter_conformant(exporter.events)
    assert [event.type for event in exporter.events] == [
        "trace.start",
        "agent.start",
        "agent.end",
        "trace.end",
    ]
    assert "private" not in str([event.attributes for event in exporter.events])

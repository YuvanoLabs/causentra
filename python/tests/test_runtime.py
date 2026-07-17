from __future__ import annotations

import asyncio

import pytest

from causentra import CausentraRuntime, MemoryExporter


def test_nested_lifecycle_privacy_relationships_and_models() -> None:
    exporter = MemoryExporter()
    runtime = CausentraRuntime("checkout-agents", exporter, session_id="a" * 32)

    with runtime.trace("checkout") as root:
        with runtime.agent("planner"):
            with runtime.model(
                "reason", provider_name="xai", request_model="grok-4", input_tokens=12
            ):
                runtime.record("decision", attributes={"api_key": "secret", "safe": True})
            with runtime.handoff("planner", "buyer", relationship_id="h-1"):
                pass
        carrier = runtime.inject_trace_context()

    events = exporter.events
    assert [event.sequence for event in events] == list(range(len(events)))
    assert {event.trace_id for event in events} == {root.trace_id}
    assert carrier and carrier["traceparent"].startswith(f"00-{root.trace_id}-")
    assert (
        next(event for event in events if event.type == "custom.event").attributes["api_key"]
        == "[REDACTED]"
    )
    model = next(event for event in events if event.type == "model.start")
    assert model.attributes["gen_ai.provider.name"] == "x_ai"
    assert model.attributes["gen_ai.usage.input_tokens"] == 12
    handoff = next(event for event in events if event.type == "agent.handoff.start")
    assert handoff.attributes["causentra.agent.to.name"] == "buyer"


def test_application_exception_is_preserved_and_message_is_private() -> None:
    exporter = MemoryExporter()
    runtime = CausentraRuntime("service", exporter)

    with pytest.raises(RuntimeError, match="customer secret"), runtime.trace("failure"):
        raise RuntimeError("customer secret")

    terminal = exporter.events[-1]
    assert terminal.status == "error"
    assert terminal.attributes == {"error.type": "RuntimeError"}


def test_telemetry_failure_does_not_change_application_behavior() -> None:
    class BrokenExporter:
        def emit(self, _event: object) -> None:
            raise RuntimeError("offline")

        def flush(self, timeout: float | None = None) -> bool:
            return False

        def shutdown(self, timeout: float | None = None) -> None:
            pass

    diagnostics = []
    runtime = CausentraRuntime("service", BrokenExporter(), on_error=diagnostics.append)
    with runtime.trace("still-works"):
        value = 42
    assert value == 42
    assert diagnostics and diagnostics[0].operation == "export"


def test_context_is_isolated_across_async_tasks() -> None:
    exporter = MemoryExporter()
    runtime = CausentraRuntime("async-service", exporter)

    async def run(name: str) -> str:
        async with runtime.trace(name) as context:
            await asyncio.sleep(0)
            async with runtime.tool("lookup"):
                await asyncio.sleep(0)
            return context.trace_id

    async def scenario() -> tuple[str, str]:
        left, right = await asyncio.gather(run("left"), run("right"))
        return left, right

    left, right = asyncio.run(scenario())
    assert left != right
    for trace_id in (left, right):
        assert [event.sequence for event in exporter.events if event.trace_id == trace_id] == [
            0,
            1,
            2,
            3,
        ]


def test_trace_from_w3c_carrier_continues_remote_trace() -> None:
    exporter = MemoryExporter()
    runtime = CausentraRuntime("consumer", exporter)
    carrier = {"traceparent": f"00-{'1' * 32}-{'2' * 16}-01"}
    with runtime.trace_from_carrier("consume", carrier) as context:
        pass
    assert context.trace_id == "1" * 32
    assert context.parent_span_id == "2" * 16


def test_runtime_instances_do_not_leak_active_context() -> None:
    first_exporter = MemoryExporter()
    second_exporter = MemoryExporter()
    first = CausentraRuntime("first", first_exporter)
    second = CausentraRuntime("second", second_exporter)
    with first.trace("outer"):
        assert second.current_context() is None
        with second.tool("independent") as second_context:
            pass
    assert second_exporter.events[0].type == "trace.start"
    assert second_exporter.events[0].trace_id == second_context.trace_id


def test_invalid_session_identifier_fails_during_configuration() -> None:
    with pytest.raises(ValueError, match="session_id"):
        CausentraRuntime("service", MemoryExporter(), session_id="tenant-name")

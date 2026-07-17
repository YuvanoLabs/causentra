from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from causentra import (
    CausentraRuntime,
    EventEngine,
    EventEngineCapacityError,
    EventEngineConflictError,
    NonRetryableEventError,
    RetryPolicy,
    RuntimeEvent,
)


def _event(index: int, event_type: str = "model.end", service: str = "billing") -> RuntimeEvent:
    return RuntimeEvent(
        schema_version="1.0",
        event_id=f"{index + 100:032x}",
        trace_id="c" * 32,
        span_id=f"{index + 1:016x}",
        sequence=index,
        timestamp="2026-07-16T10:00:00.000Z",
        type=event_type,
        name=f"operation-{index}",
        status="ok",
        service_name=service,
        attributes={"safe": True},
    )


def test_engine_routes_to_all_matching_named_subscriptions(tmp_path: Path) -> None:
    engine = EventEngine(tmp_path / "routes.sqlite", worker_count=2, poll_interval=0.01)
    model_events: list[str] = []
    billing_events: list[str] = []
    engine.subscribe(
        "models", lambda event: model_events.append(event.event_id), event_types=("model.*",)
    )
    engine.subscribe(
        "billing",
        lambda event: billing_events.append(event.event_id),
        event_types=("*.*",),
        services=("billing",),
    )

    assert engine.publish(_event(0)) == 2
    assert engine.publish(_event(1, service="search")) == 1
    assert engine.publish(_event(2, event_type="tool.end")) == 1
    assert engine.flush(2)
    assert set(model_events) == {_event(0).event_id, _event(1).event_id}
    assert set(billing_events) == {_event(0).event_id, _event(2).event_id}
    assert engine.stats.completed == 4
    engine.shutdown(2)


def test_engine_supports_async_handlers_and_bounded_retry(tmp_path: Path) -> None:
    engine = EventEngine(tmp_path / "retry.sqlite", poll_interval=0.005)
    attempts = 0
    delivered = threading.Event()

    async def handler(_event: RuntimeEvent) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary dependency outage")
        delivered.set()

    engine.subscribe(
        "async-retry",
        handler,
        retry=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.01, jitter=0),
    )
    engine.publish(_event(0))
    assert engine.flush(2)
    assert delivered.is_set()
    assert attempts == 2
    assert engine.stats.completed == 1
    engine.shutdown(2)


def test_engine_dead_letters_are_visible_and_explicitly_requeueable(tmp_path: Path) -> None:
    diagnostics = []
    engine = EventEngine(tmp_path / "dead.sqlite", poll_interval=0.005, on_error=diagnostics.append)
    reject = True

    def handler(_event: RuntimeEvent) -> None:
        if reject:
            raise NonRetryableEventError("policy destination is invalid")

    engine.subscribe("policy-sink", handler)
    engine.publish(_event(0))
    assert not engine.flush(2)
    dead = engine.dead_letters()
    assert len(dead) == 1
    assert dead[0].subscription == "policy-sink"
    assert dead[0].last_error == "NonRetryableEventError"
    assert diagnostics and diagnostics[0].dropped_events == 1

    reject = False
    assert engine.requeue_dead_letters(subscription="policy-sink") == 1
    assert engine.flush(2)
    assert engine.stats.completed == 1
    engine.shutdown(2)


def test_engine_is_idempotent_bounded_and_requires_explicit_completed_purge(
    tmp_path: Path,
) -> None:
    engine = EventEngine(tmp_path / "bounded.sqlite", max_events=1, poll_interval=0.005)
    received: list[str] = []
    engine.subscribe("sink", lambda event: received.append(event.event_id))
    event = _event(0)
    assert engine.publish(event) == 1
    assert engine.publish(event) == 0
    with pytest.raises(EventEngineConflictError):
        engine.publish(replace(event, name="different-operation"))
    assert engine.flush(2)
    assert received == [event.event_id]
    with pytest.raises(EventEngineCapacityError):
        engine.publish(_event(1))
    assert engine.purge_completed() == 1
    assert engine.publish(_event(1)) == 1
    assert engine.flush(2)
    engine.shutdown(2)
    engine.shutdown(2)
    assert not engine.worker_running


def test_causentra_runtime_can_use_event_engine_as_its_exporter(tmp_path: Path) -> None:
    engine = EventEngine(tmp_path / "runtime.sqlite", worker_count=1, poll_interval=0.005)
    types: list[str] = []
    engine.subscribe("audit", lambda event: types.append(event.type))
    runtime = CausentraRuntime("engine-runtime", engine)
    with runtime.trace("workflow"), runtime.agent("triage"):
        pass
    assert runtime.flush(2)
    assert types == ["trace.start", "agent.start", "agent.end", "trace.end"]
    runtime.shutdown(2)


def test_named_dead_letter_delivery_resumes_after_process_restart(tmp_path: Path) -> None:
    path = tmp_path / "restart.sqlite"
    first = EventEngine(path, poll_interval=0.005)

    def unavailable(_event: RuntimeEvent) -> None:
        raise NonRetryableEventError("offline")

    first.subscribe("stable-handler", unavailable)
    first.publish(_event(0))
    assert not first.flush(2)
    first.shutdown(2)

    delivered: list[str] = []
    second = EventEngine(path, poll_interval=0.005)
    second.subscribe("stable-handler", lambda event: delivered.append(event.event_id))
    assert second.requeue_dead_letters(subscription="stable-handler") == 1
    assert second.flush(2)
    assert delivered == [_event(0).event_id]
    second.shutdown(2)


def test_completed_trace_replay_is_explicit_and_subscription_scoped(tmp_path: Path) -> None:
    engine = EventEngine(tmp_path / "replay.sqlite", worker_count=1, poll_interval=0.005)
    received: list[tuple[str, str]] = []
    engine.subscribe("first", lambda event: received.append(("first", event.event_id)))
    engine.subscribe("second", lambda event: received.append(("second", event.event_id)))
    event = _event(0)
    engine.publish(event)
    assert engine.flush(2)
    assert len(received) == 2
    assert engine.replay_completed(trace_id=event.trace_id, subscription="first") == 1
    assert engine.flush(2)
    assert received.count(("first", event.event_id)) == 2
    assert received.count(("second", event.event_id)) == 1
    with pytest.raises(ValueError, match="exactly one"):
        engine.replay_completed()
    engine.shutdown(2)


def test_event_engine_migrates_pre_trace_index_database_without_losing_replay(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.sqlite"
    event = _event(0)
    payload = json.dumps(event.to_wire(), separators=(",", ":")).encode()
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE engine_events (
          event_id TEXT PRIMARY KEY,
          payload BLOB NOT NULL,
          payload_bytes INTEGER NOT NULL,
          created_at REAL NOT NULL
        );
        CREATE TABLE engine_deliveries (
          delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_id TEXT NOT NULL REFERENCES engine_events(event_id) ON DELETE CASCADE,
          subscription TEXT NOT NULL,
          state TEXT NOT NULL,
          attempts INTEGER NOT NULL,
          max_attempts INTEGER NOT NULL,
          available_at REAL NOT NULL,
          lease_owner TEXT,
          lease_expires_at REAL,
          last_error TEXT,
          UNIQUE(event_id, subscription)
        );
        """
    )
    connection.execute(
        "INSERT INTO engine_events VALUES (?, ?, ?, ?)",
        (event.event_id, payload, len(payload), time.time()),
    )
    connection.execute(
        """
        INSERT INTO engine_deliveries(
          event_id, subscription, state, attempts, max_attempts, available_at
        ) VALUES (?, 'stable', 'completed', 1, 3, ?)
        """,
        (event.event_id, time.time()),
    )
    connection.commit()
    connection.close()

    received: list[str] = []
    engine = EventEngine(path, worker_count=1, poll_interval=0.005)
    engine.subscribe("stable", lambda value: received.append(value.event_id))
    assert engine.replay_completed(trace_id=event.trace_id) == 1
    assert engine.flush(2)
    assert received == [event.event_id]
    engine.shutdown(2)

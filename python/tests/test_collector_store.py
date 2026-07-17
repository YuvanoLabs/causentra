from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from causentra import CausentraRuntime, EventValidationError, MemoryExporter
from causentra.collector_store import (
    CollectorCapacityError,
    IdempotencyConflictError,
    SqliteCollectorStore,
)
from causentra.types import RuntimeEvent


def _events() -> tuple[RuntimeEvent, ...]:
    exporter = MemoryExporter()
    runtime = CausentraRuntime("collector-test", exporter)
    with runtime.trace("workflow"), runtime.span("step"):
        pass
    return exporter.events


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_store_is_atomic_idempotent_tenant_isolated_and_persistent(tmp_path: Path) -> None:
    path = tmp_path / "collector.db"
    events = _events()
    store = SqliteCollectorStore(path)
    first = store.ingest("project-a", "batch-1", _digest("batch-1"), events)
    assert (first.accepted, first.duplicates, first.replayed_batch) == (4, 0, False)
    replay = store.ingest("project-a", "batch-1", _digest("batch-1"), events)
    assert (replay.accepted, replay.duplicates, replay.replayed_batch) == (0, 4, True)
    duplicate_events = store.ingest(
        "project-a", "batch-2", _digest("batch-2"), events
    )
    assert (duplicate_events.accepted, duplicate_events.duplicates) == (0, 4)
    second_tenant = store.ingest(
        "project-b", "batch-1", _digest("project-b-batch"), events
    )
    assert second_tenant.accepted == 4
    assert store.stats().projects == 2
    assert store.stats("project-a").events == 4
    traces = store.list_traces("project-a")
    assert len(traces) == 1
    assert traces[0]["eventCount"] == 4
    assert len(store.get_trace("project-a", events[0].trace_id)) == 4
    assert store.get_trace("missing-project", events[0].trace_id) == ()
    assert store.ready()
    store.close()

    reopened = SqliteCollectorStore(path)
    assert reopened.stats().events == 8
    assert reopened.delete_trace("project-a", events[0].trace_id) == 4
    assert reopened.stats("project-a").events == 0
    reopened.close()


def test_store_rejects_identifier_conflicts_and_rolls_back_capacity(tmp_path: Path) -> None:
    events = _events()
    store = SqliteCollectorStore(tmp_path / "collector.db", max_events=4)
    store.ingest("project-a", "batch-1", _digest("one"), events)
    with pytest.raises(IdempotencyConflictError):
        store.ingest("project-a", "batch-1", _digest("different"), events)
    changed = (replace(events[0], name="different"),)
    with pytest.raises(IdempotencyConflictError):
        store.ingest("project-a", "batch-2", _digest("two"), changed)
    with pytest.raises(CollectorCapacityError):
        store.ingest("project-b", "batch-1", _digest("three"), events)
    assert store.stats().events == 4
    assert store.stats().batches == 1
    store.close()


def test_store_rejects_conflicting_duplicate_within_one_batch(tmp_path: Path) -> None:
    event = _events()[0]
    changed = replace(event, status="error")
    store = SqliteCollectorStore(tmp_path / "collector.db")
    with pytest.raises(IdempotencyConflictError):
        store.ingest("project-a", "batch-1", _digest("one"), (event, changed))
    assert store.stats().events == 0
    store.close()


def test_store_enforces_project_quota_without_blocking_another_project(
    tmp_path: Path,
) -> None:
    events = _events()
    more = tuple(
        replace(event, event_id=f"{index + 1:032x}")
        for index, event in enumerate(events)
    )
    store = SqliteCollectorStore(
        tmp_path / "collector.db",
        max_events=8,
        max_project_events=4,
    )
    store.ingest("project-a", "batch-1", _digest("one"), events)
    with pytest.raises(CollectorCapacityError, match="project event"):
        store.ingest("project-a", "batch-2", _digest("two"), more)
    assert store.ingest("project-b", "batch-1", _digest("three"), events).accepted == 4
    store.close()


def test_store_validates_direct_events_and_creates_consistent_backup(tmp_path: Path) -> None:
    events = _events()
    store = SqliteCollectorStore(tmp_path / "collector.db")
    with pytest.raises(EventValidationError):
        store.ingest(
            "project-a",
            "invalid",
            _digest("invalid"),
            (replace(events[0], status="unsupported"),),  # type: ignore[arg-type]
        )
    store.ingest("project-a", "batch-1", _digest("one"), events)
    backup_path = store.backup(tmp_path / "backups" / "collector.db")
    with pytest.raises(ValueError, match="must differ"):
        store.backup(tmp_path / "collector.db")
    store.close()

    backup = SqliteCollectorStore(backup_path)
    assert backup.ready()
    assert backup.stats("project-a").events == len(events)
    backup.close()

"""Transactional multi-project storage for the Python collector."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

from .types import RuntimeEvent
from .validation import validate_event


class CollectorStoreError(RuntimeError):
    """Base class for durable collector storage failures."""


class IdempotencyConflictError(CollectorStoreError):
    """An idempotency or event identifier was reused for different data."""


class CollectorCapacityError(CollectorStoreError):
    """The configured durable storage capacity has been reached."""


@dataclass(frozen=True, slots=True)
class IngestResult:
    accepted: int
    duplicates: int
    replayed_batch: bool


@dataclass(frozen=True, slots=True)
class CollectorStoreStats:
    projects: int
    traces: int
    events: int
    payload_bytes: int
    batches: int


class SqliteCollectorStore:
    """Crash-safe SQLite event store with project-scoped uniqueness.

    A batch is inserted atomically. Reusing an event ID or idempotency key for
    different bytes fails closed instead of silently replacing telemetry.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        max_events: int = 10_000_000,
        max_payload_bytes: int = 20 * 1024 * 1024 * 1024,
        max_project_events: int | None = None,
        max_project_payload_bytes: int | None = None,
        busy_timeout: float = 5.0,
    ) -> None:
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        if max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")
        project_events = max_events if max_project_events is None else max_project_events
        project_bytes = (
            max_payload_bytes
            if max_project_payload_bytes is None
            else max_project_payload_bytes
        )
        if project_events <= 0 or project_events > max_events:
            raise ValueError("max_project_events must be positive and no greater than max_events")
        if project_bytes <= 0 or project_bytes > max_payload_bytes:
            raise ValueError(
                "max_project_payload_bytes must be positive and no greater than max_payload_bytes"
            )
        if busy_timeout <= 0:
            raise ValueError("busy_timeout must be positive")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self._path,
            timeout=busy_timeout,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute(f"PRAGMA busy_timeout={int(busy_timeout * 1_000)}")
        self._max_events = max_events
        self._max_payload_bytes = max_payload_bytes
        self._max_project_events = project_events
        self._max_project_payload_bytes = project_bytes
        self._lock = threading.RLock()
        self._closed = False
        self._migrate()

    def ingest(
        self,
        project_id: str,
        batch_id: str,
        payload_digest: str,
        events: tuple[RuntimeEvent, ...],
    ) -> IngestResult:
        if not events:
            raise ValueError("events cannot be empty")
        encoded: list[tuple[RuntimeEvent, bytes, str]] = []
        seen: dict[str, str] = {}
        duplicates = 0
        for event in events:
            validate_event(event)
            payload = json.dumps(
                event.to_wire(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            digest = hashlib.sha256(payload).hexdigest()
            existing = seen.get(event.event_id)
            if existing is not None:
                if existing != digest:
                    raise IdempotencyConflictError(
                        f"event ID {event.event_id} occurs with different payloads"
                    )
                duplicates += 1
                continue
            seen[event.event_id] = digest
            encoded.append((event, payload, digest))
        with self._transaction():
            batch = self._connection.execute(
                """
                SELECT payload_digest, event_count FROM collector_batches
                WHERE project_id = ? AND batch_id = ?
                """,
                (project_id, batch_id),
            ).fetchone()
            if batch is not None:
                if str(batch["payload_digest"]) != payload_digest:
                    raise IdempotencyConflictError(
                        "idempotency key was already used for a different request"
                    )
                return IngestResult(0, int(batch["event_count"]), True)
            current = self._connection.execute(
                """
                SELECT COUNT(*) AS count, COALESCE(SUM(payload_bytes), 0) AS size
                FROM collector_events
                """
            ).fetchone()
            project_current = self._connection.execute(
                """
                SELECT COUNT(*) AS count, COALESCE(SUM(payload_bytes), 0) AS size
                FROM collector_events WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
            assert current is not None and project_current is not None
            accepted: list[tuple[RuntimeEvent, bytes, str]] = []
            for event, payload, digest in encoded:
                row = self._connection.execute(
                    """
                    SELECT payload_digest FROM collector_events
                    WHERE project_id = ? AND event_id = ?
                    """,
                    (project_id, event.event_id),
                ).fetchone()
                if row is None:
                    accepted.append((event, payload, digest))
                elif str(row["payload_digest"]) == digest:
                    duplicates += 1
                else:
                    raise IdempotencyConflictError(
                        f"event ID {event.event_id} was already used for different data"
                    )
            additional_bytes = sum(len(payload) for _, payload, _ in accepted)
            if int(current["count"]) + len(accepted) > self._max_events:
                raise CollectorCapacityError("collector event capacity has been reached")
            if int(current["size"]) + additional_bytes > self._max_payload_bytes:
                raise CollectorCapacityError("collector byte capacity has been reached")
            if int(project_current["count"]) + len(accepted) > self._max_project_events:
                raise CollectorCapacityError("project event capacity has been reached")
            if (
                int(project_current["size"]) + additional_bytes
                > self._max_project_payload_bytes
            ):
                raise CollectorCapacityError("project byte capacity has been reached")
            received_at = time.time()
            self._connection.executemany(
                """
                INSERT INTO collector_events (
                    project_id, event_id, trace_id, span_id, sequence, timestamp,
                    event_type, name, status, service_name, payload, payload_digest,
                    payload_bytes, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        project_id,
                        event.event_id,
                        event.trace_id,
                        event.span_id,
                        event.sequence,
                        event.timestamp,
                        event.type,
                        event.name,
                        event.status,
                        event.service_name,
                        payload,
                        digest,
                        len(payload),
                        received_at,
                    )
                    for event, payload, digest in accepted
                ],
            )
            self._connection.execute(
                """
                INSERT INTO collector_batches (
                    project_id, batch_id, payload_digest, event_count,
                    accepted_count, received_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    batch_id,
                    payload_digest,
                    len(events),
                    len(accepted),
                    received_at,
                ),
            )
        return IngestResult(len(accepted), duplicates, False)

    def stats(self, project_id: str | None = None) -> CollectorStoreStats:
        event_query = """
            SELECT COUNT(*) AS events, COUNT(DISTINCT project_id) AS projects,
                   COUNT(DISTINCT project_id || ':' || trace_id) AS traces,
                   COALESCE(SUM(payload_bytes), 0) AS payload_bytes
            FROM collector_events
        """
        batch_query = "SELECT COUNT(*) AS batches FROM collector_batches"
        parameters: tuple[object, ...] = ()
        if project_id is not None:
            event_query += " WHERE project_id = ?"
            batch_query += " WHERE project_id = ?"
            parameters = (project_id,)
        with self._lock:
            self._ensure_open()
            event_row = self._connection.execute(event_query, parameters).fetchone()
            batch_row = self._connection.execute(batch_query, parameters).fetchone()
        assert event_row is not None and batch_row is not None
        return CollectorStoreStats(
            projects=int(event_row["projects"]),
            traces=int(event_row["traces"]),
            events=int(event_row["events"]),
            payload_bytes=int(event_row["payload_bytes"]),
            batches=int(batch_row["batches"]),
        )

    def list_traces(self, project_id: str, limit: int = 50) -> tuple[dict[str, Any], ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                """
                SELECT trace_id, MIN(timestamp) AS started_at, MAX(timestamp) AS last_event_at,
                       COUNT(*) AS event_count,
                       SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_count,
                       MAX(CASE WHEN event_type = 'trace.end' THEN 1 ELSE 0 END) AS ended,
                       COALESCE(
                         MAX(CASE WHEN event_type = 'trace.start' THEN name END),
                         MIN(name)
                       ) AS name,
                       COALESCE(
                         MAX(CASE WHEN event_type = 'trace.start' THEN service_name END),
                         MIN(service_name)
                       ) AS service_name
                FROM collector_events WHERE project_id = ?
                GROUP BY trace_id ORDER BY started_at DESC LIMIT ?
                """,
                (project_id, limit),
            ).fetchall()
        return tuple(
            {
                "traceId": str(row["trace_id"]),
                "name": str(row["name"]),
                "serviceName": str(row["service_name"]),
                "status": (
                    "error"
                    if int(row["error_count"]) > 0
                    else "ok"
                    if int(row["ended"]) > 0
                    else "running"
                ),
                "startedAt": str(row["started_at"]),
                "lastEventAt": str(row["last_event_at"]),
                "eventCount": int(row["event_count"]),
                "errorCount": int(row["error_count"]),
            }
            for row in rows
        )

    def get_trace(self, project_id: str, trace_id: str) -> tuple[RuntimeEvent, ...]:
        from .validation import event_from_wire

        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                """
                SELECT payload FROM collector_events
                WHERE project_id = ? AND trace_id = ?
                ORDER BY timestamp, sequence, event_id
                """,
                (project_id, trace_id),
            ).fetchall()
        return tuple(event_from_wire(json.loads(bytes(row["payload"]))) for row in rows)

    def delete_trace(self, project_id: str, trace_id: str) -> int:
        with self._transaction():
            cursor = self._connection.execute(
                "DELETE FROM collector_events WHERE project_id = ? AND trace_id = ?",
                (project_id, trace_id),
            )
        return int(cursor.rowcount)

    def prune_batches(self, *, older_than: float, limit: int = 10_000) -> int:
        if limit <= 0:
            raise ValueError("limit must be positive")
        with self._transaction():
            rows = self._connection.execute(
                """
                SELECT project_id, batch_id FROM collector_batches
                WHERE received_at < ? ORDER BY received_at LIMIT ?
                """,
                (older_than, limit),
            ).fetchall()
            if not rows:
                return 0
            self._connection.executemany(
                "DELETE FROM collector_batches WHERE project_id = ? AND batch_id = ?",
                [(str(row["project_id"]), str(row["batch_id"])) for row in rows],
            )
        return len(rows)

    def ready(self) -> bool:
        try:
            with self._lock:
                self._ensure_open()
                row = self._connection.execute("PRAGMA quick_check(1)").fetchone()
            return row is not None and str(row[0]).lower() == "ok"
        except sqlite3.Error:
            return False

    def checkpoint(self) -> None:
        with self._lock:
            self._ensure_open()
            self._connection.execute("PRAGMA wal_checkpoint(PASSIVE)")

    def backup(self, destination: str | Path) -> Path:
        """Create an atomic, transactionally consistent SQLite backup file."""

        target = Path(destination).expanduser().resolve()
        if target == self._path.expanduser().resolve():
            raise ValueError("backup destination must differ from the active database")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
        try:
            with self._lock:
                self._ensure_open()
                backup = sqlite3.connect(temporary)
                try:
                    self._connection.backup(backup)
                finally:
                    backup.close()
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def _migrate(self) -> None:
        with self._transaction():
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS collector_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            version = self._connection.execute(
                "SELECT value FROM collector_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if version is not None and str(version["value"]) != "1":
                raise CollectorStoreError("collector database schema version is unsupported")
            self._connection.execute(
                """
                INSERT OR IGNORE INTO collector_metadata(key, value)
                VALUES ('schema_version', '1')
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS collector_events (
                    project_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    span_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK(sequence >= 0),
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('unset', 'ok', 'error')),
                    service_name TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    payload_digest TEXT NOT NULL,
                    payload_bytes INTEGER NOT NULL CHECK(payload_bytes > 0),
                    received_at REAL NOT NULL,
                    PRIMARY KEY(project_id, event_id)
                ) WITHOUT ROWID
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS collector_trace_index
                ON collector_events(project_id, trace_id, timestamp, sequence)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS collector_batches (
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    event_count INTEGER NOT NULL CHECK(event_count > 0),
                    accepted_count INTEGER NOT NULL CHECK(accepted_count >= 0),
                    received_at REAL NOT NULL,
                    PRIMARY KEY(project_id, batch_id)
                ) WITHOUT ROWID
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS collector_batch_retention_index
                ON collector_batches(received_at)
                """
            )

    def _transaction(self) -> _Transaction:
        self._ensure_open()
        return _Transaction(self._connection, self._lock)

    def _ensure_open(self) -> None:
        if self._closed:
            raise CollectorStoreError("collector store is closed")


class _Transaction(AbstractContextManager[None]):
    def __init__(self, connection: sqlite3.Connection, lock: threading.RLock) -> None:
        self._connection = connection
        self._lock = lock

    def __enter__(self) -> None:
        self._lock.acquire()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
        except BaseException:
            self._lock.release()
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        try:
            self._connection.execute("COMMIT" if exc_type is None else "ROLLBACK")
        finally:
            self._lock.release()

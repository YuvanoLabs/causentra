"""Crash-recoverable, bounded event spool for durable transport exporters."""

from __future__ import annotations

import hmac
import json
import sqlite3
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .types import RuntimeEvent
from .validation import validate_event


class SpoolFullError(BufferError):
    """Raised when accepting another event would exceed a configured bound."""


class SpoolConflictError(RuntimeError):
    """Raised when an existing event ID is reused for different event bytes."""


@dataclass(frozen=True, slots=True)
class SpoolRecord:
    """One leased event and its durable delivery metadata."""

    sequence: int
    event_id: str
    payload: bytes
    attempts: int


@dataclass(frozen=True, slots=True)
class SpoolStats:
    """Operational counters suitable for health and readiness reporting."""

    pending: int
    in_flight: int
    dead_letter: int
    total_events: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class SpoolDeadLetter:
    """Privacy-safe terminal delivery record for operator inspection."""

    sequence: int
    event_id: str
    attempts: int
    error_type: str


class SqliteEventSpool:
    """Durable FIFO spool with leases, retry scheduling, and dead letters.

    SQLite WAL plus ``synchronous=FULL`` makes acceptance durable before
    ``enqueue`` returns. A lease prevents concurrent exporters from sending the
    same row intentionally; expired leases are recovered after a crash. Event
    IDs remain the end-to-end idempotency boundary.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        max_events: int = 100_000,
        max_bytes: int = 512 * 1024 * 1024,
        max_event_bytes: int = 256 * 1024,
        busy_timeout: float = 5.0,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._path = Path(path).expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_events = _positive_int(max_events, "max_events")
        self._max_bytes = _positive_int(max_bytes, "max_bytes")
        self._max_event_bytes = _positive_int(max_event_bytes, "max_event_bytes")
        self._now = now
        self._lock = threading.RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            self._path,
            timeout=_positive_number(busy_timeout, "busy_timeout"),
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute(f"PRAGMA busy_timeout={int(busy_timeout * 1_000)}")
            self._migrate()

    @property
    def path(self) -> Path:
        return self._path

    def enqueue(self, event: RuntimeEvent) -> bool:
        """Durably accept an event; return ``False`` for an existing event ID."""

        validate_event(event)
        payload = json.dumps(
            event.to_wire(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        if len(payload) > self._max_event_bytes:
            raise SpoolFullError(
                f"event requires {len(payload)} bytes; maximum is {self._max_event_bytes}"
            )
        with self._transaction():
            duplicate = self._connection.execute(
                "SELECT payload FROM spool_events WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            if duplicate is not None:
                if hmac.compare_digest(bytes(duplicate["payload"]), payload):
                    return False
                raise SpoolConflictError(
                    f"event ID {event.event_id} was already used for different data"
                )
            count, size = self._usage()
            if count >= self._max_events or size + len(payload) > self._max_bytes:
                raise SpoolFullError(
                    "durable spool capacity exceeded; deliver, requeue, or purge dead letters"
                )
            self._connection.execute(
                """
                INSERT INTO spool_events (
                    event_id, payload, payload_bytes, state, attempts,
                    available_at, created_at
                ) VALUES (?, ?, ?, 'pending', 0, ?, ?)
                """,
                (event.event_id, payload, len(payload), self._now(), self._now()),
            )
        return True

    def lease(
        self,
        limit: int,
        *,
        owner: str,
        lease_seconds: float,
    ) -> tuple[SpoolRecord, ...]:
        """Lease the oldest available rows and increment their attempt count."""

        batch_limit = _positive_int(limit, "limit")
        if not owner.strip() or len(owner) > 256:
            raise ValueError("owner must be non-empty and at most 256 characters")
        lease_duration = _positive_number(lease_seconds, "lease_seconds")
        now = self._now()
        with self._transaction():
            self._recover_expired_leases(now)
            rows = self._connection.execute(
                """
                SELECT sequence, event_id, payload, attempts
                FROM spool_events
                WHERE state = 'pending' AND available_at <= ?
                ORDER BY sequence
                LIMIT ?
                """,
                (now, batch_limit),
            ).fetchall()
            if not rows:
                return ()
            sequences = [int(row["sequence"]) for row in rows]
            # Only placeholder tokens are generated; every sequence value remains bound.
            placeholders = ",".join("?" for _ in sequences)
            update_query = (
                "UPDATE spool_events SET state = 'in_flight', lease_owner = ?, "  # nosec
                "lease_expires_at = ?, attempts = attempts + 1 "
                f"WHERE sequence IN ({placeholders}) AND state = 'pending'"
            )
            self._connection.execute(
                update_query,
                (owner, now + lease_duration, *sequences),
            )
            select_query = (
                "SELECT sequence, event_id, payload, attempts FROM spool_events "  # nosec
                f"WHERE sequence IN ({placeholders}) AND state = 'in_flight' "
                "AND lease_owner = ? ORDER BY sequence"
            )
            leased = self._connection.execute(
                select_query,
                (*sequences, owner),
            ).fetchall()
        return tuple(
            SpoolRecord(
                sequence=int(row["sequence"]),
                event_id=str(row["event_id"]),
                payload=bytes(row["payload"]),
                attempts=int(row["attempts"]),
            )
            for row in leased
        )

    def acknowledge(self, records: Sequence[SpoolRecord], *, owner: str) -> int:
        """Delete successfully delivered rows owned by this lease holder."""

        sequences = tuple(record.sequence for record in records)
        if not sequences:
            return 0
        # Only placeholder tokens are generated; every sequence value remains bound.
        placeholders = ",".join("?" for _ in sequences)
        with self._transaction():
            delete_query = (
                "DELETE FROM spool_events "  # nosec
                f"WHERE sequence IN ({placeholders}) AND state = 'in_flight' "
                "AND lease_owner = ?"
            )
            cursor = self._connection.execute(
                delete_query,
                (*sequences, owner),
            )
        return int(cursor.rowcount)

    def reject(
        self,
        records: Sequence[SpoolRecord],
        *,
        owner: str,
        error: BaseException,
        retry_at: float,
        max_attempts: int,
        permanent: bool = False,
    ) -> int:
        """Retry leased rows later or move exhausted rows to dead-letter state."""

        attempt_limit = _positive_int(max_attempts, "max_attempts")
        error_type = type(error).__name__[:256]
        dead = 0
        with self._transaction():
            for record in records:
                state = (
                    "dead_letter" if permanent or record.attempts >= attempt_limit else "pending"
                )
                dead += state == "dead_letter"
                self._connection.execute(
                    """
                    UPDATE spool_events
                    SET state = ?, available_at = ?, lease_owner = NULL,
                        lease_expires_at = NULL, last_error = ?
                    WHERE sequence = ? AND state = 'in_flight' AND lease_owner = ?
                    """,
                    (state, retry_at, error_type, record.sequence, owner),
                )
        return dead

    def dead_letters(self, *, limit: int = 100) -> tuple[SpoolDeadLetter, ...]:
        """Return bounded terminal records without persisting exception messages."""

        bounded = _positive_int(limit, "limit")
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                """
                SELECT sequence, event_id, attempts, last_error
                FROM spool_events WHERE state = 'dead_letter'
                ORDER BY sequence LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        return tuple(
            SpoolDeadLetter(
                sequence=int(row["sequence"]),
                event_id=str(row["event_id"]),
                attempts=int(row["attempts"]),
                error_type=str(row["last_error"] or "UnknownError"),
            )
            for row in rows
        )

    def requeue_dead_letters(self, *, limit: int = 1_000) -> int:
        """Explicitly return oldest dead letters to the delivery queue."""

        batch_limit = _positive_int(limit, "limit")
        with self._transaction():
            rows = self._connection.execute(
                """
                SELECT sequence FROM spool_events
                WHERE state = 'dead_letter' ORDER BY sequence LIMIT ?
                """,
                (batch_limit,),
            ).fetchall()
            sequences = [int(row["sequence"]) for row in rows]
            if not sequences:
                return 0
            # Only placeholder tokens are generated; every sequence value remains bound.
            placeholders = ",".join("?" for _ in sequences)
            update_query = (
                "UPDATE spool_events SET state = 'pending', attempts = 0, "  # nosec
                "available_at = ?, lease_owner = NULL, lease_expires_at = NULL, "
                "last_error = NULL "
                f"WHERE sequence IN ({placeholders})"
            )
            cursor = self._connection.execute(
                update_query,
                (self._now(), *sequences),
            )
        return int(cursor.rowcount)

    def purge_dead_letters(self, *, limit: int = 1_000) -> int:
        """Explicitly delete oldest dead letters after operator review."""

        batch_limit = _positive_int(limit, "limit")
        with self._transaction():
            cursor = self._connection.execute(
                """
                DELETE FROM spool_events WHERE sequence IN (
                    SELECT sequence FROM spool_events
                    WHERE state = 'dead_letter' ORDER BY sequence LIMIT ?
                )
                """,
                (batch_limit,),
            )
        return int(cursor.rowcount)

    def stats(self) -> SpoolStats:
        """Return a consistent snapshot of queue depth and disk ownership."""

        with self._lock:
            self._ensure_open()
            row = self._connection.execute(
                """
                SELECT
                  SUM(CASE WHEN state = 'pending' THEN 1 ELSE 0 END) AS pending,
                  SUM(CASE WHEN state = 'in_flight' THEN 1 ELSE 0 END) AS in_flight,
                  SUM(CASE WHEN state = 'dead_letter' THEN 1 ELSE 0 END) AS dead_letter,
                  COUNT(*) AS total_events,
                  COALESCE(SUM(payload_bytes), 0) AS total_bytes
                FROM spool_events
                """
            ).fetchone()
        assert row is not None
        return SpoolStats(
            pending=int(row["pending"] or 0),
            in_flight=int(row["in_flight"] or 0),
            dead_letter=int(row["dead_letter"] or 0),
            total_events=int(row["total_events"] or 0),
            total_bytes=int(row["total_bytes"] or 0),
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def _usage(self) -> tuple[int, int]:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(payload_bytes), 0) AS size FROM spool_events"
        ).fetchone()
        assert row is not None
        return int(row["count"]), int(row["size"])

    def _recover_expired_leases(self, now: float) -> None:
        self._connection.execute(
            """
            UPDATE spool_events
            SET state = 'pending', available_at = ?, lease_owner = NULL,
                lease_expires_at = NULL,
                last_error = COALESCE(last_error, 'LeaseExpired')
            WHERE state = 'in_flight' AND lease_expires_at <= ?
            """,
            (now, now),
        )

    def _migrate(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS spool_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS spool_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                payload BLOB NOT NULL,
                payload_bytes INTEGER NOT NULL CHECK(payload_bytes > 0),
                state TEXT NOT NULL CHECK(state IN ('pending', 'in_flight', 'dead_letter')),
                attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                available_at REAL NOT NULL,
                lease_owner TEXT,
                lease_expires_at REAL,
                last_error TEXT,
                created_at REAL NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS spool_delivery_index
            ON spool_events(state, available_at, sequence)
            """
        )
        version = self._connection.execute(
            "SELECT value FROM spool_meta WHERE key = 'schema_version'"
        ).fetchone()
        if version is None:
            self._connection.execute(
                "INSERT INTO spool_meta(key, value) VALUES ('schema_version', '1')"
            )
        elif version["value"] != "1":
            raise RuntimeError(f"unsupported spool schema version {version['value']}")

    def _transaction(self) -> _Transaction:
        self._ensure_open()
        return _Transaction(self._connection, self._lock)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("spool is closed")


class _Transaction:
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

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_value, traceback
        try:
            self._connection.execute("COMMIT" if exc_type is None else "ROLLBACK")
        finally:
            self._lock.release()


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)

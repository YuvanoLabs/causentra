"""Durable, bounded event routing engine for operational integrations."""

from __future__ import annotations

import asyncio
import fnmatch
import inspect
import json
import random
import sqlite3
import threading
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .types import RuntimeErrorContext, RuntimeEvent
from .validation import event_from_wire, validate_event

EventHandler = Callable[[RuntimeEvent], Awaitable[None] | None]


class EventEngineCapacityError(BufferError):
    """Raised when the durable event engine reaches a configured bound."""


class EventEngineConflictError(RuntimeError):
    """Raised when an existing event ID is reused for different event bytes."""


class NonRetryableEventError(RuntimeError):
    """A handler rejection that should move directly to dead-letter state."""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential retry policy for one named subscription."""

    max_attempts: int = 5
    base_delay: float = 0.25
    max_delay: float = 30.0
    jitter: float = 0.2

    def __post_init__(self) -> None:
        _positive_int(self.max_attempts, "max_attempts")
        _positive_number(self.base_delay, "base_delay")
        _positive_number(self.max_delay, "max_delay")
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay must be greater than or equal to base_delay")
        if not isinstance(self.jitter, int | float) or isinstance(self.jitter, bool):
            raise ValueError("jitter must be a number between 0 and 1")
        if not 0 <= self.jitter <= 1:
            raise ValueError("jitter must be between 0 and 1")

    def delay(self, attempt: int) -> float:
        unjittered = min(self.max_delay, self.base_delay * (2 ** max(0, attempt - 1)))
        return float(unjittered * random.uniform(1 - self.jitter, 1 + self.jitter))


@dataclass(frozen=True, slots=True)
class EventEngineStats:
    """Durable processing state for health, readiness, and alerting."""

    events: int
    pending: int
    in_flight: int
    completed: int
    dead_letter: int
    payload_bytes: int


@dataclass(frozen=True, slots=True)
class DeadLetter:
    """Operator-visible terminal handler failure."""

    event_id: str
    subscription: str
    attempts: int
    last_error: str


@dataclass(frozen=True, slots=True)
class _Subscription:
    name: str
    handler: EventHandler
    event_types: tuple[str, ...]
    services: frozenset[str]
    retry: RetryPolicy

    def matches(self, event: RuntimeEvent) -> bool:
        type_match = any(fnmatch.fnmatchcase(event.type, pattern) for pattern in self.event_types)
        return type_match and (not self.services or event.service_name in self.services)


@dataclass(frozen=True, slots=True)
class _Delivery:
    delivery_id: int
    event: RuntimeEvent
    subscription: str
    attempts: int
    max_attempts: int


class EventEngine:
    """Durable multi-subscriber event engine with failure isolation.

    ``emit`` satisfies the runtime exporter protocol. Events are committed once
    and independently delivered to every matching named subscription. Stable
    subscription names allow pending work to resume after process restart.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        worker_count: int = 2,
        max_events: int = 100_000,
        max_bytes: int = 512 * 1024 * 1024,
        lease_seconds: float = 30.0,
        poll_interval: float = 0.1,
        on_error: Callable[[RuntimeErrorContext], None] | None = None,
    ) -> None:
        self._worker_count = _positive_int(worker_count, "worker_count")
        self._lease_seconds = _positive_number(lease_seconds, "lease_seconds")
        self._poll_interval = _positive_number(poll_interval, "poll_interval")
        self._on_error = on_error or (lambda _context: None)
        self._store = _EventStore(path, max_events=max_events, max_bytes=max_bytes)
        self._subscriptions: dict[str, _Subscription] = {}
        self._subscription_lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._condition = threading.Condition()
        self._shutdown_lock = threading.Lock()
        self._accepting = True
        self._closed = False
        self._store_closed = False
        self._workers = tuple(
            threading.Thread(
                target=self._run,
                args=(f"worker-{index}",),
                name=f"causentra-event-engine-{index}",
                daemon=True,
            )
            for index in range(self._worker_count)
        )
        for worker in self._workers:
            worker.start()

    def subscribe(
        self,
        name: str,
        handler: EventHandler,
        *,
        event_types: Sequence[str] = ("*.*",),
        services: Sequence[str] = (),
        retry: RetryPolicy | None = None,
    ) -> None:
        """Register a stable route used for new and restart-pending deliveries."""

        normalized = _subscription_name(name)
        patterns = tuple(_event_pattern(pattern) for pattern in event_types)
        if not patterns:
            raise ValueError("event_types cannot be empty")
        service_set = frozenset(_service_name(service) for service in services)
        subscription = _Subscription(
            normalized, handler, patterns, service_set, retry or RetryPolicy()
        )
        with self._lifecycle_lock:
            if not self._accepting:
                raise RuntimeError("event engine is closed")
            with self._subscription_lock:
                if normalized in self._subscriptions:
                    raise ValueError(f"subscription {normalized!r} is already registered")
                self._subscriptions[normalized] = subscription
        with self._condition:
            self._condition.notify_all()

    def publish(self, event: RuntimeEvent) -> int:
        """Commit an event and return its number of matching deliveries."""

        with self._lifecycle_lock:
            validate_event(event)
            if not self._accepting:
                raise RuntimeError("event engine is closed")
            with self._subscription_lock:
                matched = tuple(
                    subscription
                    for subscription in self._subscriptions.values()
                    if subscription.matches(event)
                )
            if not matched:
                return 0
            accepted = self._store.publish(event, matched)
        with self._condition:
            self._condition.notify_all()
        return len(matched) if accepted else 0

    def emit(self, event: RuntimeEvent) -> None:
        """Fail-open exporter entry point used by :class:`CausentraRuntime`."""

        try:
            self.publish(event)
        except BaseException as error:
            self._report(error, 1)

    def flush(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while True:
            stats = self._store.stats()
            if stats.pending == 0 and stats.in_flight == 0:
                return stats.dead_letter == 0
            if not any(worker.is_alive() for worker in self._workers):
                return False
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            with self._condition:
                self._condition.notify_all()
                self._condition.wait(
                    self._poll_interval
                    if remaining is None
                    else min(remaining, self._poll_interval)
                )

    def shutdown(self, timeout: float | None = 10.0) -> None:
        with self._shutdown_lock:
            if self._store_closed:
                return
            started = time.monotonic()
            with self._lifecycle_lock:
                self._accepting = False
            if not self._closed:
                self.flush(timeout)
                with self._condition:
                    self._closed = True
                    self._condition.notify_all()
            for worker in self._workers:
                worker.join(_remaining(timeout, started))
            if any(worker.is_alive() for worker in self._workers):
                self._report(TimeoutError("event engine workers did not stop before timeout"), 0)
                return
            self._store.close()
            self._store_closed = True

    @property
    def worker_running(self) -> bool:
        """Return whether every configured worker is alive and accepting work."""

        return self._accepting and all(worker.is_alive() for worker in self._workers)

    @property
    def stats(self) -> EventEngineStats:
        return self._store.stats()

    def dead_letters(self, *, limit: int = 100) -> tuple[DeadLetter, ...]:
        return self._store.dead_letters(limit)

    def requeue_dead_letters(self, *, subscription: str | None = None, limit: int = 1_000) -> int:
        count = self._store.requeue_dead_letters(subscription=subscription, limit=limit)
        with self._condition:
            self._condition.notify_all()
        return count

    def purge_completed(self, *, limit: int = 1_000) -> int:
        """Explicitly remove events whose every delivery completed successfully."""

        return self._store.purge_completed(limit)

    def replay_completed(
        self,
        *,
        trace_id: str | None = None,
        event_id: str | None = None,
        subscription: str | None = None,
        limit: int = 1_000,
    ) -> int:
        """Explicitly replay completed deliveries selected by trace or event ID."""

        if (trace_id is None) == (event_id is None):
            raise ValueError("exactly one of trace_id or event_id must be supplied")
        count = self._store.replay_completed(
            trace_id=trace_id,
            event_id=event_id,
            subscription=subscription,
            limit=limit,
        )
        with self._condition:
            self._condition.notify_all()
        return count

    def _run(self, worker_name: str) -> None:
        owner = f"{worker_name}-{id(self):x}"
        try:
            while True:
                with self._condition:
                    if self._closed:
                        return
                with self._subscription_lock:
                    names = tuple(self._subscriptions)
                delivery = self._store.lease(
                    names,
                    owner=owner,
                    lease_seconds=self._lease_seconds,
                )
                if delivery is None:
                    with self._condition:
                        self._condition.wait(self._poll_interval)
                    continue
                self._dispatch(delivery, owner)
                with self._condition:
                    self._condition.notify_all()
        except BaseException as error:
            self._report(error, 0)

    def _dispatch(self, delivery: _Delivery, owner: str) -> None:
        with self._subscription_lock:
            subscription = self._subscriptions.get(delivery.subscription)
        if subscription is None:
            self._store.release(delivery.delivery_id, owner=owner)
            return
        try:
            result = subscription.handler(delivery.event)
            if inspect.isawaitable(result):
                asyncio.run(_await_handler(result))
            if not self._store.acknowledge(delivery.delivery_id, owner=owner):
                raise RuntimeError("event handler lease expired before acknowledgement")
        except BaseException as error:
            permanent = isinstance(error, NonRetryableEventError)
            dead = self._store.reject(
                delivery,
                owner=owner,
                error=error,
                retry_at=time.time() + subscription.retry.delay(delivery.attempts),
                permanent=permanent,
            )
            self._report(error, int(dead))

    def _report(self, error: BaseException, dropped: int) -> None:
        with suppress(BaseException):
            self._on_error(RuntimeErrorContext("adapter", error, dropped))


async def _await_handler(result: Awaitable[None]) -> None:
    await result


class _EventStore:
    def __init__(self, path: str | Path, *, max_events: int, max_bytes: int) -> None:
        self._path = Path(path).expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_events = _positive_int(max_events, "max_events")
        self._max_bytes = _positive_int(max_bytes, "max_bytes")
        self._lock = threading.RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            self._path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA busy_timeout=5000")
            self._migrate()

    def publish(self, event: RuntimeEvent, subscriptions: Sequence[_Subscription]) -> bool:
        payload = json.dumps(
            event.to_wire(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        now = time.time()
        with self._transaction():
            duplicate = self._connection.execute(
                "SELECT payload FROM engine_events WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            if duplicate is not None:
                if bytes(duplicate["payload"]) == payload:
                    return False
                raise EventEngineConflictError(
                    f"event ID {event.event_id} was already used for different data"
                )
            usage = self._connection.execute(
                """
                SELECT COUNT(*) AS count, COALESCE(SUM(payload_bytes), 0) AS size
                FROM engine_events
                """
            ).fetchone()
            assert usage is not None
            if (
                int(usage["count"]) >= self._max_events
                or int(usage["size"]) + len(payload) > self._max_bytes
            ):
                raise EventEngineCapacityError(
                    "event engine capacity exceeded; purge completed or resolve dead letters"
                )
            self._connection.execute(
                """
                INSERT INTO engine_events(
                    event_id, trace_id, payload, payload_bytes, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (event.event_id, event.trace_id, payload, len(payload), now),
            )
            self._connection.executemany(
                """
                INSERT INTO engine_deliveries(
                    event_id, subscription, state, attempts, max_attempts, available_at
                ) VALUES (?, ?, 'pending', 0, ?, ?)
                """,
                [
                    (event.event_id, subscription.name, subscription.retry.max_attempts, now)
                    for subscription in subscriptions
                ],
            )
        return True

    def lease(
        self,
        subscriptions: Sequence[str],
        *,
        owner: str,
        lease_seconds: float,
    ) -> _Delivery | None:
        if not subscriptions:
            return None
        # Only placeholder tokens are generated; every subscription value remains bound.
        placeholders = ",".join("?" for _ in subscriptions)
        now = time.time()
        with self._transaction():
            self._connection.execute(
                """
                UPDATE engine_deliveries
                SET state = 'pending', lease_owner = NULL, lease_expires_at = NULL,
                    available_at = ?,
                    last_error = COALESCE(last_error, 'LeaseExpired')
                WHERE state = 'in_flight' AND lease_expires_at <= ?
                """,
                (now, now),
            )
            lease_query = (
                "SELECT d.delivery_id FROM engine_deliveries d "  # nosec
                "JOIN engine_events e ON e.event_id = d.event_id "
                "WHERE d.state = 'pending' AND d.available_at <= ? "
                f"AND d.subscription IN ({placeholders}) "
                "ORDER BY e.created_at, d.delivery_id LIMIT 1"
            )
            row = self._connection.execute(
                lease_query,
                (now, *subscriptions),
            ).fetchone()
            if row is None:
                return None
            delivery_id = int(row["delivery_id"])
            self._connection.execute(
                """
                UPDATE engine_deliveries
                SET state = 'in_flight', lease_owner = ?, lease_expires_at = ?,
                    attempts = attempts + 1
                WHERE delivery_id = ? AND state = 'pending'
                """,
                (owner, now + lease_seconds, delivery_id),
            )
            leased = self._connection.execute(
                """
                SELECT d.delivery_id, d.subscription, d.attempts, d.max_attempts, e.payload
                FROM engine_deliveries d
                JOIN engine_events e ON e.event_id = d.event_id
                WHERE d.delivery_id = ? AND d.state = 'in_flight' AND d.lease_owner = ?
                """,
                (delivery_id, owner),
            ).fetchone()
        if leased is None:
            return None
        return _Delivery(
            delivery_id=int(leased["delivery_id"]),
            event=event_from_wire(json.loads(bytes(leased["payload"]))),
            subscription=str(leased["subscription"]),
            attempts=int(leased["attempts"]),
            max_attempts=int(leased["max_attempts"]),
        )

    def acknowledge(self, delivery_id: int, *, owner: str) -> bool:
        with self._transaction():
            cursor = self._connection.execute(
                """
                UPDATE engine_deliveries
                SET state = 'completed', lease_owner = NULL, lease_expires_at = NULL,
                    last_error = NULL
                WHERE delivery_id = ? AND state = 'in_flight' AND lease_owner = ?
                """,
                (delivery_id, owner),
            )
        return cursor.rowcount == 1

    def release(self, delivery_id: int, *, owner: str) -> None:
        with self._transaction():
            self._connection.execute(
                """
                UPDATE engine_deliveries
                SET state = 'pending', available_at = ?, lease_owner = NULL,
                    lease_expires_at = NULL
                WHERE delivery_id = ? AND state = 'in_flight' AND lease_owner = ?
                """,
                (time.time(), delivery_id, owner),
            )

    def reject(
        self,
        delivery: _Delivery,
        *,
        owner: str,
        error: BaseException,
        retry_at: float,
        permanent: bool,
    ) -> bool:
        dead = permanent or delivery.attempts >= delivery.max_attempts
        with self._transaction():
            cursor = self._connection.execute(
                """
                UPDATE engine_deliveries
                SET state = ?, available_at = ?, lease_owner = NULL,
                    lease_expires_at = NULL, last_error = ?
                WHERE delivery_id = ? AND state = 'in_flight' AND lease_owner = ?
                """,
                (
                    "dead_letter" if dead else "pending",
                    retry_at,
                    type(error).__name__[:256],
                    delivery.delivery_id,
                    owner,
                ),
            )
        return dead and cursor.rowcount == 1

    def stats(self) -> EventEngineStats:
        with self._lock:
            self._ensure_open()
            event_row = self._connection.execute(
                """
                SELECT COUNT(*) AS count, COALESCE(SUM(payload_bytes), 0) AS size
                FROM engine_events
                """
            ).fetchone()
            delivery_row = self._connection.execute(
                """
                SELECT
                  SUM(CASE WHEN state = 'pending' THEN 1 ELSE 0 END) AS pending,
                  SUM(CASE WHEN state = 'in_flight' THEN 1 ELSE 0 END) AS in_flight,
                  SUM(CASE WHEN state = 'completed' THEN 1 ELSE 0 END) AS completed,
                  SUM(CASE WHEN state = 'dead_letter' THEN 1 ELSE 0 END) AS dead_letter
                FROM engine_deliveries
                """
            ).fetchone()
        assert event_row is not None and delivery_row is not None
        return EventEngineStats(
            events=int(event_row["count"] or 0),
            pending=int(delivery_row["pending"] or 0),
            in_flight=int(delivery_row["in_flight"] or 0),
            completed=int(delivery_row["completed"] or 0),
            dead_letter=int(delivery_row["dead_letter"] or 0),
            payload_bytes=int(event_row["size"] or 0),
        )

    def dead_letters(self, limit: int) -> tuple[DeadLetter, ...]:
        bounded = _positive_int(limit, "limit")
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                """
                SELECT event_id, subscription, attempts, last_error
                FROM engine_deliveries
                WHERE state = 'dead_letter'
                ORDER BY delivery_id LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        return tuple(
            DeadLetter(
                event_id=str(row["event_id"]),
                subscription=str(row["subscription"]),
                attempts=int(row["attempts"]),
                last_error=str(row["last_error"] or "unknown error"),
            )
            for row in rows
        )

    def requeue_dead_letters(self, *, subscription: str | None, limit: int) -> int:
        bounded = _positive_int(limit, "limit")
        # SQL fragments are selected from fixed literals; external values remain bound.
        clause = "" if subscription is None else "AND subscription = ?"
        parameters: tuple[object, ...] = () if subscription is None else (subscription,)
        with self._transaction():
            select_query = (
                "SELECT delivery_id FROM engine_deliveries "  # nosec
                f"WHERE state = 'dead_letter' {clause} "
                "ORDER BY delivery_id LIMIT ?"
            )
            rows = self._connection.execute(
                select_query,
                (*parameters, bounded),
            ).fetchall()
            identifiers = [int(row["delivery_id"]) for row in rows]
            if not identifiers:
                return 0
            # Only placeholder tokens are generated; every identifier remains bound.
            placeholders = ",".join("?" for _ in identifiers)
            update_query = (
                "UPDATE engine_deliveries SET state = 'pending', attempts = 0, "  # nosec
                "available_at = ?, last_error = NULL "
                f"WHERE delivery_id IN ({placeholders})"
            )
            cursor = self._connection.execute(
                update_query,
                (time.time(), *identifiers),
            )
        return int(cursor.rowcount)

    def purge_completed(self, limit: int) -> int:
        bounded = _positive_int(limit, "limit")
        with self._transaction():
            rows = self._connection.execute(
                """
                SELECT e.event_id
                FROM engine_events e
                WHERE NOT EXISTS (
                  SELECT 1 FROM engine_deliveries d
                  WHERE d.event_id = e.event_id AND d.state != 'completed'
                )
                ORDER BY e.created_at LIMIT ?
                """,
                (bounded,),
            ).fetchall()
            identifiers = [str(row["event_id"]) for row in rows]
            if not identifiers:
                return 0
            # Only placeholder tokens are generated; every identifier remains bound.
            placeholders = ",".join("?" for _ in identifiers)
            delete_query = (
                f"DELETE FROM engine_events WHERE event_id IN ({placeholders})"  # nosec
            )
            cursor = self._connection.execute(delete_query, identifiers)
        return int(cursor.rowcount)

    def replay_completed(
        self,
        *,
        trace_id: str | None,
        event_id: str | None,
        subscription: str | None,
        limit: int,
    ) -> int:
        bounded = _positive_int(limit, "limit")
        # SQL fragments are selected from fixed literals; external values remain bound.
        selector = "e.trace_id = ?" if trace_id is not None else "e.event_id = ?"
        selected = trace_id if trace_id is not None else event_id
        subscription_clause = "" if subscription is None else "AND d.subscription = ?"
        parameters: tuple[object, ...] = (
            (selected,) if subscription is None else (selected, subscription)
        )
        with self._transaction():
            select_query = (
                "SELECT d.delivery_id FROM engine_deliveries d "  # nosec
                "JOIN engine_events e ON e.event_id = d.event_id "
                f"WHERE d.state = 'completed' AND {selector} "
                f"{subscription_clause} ORDER BY d.delivery_id LIMIT ?"
            )
            rows = self._connection.execute(
                select_query,
                (*parameters, bounded),
            ).fetchall()
            identifiers = [int(row["delivery_id"]) for row in rows]
            if not identifiers:
                return 0
            # Only placeholder tokens are generated; every identifier remains bound.
            placeholders = ",".join("?" for _ in identifiers)
            update_query = (
                "UPDATE engine_deliveries SET state = 'pending', attempts = 0, "  # nosec
                "available_at = ?, lease_owner = NULL, lease_expires_at = NULL, "
                "last_error = NULL "
                f"WHERE delivery_id IN ({placeholders})"
            )
            cursor = self._connection.execute(
                update_query,
                (time.time(), *identifiers),
            )
        return int(cursor.rowcount)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def _migrate(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS engine_events (
                event_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                payload BLOB NOT NULL,
                payload_bytes INTEGER NOT NULL CHECK(payload_bytes > 0),
                created_at REAL NOT NULL
            )
            """
        )
        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(engine_events)").fetchall()
        }
        if "trace_id" not in columns:
            self._connection.execute("ALTER TABLE engine_events ADD COLUMN trace_id TEXT")
        rows = self._connection.execute(
            """
            SELECT event_id, payload FROM engine_events
            WHERE trace_id IS NULL OR trace_id = ''
            """
        ).fetchall()
        if rows:
            self._connection.executemany(
                "UPDATE engine_events SET trace_id = ? WHERE event_id = ?",
                [
                    (str(json.loads(bytes(row["payload"]))["traceId"]), str(row["event_id"]))
                    for row in rows
                ],
            )
        self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS engine_trace_index
            ON engine_events(trace_id, created_at)
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS engine_deliveries (
                delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL REFERENCES engine_events(event_id) ON DELETE CASCADE,
                subscription TEXT NOT NULL,
                state TEXT NOT NULL CHECK(
                    state IN ('pending', 'in_flight', 'completed', 'dead_letter')
                ),
                attempts INTEGER NOT NULL CHECK(attempts >= 0),
                max_attempts INTEGER NOT NULL CHECK(max_attempts > 0),
                available_at REAL NOT NULL,
                lease_owner TEXT,
                lease_expires_at REAL,
                last_error TEXT,
                UNIQUE(event_id, subscription)
            )
            """
        )
        self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS engine_delivery_index
            ON engine_deliveries(state, available_at, delivery_id)
            """
        )

    def _transaction(self) -> _Transaction:
        self._ensure_open()
        return _Transaction(self._connection, self._lock)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("event engine store is closed")


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

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_value, traceback
        try:
            self._connection.execute("COMMIT" if exc_type is None else "ROLLBACK")
        finally:
            self._lock.release()


def _subscription_name(value: str) -> str:
    if not value.strip() or len(value) > 256:
        raise ValueError("subscription name must be non-empty and at most 256 characters")
    return value


def _event_pattern(value: str) -> str:
    if not value.strip() or len(value) > 128 or "." not in value:
        raise ValueError("event pattern must be dot-namespaced and at most 128 characters")
    return value


def _service_name(value: str) -> str:
    if not value.strip() or len(value) > 256:
        raise ValueError("service name must be non-empty and at most 256 characters")
    return value


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


def _remaining(timeout: float | None, started: float) -> float | None:
    return None if timeout is None else max(0.0, timeout - (time.monotonic() - started))

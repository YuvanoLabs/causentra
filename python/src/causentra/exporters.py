"""Built-in exporters with bounded, fail-open delivery semantics."""

from __future__ import annotations

import copy
import ipaddress
import json
import random
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable, Mapping
from contextlib import suppress
from urllib.parse import urlparse

from .types import RuntimeErrorContext, RuntimeEvent
from .validation import validate_event


class MemoryExporter:
    """Thread-safe exporter intended for tests and embedded inspection."""

    def __init__(self) -> None:
        self._events: list[RuntimeEvent] = []
        self._lock = threading.Lock()

    @property
    def events(self) -> tuple[RuntimeEvent, ...]:
        with self._lock:
            return tuple(copy.deepcopy(self._events))

    def emit(self, event: RuntimeEvent) -> None:
        with self._lock:
            self._events.append(copy.deepcopy(event))

    def flush(self, timeout: float | None = None) -> bool:
        del timeout
        return True

    def shutdown(self, timeout: float | None = None) -> None:
        del timeout


class HttpBatchExporter:
    """Bounded in-memory HTTP exporter for local inspection and development.

    ``emit`` never performs network I/O. A daemon worker sends at-least-once
    within process lifetime; abrupt termination can lose queued events. Use
    ``DurableTransportExporter`` for restart-safe production delivery.
    """

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:4318/v1/events",
        *,
        batch_size: int = 50,
        flush_interval: float = 1.0,
        max_queue_size: int = 2_000,
        max_retries: int = 2,
        request_timeout: float = 3.0,
        retry_base_delay: float = 0.1,
        headers: Mapping[str, str] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        allow_insecure_remote: bool = False,
        on_error: Callable[[RuntimeErrorContext], None] | None = None,
    ) -> None:
        self._endpoint = _url(endpoint, allow_insecure_remote=allow_insecure_remote)
        self._batch_size = _positive_int(batch_size, "batch_size")
        self._flush_interval = _positive_number(flush_interval, "flush_interval")
        self._max_queue_size = _positive_int(max_queue_size, "max_queue_size")
        self._max_retries = _non_negative_int(max_retries, "max_retries")
        self._request_timeout = _positive_number(request_timeout, "request_timeout")
        self._retry_base_delay = _positive_number(retry_base_delay, "retry_base_delay")
        self._headers = {str(key): str(value) for key, value in (headers or {}).items()}
        reserved = {key.lower() for key in self._headers} & {
            "content-length",
            "content-type",
        }
        if reserved:
            raise ValueError(f"HTTP exporter header is reserved: {sorted(reserved)[0]}")
        self._ssl_context = ssl_context
        self._on_error = on_error or (lambda _context: None)
        self._queue: deque[RuntimeEvent] = deque()
        self._condition = threading.Condition()
        self._closed = False
        self._sending = False
        self._flush_requested = False
        self._delivery_failed = False
        self._dropped = 0
        self._worker = threading.Thread(
            target=self._run, name="causentra-http-exporter", daemon=True
        )
        self._worker.start()

    @property
    def dropped_events(self) -> int:
        with self._condition:
            return self._dropped

    def emit(self, event: RuntimeEvent) -> None:
        error: BaseException | None = None
        try:
            validate_event(event)
            snapshot = copy.deepcopy(event)
        except BaseException as caught:
            snapshot = event
            error = caught
        with self._condition:
            if error is not None:
                self._dropped += 1
            elif self._closed:
                self._dropped += 1
                error = RuntimeError("exporter is closed")
            elif len(self._queue) >= self._max_queue_size:
                self._dropped += 1
                error = BufferError("export queue is full")
            else:
                self._queue.append(snapshot)
                if len(self._queue) >= self._batch_size:
                    self._condition.notify()
        if error is not None:
            self._report(error)

    def flush(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._condition:
            self._flush_requested = True
            self._delivery_failed = False
            self._condition.notify_all()
            while self._queue or self._sending:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return not self._delivery_failed

    def shutdown(self, timeout: float | None = 5.0) -> None:
        delivered = self.flush(timeout)
        pending = 0
        with self._condition:
            self._closed = True
            if not delivered:
                pending = len(self._queue)
                self._queue.clear()
                self._dropped += pending
            self._condition.notify_all()
        self._worker.join(timeout)
        if pending:
            self._report(RuntimeError("exporter closed with undelivered events"))

    def _run(self) -> None:
        while True:
            with self._condition:
                if not self._queue and not self._closed:
                    self._condition.wait(self._flush_interval)
                if self._closed and not self._queue:
                    return
                if not self._queue:
                    continue
                batch = [
                    self._queue.popleft() for _ in range(min(self._batch_size, len(self._queue)))
                ]
                self._sending = True
                self._flush_requested = False
            try:
                self._send(batch)
            except BaseException as error:  # instrumentation must contain every failure
                with self._condition:
                    self._delivery_failed = True
                    if self._closed:
                        lost = len(batch)
                    else:
                        # Preserve at-least-once ordering if capacity still exists.
                        room = self._max_queue_size - len(self._queue)
                        for event in reversed(batch[:room]):
                            self._queue.appendleft(event)
                        lost = len(batch) - room
                    if lost > 0:
                        self._dropped += lost
                self._report(error)
                # Avoid a hot loop while the collector is unavailable.
                time.sleep(min(self._flush_interval, 1.0))
            finally:
                with self._condition:
                    self._sending = False
                    self._condition.notify_all()

    def _send(self, events: list[RuntimeEvent]) -> None:
        payload = json.dumps(
            {"events": [event.to_wire() for event in events]},
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", **self._headers}
        last_error: BaseException = RuntimeError("export failed")
        for attempt in range(self._max_retries + 1):
            if attempt:
                delay = self._retry_base_delay * (2 ** (attempt - 1))
                time.sleep(delay * random.uniform(0.8, 1.2))
            request = urllib.request.Request(
                self._endpoint, data=payload, headers=headers, method="POST"
            )
            try:
                # Constructor validation permits only HTTP(S).
                with urllib.request.urlopen(  # nosec B310
                    request,
                    timeout=self._request_timeout,
                    context=self._ssl_context,
                ) as response:
                    if 200 <= response.status < 300:
                        return
                    last_error = RuntimeError(f"collector returned HTTP {response.status}")
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code < 500 and error.code != 429:
                    break
            except (OSError, urllib.error.URLError, TimeoutError) as error:
                last_error = error
        raise last_error

    def _report(self, error: BaseException) -> None:
        with suppress(BaseException):
            self._on_error(RuntimeErrorContext("export", error, self.dropped_events))


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


def _url(value: str, *, allow_insecure_remote: bool) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("endpoint must be an http:// or https:// URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("endpoint must not contain credentials")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("endpoint contains an invalid port") from error
    del port
    if (
        parsed.scheme == "http"
        and not _is_loopback(parsed.hostname)
        and not allow_insecure_remote
    ):
        raise ValueError("remote HTTP endpoint requires TLS")
    return value


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

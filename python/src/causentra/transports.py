"""Acknowledged transports and a crash-safe durable exporter."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import ipaddress
import json
import random
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Coroutine, Mapping, Sequence
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, cast, runtime_checkable
from urllib.parse import urlparse

from .spool import SpoolRecord, SpoolStats, SqliteEventSpool
from .types import RuntimeErrorContext, RuntimeEvent

_ResultT = TypeVar("_ResultT")


class TransportDeliveryError(RuntimeError):
    """A transport failure classified for durable retry handling."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class TransportBatch:
    """Stable JSON batch shared by every broker and HTTP transport."""

    batch_id: str
    event_ids: tuple[str, ...]
    payload: bytes

    @classmethod
    def from_records(cls, records: Sequence[SpoolRecord]) -> TransportBatch:
        if not records:
            raise ValueError("transport batch cannot be empty")
        event_ids = tuple(record.event_id for record in records)
        digest = hashlib.sha256("\n".join(event_ids).encode("ascii")).hexdigest()[:32]
        events = [json.loads(record.payload) for record in records]
        payload = json.dumps(
            {
                "transportVersion": "1.0",
                "batchId": digest,
                "events": events,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return cls(digest, event_ids, payload)


@runtime_checkable
class BatchTransport(Protocol):
    """Acknowledged delivery boundary used by :class:`DurableTransportExporter`."""

    @property
    def name(self) -> str: ...

    def send(self, batch: TransportBatch, *, timeout: float) -> None: ...

    def close(self, timeout: float | None = None) -> None: ...


class DurableTransportExporter:
    """Persist events before acknowledged delivery over a pluggable transport.

    Application threads perform one bounded SQLite transaction and never wait
    for a broker. A daemon worker owns delivery. Undelivered rows survive
    shutdown and process failure; exhausted rows remain visible as dead letters.
    """

    def __init__(
        self,
        spool: SqliteEventSpool,
        transport: BatchTransport,
        *,
        batch_size: int = 100,
        poll_interval: float = 0.25,
        delivery_timeout: float = 10.0,
        lease_seconds: float = 30.0,
        max_attempts: int = 10,
        retry_base_delay: float = 0.25,
        retry_max_delay: float = 60.0,
        on_error: Callable[[RuntimeErrorContext], None] | None = None,
    ) -> None:
        self._spool = spool
        self._transport = transport
        self._batch_size = _positive_int(batch_size, "batch_size")
        self._poll_interval = _positive_number(poll_interval, "poll_interval")
        self._delivery_timeout = _positive_number(delivery_timeout, "delivery_timeout")
        self._lease_seconds = _positive_number(lease_seconds, "lease_seconds")
        if self._lease_seconds <= self._delivery_timeout:
            raise ValueError("lease_seconds must be greater than delivery_timeout")
        self._max_attempts = _positive_int(max_attempts, "max_attempts")
        self._retry_base_delay = _positive_number(retry_base_delay, "retry_base_delay")
        self._retry_max_delay = _positive_number(retry_max_delay, "retry_max_delay")
        if self._retry_max_delay < self._retry_base_delay:
            raise ValueError("retry_max_delay must be greater than or equal to retry_base_delay")
        self._on_error = on_error or (lambda _context: None)
        self._owner = f"{transport.name}-{secrets.token_hex(16)}"
        self._emit_lock = threading.RLock()
        self._shutdown_lock = threading.Lock()
        self._condition = threading.Condition()
        self._accepting = True
        self._closed = False
        self._shutdown_complete = False
        self._shutdown_result: bool | None = None
        self._worker_stopped = False
        self._dead_lettered = 0
        self._rejected = 0
        self._worker = threading.Thread(
            target=self._run,
            name=f"causentra-{transport.name}-transport",
            daemon=True,
        )
        self._worker.start()

    @property
    def stats(self) -> SpoolStats:
        return self._spool.stats()

    @property
    def dead_lettered_events(self) -> int:
        with self._condition:
            return self._dead_lettered

    @property
    def rejected_events(self) -> int:
        with self._condition:
            return self._rejected

    @property
    def worker_running(self) -> bool:
        """Return whether the delivery worker is available to drain the spool."""

        with self._condition:
            return not self._worker_stopped and self._worker.is_alive()

    def emit(self, event: RuntimeEvent) -> None:
        error: BaseException | None = None
        with self._emit_lock:
            with self._condition:
                if not self._accepting:
                    self._rejected += 1
                    error = RuntimeError("durable exporter is closed")
            if error is None:
                try:
                    self._spool.enqueue(event)
                except BaseException as caught:
                    with self._condition:
                        self._rejected += 1
                    error = caught
        if error is not None:
            self._report(error)
            return
        if not self.worker_running:
            self._report(RuntimeError("durable transport worker is not running"))
        with self._condition:
            self._condition.notify_all()

    def flush(self, timeout: float | None = None) -> bool:
        if self._shutdown_complete:
            return bool(self._shutdown_result)
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._condition:
            self._condition.notify_all()
        while True:
            stats = self._spool.stats()
            if stats.pending == 0 and stats.in_flight == 0:
                return stats.dead_letter == 0
            with self._condition:
                if self._worker_stopped:
                    return False
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            with self._condition:
                self._condition.wait(
                    self._poll_interval
                    if remaining is None
                    else min(self._poll_interval, remaining)
                )

    def shutdown(self, timeout: float | None = 10.0) -> None:
        with self._shutdown_lock:
            if self._shutdown_complete:
                return
            started = time.monotonic()
            with self._emit_lock, self._condition:
                self._accepting = False
            self._shutdown_result = self.flush(timeout)
            with self._condition:
                self._closed = True
                self._condition.notify_all()
            remaining = _remaining(timeout, started)
            self._worker.join(remaining)
            if self._worker.is_alive():
                self._report(TimeoutError("transport worker did not stop before shutdown timeout"))
                return
            try:
                self._transport.close(_remaining(timeout, started))
            except BaseException as error:
                self._report(error)
            finally:
                self._spool.close()
                self._shutdown_complete = True

    def _run(self) -> None:
        try:
            while True:
                with self._condition:
                    if self._closed:
                        return
                records = self._spool.lease(
                    self._batch_size,
                    owner=self._owner,
                    lease_seconds=self._lease_seconds,
                )
                if not records:
                    with self._condition:
                        self._condition.wait(self._poll_interval)
                    continue
                self._deliver(records)
                with self._condition:
                    self._condition.notify_all()
        except BaseException as error:
            self._report(error)
        finally:
            with self._condition:
                self._worker_stopped = True
                self._condition.notify_all()

    def _deliver(self, records: Sequence[SpoolRecord]) -> None:
        try:
            batch = TransportBatch.from_records(records)
            self._transport.send(batch, timeout=self._delivery_timeout)
            accepted = self._spool.acknowledge(records, owner=self._owner)
            if accepted != len(records):
                raise RuntimeError("delivery lease expired before acknowledgement")
        except BaseException as error:
            retryable = not isinstance(error, TransportDeliveryError) or error.retryable
            attempts = max(record.attempts for record in records)
            delay = min(
                self._retry_max_delay,
                self._retry_base_delay * (2 ** max(0, attempts - 1)),
            ) * random.uniform(0.8, 1.2)
            dead = self._spool.reject(
                records,
                owner=self._owner,
                error=error,
                retry_at=time.time() + delay,
                max_attempts=self._max_attempts,
                permanent=not retryable,
            )
            with self._condition:
                self._dead_lettered += dead
            self._report(error)

    def _report(self, error: BaseException) -> None:
        with suppress(BaseException):
            self._on_error(
                RuntimeErrorContext(
                    "export",
                    error,
                    self.rejected_events + self.dead_lettered_events,
                )
            )


class HttpTransport:
    """Acknowledged HTTP transport with secure-remote defaults."""

    name = "http"

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:4318/v1/events",
        *,
        headers: Mapping[str, str] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        allow_insecure_remote: bool = False,
    ) -> None:
        _secure_endpoint(
            endpoint, secure_scheme="https", allow_insecure_remote=allow_insecure_remote
        )
        self._endpoint = endpoint
        self._headers = {str(key): str(value) for key, value in (headers or {}).items()}
        reserved = {
            key.lower() for key in self._headers
        } & {"content-type", "content-length", "idempotency-key"}
        if reserved:
            raise ValueError(f"HTTP transport header is reserved: {sorted(reserved)[0]}")
        self._ssl_context = ssl_context

    def send(self, batch: TransportBatch, *, timeout: float) -> None:
        request = urllib.request.Request(
            self._endpoint,
            data=batch.payload,
            headers={
                **self._headers,
                "Content-Type": "application/json",
                "Idempotency-Key": batch.batch_id,
            },
            method="POST",
        )
        try:
            # Endpoint validation permits only HTTP(S).
            with urllib.request.urlopen(  # nosec B310
                request,
                timeout=_positive_number(timeout, "timeout"),
                context=self._ssl_context,
            ) as response:
                if 200 <= response.status < 300:
                    return
                raise TransportDeliveryError(
                    f"HTTP endpoint returned {response.status}",
                    retryable=response.status >= 500 or response.status in (408, 429),
                )
        except urllib.error.HTTPError as error:
            raise TransportDeliveryError(
                f"HTTP endpoint returned {error.code}",
                retryable=error.code >= 500 or error.code in (408, 429),
            ) from error
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            raise TransportDeliveryError(f"HTTP delivery failed: {error}") from error

    def close(self, timeout: float | None = None) -> None:
        del timeout


class _KafkaProducer(Protocol):
    def produce(self, topic: str, **kwargs: object) -> None: ...

    def poll(self, timeout: float) -> int: ...

    def flush(self, timeout: float | None = None) -> int: ...


class KafkaTransport:
    """Kafka producer transport with idempotent, all-replica defaults."""

    name = "kafka"

    def __init__(
        self,
        topic: str,
        *,
        config: Mapping[str, object] | None = None,
        producer: _KafkaProducer | None = None,
        allow_insecure_remote: bool = False,
    ) -> None:
        self._topic = _channel(topic, "topic")
        effective = {
            "bootstrap.servers": "127.0.0.1:9092",
            "enable.idempotence": True,
            "acks": "all",
            "compression.type": "zstd",
            "client.id": "causentra-python",
            **(config or {}),
        }
        if effective.get("enable.idempotence") is not True or effective.get("acks") != "all":
            raise ValueError("Kafka transport requires idempotence and acks=all")
        remote = any(
            not _is_loopback(host)
            for host in _kafka_hosts(str(effective["bootstrap.servers"]))
        )
        protocol = str(effective.get("security.protocol", "PLAINTEXT")).upper()
        if remote and protocol not in {"SSL", "SASL_SSL"} and not allow_insecure_remote:
            raise ValueError("remote Kafka requires SSL or SASL_SSL")
        if producer is None:
            module = _optional_module("confluent_kafka", "kafka")
            self._producer = cast(_KafkaProducer, module.Producer(effective))
        else:
            self._producer = producer

    def send(self, batch: TransportBatch, *, timeout: float) -> None:
        delivered = threading.Event()
        failure: list[object] = []

        def callback(error: object | None, _message: object) -> None:
            if error is not None:
                failure.append(error)
            delivered.set()

        try:
            self._producer.produce(
                self._topic,
                value=batch.payload,
                key=batch.batch_id,
                headers=[
                    ("content-type", b"application/json"),
                    ("batch-id", batch.batch_id.encode()),
                ],
                on_delivery=callback,
            )
            deadline = time.monotonic() + _positive_number(timeout, "timeout")
            while not delivered.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportDeliveryError("Kafka delivery acknowledgement timed out")
                self._producer.poll(min(0.1, remaining))
            if failure:
                raise TransportDeliveryError(f"Kafka broker rejected batch: {failure[0]}")
        except TransportDeliveryError:
            raise
        except BaseException as error:
            raise TransportDeliveryError(f"Kafka delivery failed: {error}") from error

    def close(self, timeout: float | None = None) -> None:
        remaining = self._producer.flush(10.0 if timeout is None else max(0.0, timeout))
        if remaining:
            raise TransportDeliveryError(f"Kafka close left {remaining} messages unacknowledged")


class _RedisClient(Protocol):
    def xadd(self, name: str, fields: Mapping[str, object], **kwargs: object) -> object: ...

    def close(self) -> None: ...


class RedisStreamsTransport:
    """Redis Streams transport; XADD response is the server acknowledgement."""

    name = "redis"

    def __init__(
        self,
        stream: str = "causentra.events",
        *,
        url: str = "redis://127.0.0.1:6379/0",
        client: _RedisClient | None = None,
        max_length: int | None = None,
        socket_timeout: float = 10.0,
        allow_insecure_remote: bool = False,
    ) -> None:
        self._stream = _channel(stream, "stream")
        self._max_length = None if max_length is None else _positive_int(max_length, "max_length")
        configured_timeout = _positive_number(socket_timeout, "socket_timeout")
        self._socket_timeout: float | None = configured_timeout if client is None else None
        if client is None:
            _secure_endpoint(
                url,
                secure_scheme="rediss",
                allow_insecure_remote=allow_insecure_remote,
            )
            module = _optional_module("redis", "redis")
            self._client = cast(
                _RedisClient,
                module.Redis.from_url(
                    url,
                    socket_connect_timeout=configured_timeout,
                    socket_timeout=configured_timeout,
                ),
            )
        else:
            self._client = client

    def send(self, batch: TransportBatch, *, timeout: float) -> None:
        if (
            self._socket_timeout is not None
            and _positive_number(timeout, "timeout") < self._socket_timeout
        ):
            raise ValueError(
                "delivery timeout cannot be lower than the Redis socket_timeout"
            )
        kwargs: dict[str, object] = {}
        if self._max_length is not None:
            kwargs.update(maxlen=self._max_length, approximate=True)
        try:
            message_id = self._client.xadd(
                self._stream,
                {
                    "batch_id": batch.batch_id,
                    "content_type": "application/json",
                    "payload": batch.payload,
                },
                **kwargs,
            )
            if message_id is None:
                raise TransportDeliveryError("Redis XADD returned no stream ID")
        except TransportDeliveryError:
            raise
        except BaseException as error:
            raise TransportDeliveryError(f"Redis Streams delivery failed: {error}") from error

    def close(self, timeout: float | None = None) -> None:
        del timeout
        self._client.close()


class _MqttMessageInfo(Protocol):
    rc: int

    def wait_for_publish(self, timeout: float | None = None) -> object: ...

    def is_published(self) -> bool: ...


class _MqttClient(Protocol):
    def publish(self, topic: str, payload: bytes, qos: int, retain: bool) -> _MqttMessageInfo: ...

    def disconnect(self) -> object: ...

    def loop_stop(self) -> object: ...


class MqttTransport:
    """MQTT QoS 1/2 transport that waits for protocol-level publication."""

    name = "mqtt"

    def __init__(
        self,
        topic: str = "causentra/events",
        *,
        client: _MqttClient | None = None,
        host: str = "127.0.0.1",
        port: int = 8883,
        qos: int = 1,
        username: str | None = None,
        password: str | None = None,
        tls: bool = True,
        allow_insecure_remote: bool = False,
    ) -> None:
        self._topic = _channel(topic, "topic")
        if qos not in (1, 2):
            raise ValueError("qos must be 1 or 2 for acknowledged delivery")
        self._qos = qos
        if client is None:
            if not tls and not allow_insecure_remote and not _is_loopback(host):
                raise ValueError("remote MQTT requires TLS unless explicitly acknowledged")
            module = _optional_module("paho.mqtt.client", "mqtt")
            created = module.Client(module.CallbackAPIVersion.VERSION2)
            if username is not None:
                created.username_pw_set(username, password)
            if tls:
                created.tls_set()
            created.connect(host, _positive_int(port, "port"))
            created.loop_start()
            self._client = cast(_MqttClient, created)
        else:
            self._client = client

    def send(self, batch: TransportBatch, *, timeout: float) -> None:
        try:
            info = self._client.publish(self._topic, batch.payload, qos=self._qos, retain=False)
            if info.rc != 0:
                raise TransportDeliveryError(f"MQTT publish returned result code {info.rc}")
            info.wait_for_publish(_positive_number(timeout, "timeout"))
            if not info.is_published():
                raise TransportDeliveryError("MQTT publish acknowledgement timed out")
        except TransportDeliveryError:
            raise
        except BaseException as error:
            raise TransportDeliveryError(f"MQTT delivery failed: {error}") from error

    def close(self, timeout: float | None = None) -> None:
        del timeout
        self._client.disconnect()
        self._client.loop_stop()


class WebSocketTransport:
    """Request/ack WebSocket transport with batch-ID verification."""

    name = "websocket"

    def __init__(
        self,
        uri: str,
        *,
        headers: Mapping[str, str] | None = None,
        allow_insecure_remote: bool = False,
        connect_factory: Callable[..., Any] | None = None,
    ) -> None:
        _secure_endpoint(uri, secure_scheme="wss", allow_insecure_remote=allow_insecure_remote)
        self._uri = uri
        self._headers = dict(headers or {})
        if connect_factory is None:
            module = _optional_module("websockets.sync.client", "websocket")
            self._connect = cast(Callable[..., Any], module.connect)
        else:
            self._connect = connect_factory

    def send(self, batch: TransportBatch, *, timeout: float) -> None:
        try:
            with self._connect(
                self._uri,
                additional_headers=self._headers,
                open_timeout=timeout,
                close_timeout=timeout,
                max_size=64 * 1024,
            ) as connection:
                connection.send(batch.payload)
                raw = connection.recv(timeout=timeout)
            try:
                ack = json.loads(raw, object_pairs_hook=_unique_json_object)
            except (
                json.JSONDecodeError,
                UnicodeDecodeError,
                TypeError,
                ValueError,
                RecursionError,
            ) as error:
                raise TransportDeliveryError(
                    "WebSocket acknowledgement was not valid JSON",
                    retryable=False,
                ) from error
            if not isinstance(ack, dict) or ack.get("batchId") != batch.batch_id:
                raise TransportDeliveryError(
                    "WebSocket acknowledgement did not match the batch ID",
                    retryable=False,
                )
            retryable = ack.get("retryable", False)
            if not isinstance(retryable, bool):
                raise TransportDeliveryError(
                    "WebSocket acknowledgement retryable flag was invalid",
                    retryable=False,
                )
            if ack.get("accepted") is not True:
                raise TransportDeliveryError(
                    "WebSocket receiver rejected the batch",
                    retryable=retryable,
                )
        except TransportDeliveryError:
            raise
        except BaseException as error:
            raise TransportDeliveryError(f"WebSocket delivery failed: {error}") from error

    def close(self, timeout: float | None = None) -> None:
        del timeout


class NatsJetStreamTransport:
    """NATS JetStream transport with persistence acknowledgement and dedup ID."""

    name = "nats"

    def __init__(
        self,
        subject: str = "causentra.events",
        *,
        servers: Sequence[str] = ("nats://127.0.0.1:4222",),
        connect_options: Mapping[str, object] | None = None,
        jetstream: object | None = None,
        allow_insecure_remote: bool = False,
    ) -> None:
        self._subject = _channel(subject, "subject")
        self._servers = tuple(servers)
        if not self._servers:
            raise ValueError("servers cannot be empty")
        self._connect_options = dict(connect_options or {})
        tls_enabled = bool(self._connect_options.get("tls"))
        for server in self._servers:
            _secure_nats_server(
                server,
                tls_enabled=tls_enabled,
                allow_insecure_remote=allow_insecure_remote,
            )
        self._jetstream = jetstream
        self._connection: Any = None
        self._bridge = _AsyncBridge("causentra-nats-loop")

    def send(self, batch: TransportBatch, *, timeout: float) -> None:
        try:
            self._bridge.run(self._publish(batch), timeout)
        except FutureTimeoutError as error:
            raise TransportDeliveryError("NATS JetStream acknowledgement timed out") from error
        except TransportDeliveryError:
            raise
        except BaseException as error:
            raise TransportDeliveryError(f"NATS JetStream delivery failed: {error}") from error

    def close(self, timeout: float | None = None) -> None:
        effective = 5.0 if timeout is None else max(0.001, timeout)
        try:
            self._bridge.run(self._close_connection(), effective)
        finally:
            self._bridge.close(effective)

    async def _publish(self, batch: TransportBatch) -> None:
        jetstream = await self._get_jetstream()
        acknowledgement = await jetstream.publish(
            self._subject,
            batch.payload,
            headers={"Nats-Msg-Id": batch.batch_id, "Content-Type": "application/json"},
        )
        if acknowledgement is None:
            raise TransportDeliveryError("NATS JetStream returned no persistence acknowledgement")

    async def _get_jetstream(self) -> Any:
        if self._jetstream is not None:
            return self._jetstream
        module = _optional_module("nats", "nats")
        self._connection = await module.connect(
            servers=list(self._servers),
            **self._connect_options,
        )
        self._jetstream = self._connection.jetstream()
        return self._jetstream

    async def _close_connection(self) -> None:
        if self._connection is not None:
            await self._connection.drain()
            self._connection = None
            self._jetstream = None


class _AsyncBridge:
    def __init__(self, name: str) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()
        if not self._ready.wait(5.0):
            raise RuntimeError("async transport event loop failed to start")

    def run(self, coroutine: Coroutine[Any, Any, _ResultT], timeout: float) -> _ResultT:
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(_positive_number(timeout, "timeout"))
        except BaseException:
            future.cancel()
            raise

    def close(self, timeout: float) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise TimeoutError("async transport event loop did not stop")

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()
        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self._loop.close()


def _optional_module(module_name: str, extra: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        raise RuntimeError(f"{module_name} is optional; install causentra[{extra}]") from error


def _secure_endpoint(value: str, *, secure_scheme: str, allow_insecure_remote: bool) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in (secure_scheme, _insecure_scheme(secure_scheme)) or not parsed.hostname:
        raise ValueError(f"endpoint must use {secure_scheme} or {_insecure_scheme(secure_scheme)}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("endpoint credentials must be supplied outside the URL")
    if (
        parsed.scheme != secure_scheme
        and not allow_insecure_remote
        and not _is_loopback(parsed.hostname)
    ):
        raise ValueError(f"remote endpoint requires {secure_scheme} unless explicitly acknowledged")


def _insecure_scheme(secure_scheme: str) -> str:
    return {"https": "http", "wss": "ws", "rediss": "redis"}[secure_scheme]


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _kafka_hosts(value: str) -> tuple[str, ...]:
    if not value.strip():
        raise ValueError("Kafka bootstrap.servers cannot be empty")
    hosts: list[str] = []
    for server in value.split(","):
        candidate = server.strip()
        if not candidate:
            raise ValueError("Kafka bootstrap.servers contains an empty server")
        if candidate.startswith("["):
            closing = candidate.find("]")
            if closing <= 1:
                raise ValueError("Kafka bootstrap.servers contains an invalid IPv6 host")
            host = candidate[1:closing]
        else:
            host = candidate.rsplit(":", 1)[0] if ":" in candidate else candidate
        if not host:
            raise ValueError("Kafka bootstrap.servers contains an invalid host")
        hosts.append(host)
    return tuple(hosts)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _secure_nats_server(
    value: str, *, tls_enabled: bool, allow_insecure_remote: bool
) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"nats", "tls"} or not parsed.hostname:
        raise ValueError("NATS server must use nats:// or tls://")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("NATS credentials must be supplied through connect_options")
    secure = parsed.scheme == "tls" or tls_enabled
    if not secure and not allow_insecure_remote and not _is_loopback(parsed.hostname):
        raise ValueError("remote NATS requires TLS unless explicitly acknowledged")


def _channel(value: str, name: str) -> str:
    if not value.strip() or len(value) > 512:
        raise ValueError(f"{name} must be non-empty and at most 512 characters")
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

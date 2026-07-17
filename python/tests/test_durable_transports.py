from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from causentra import (
    DurableTransportExporter,
    HttpTransport,
    KafkaTransport,
    MqttTransport,
    NatsJetStreamTransport,
    RedisStreamsTransport,
    RuntimeEvent,
    SpoolConflictError,
    SpoolFullError,
    SqliteEventSpool,
    TransportBatch,
    TransportDeliveryError,
    WebSocketTransport,
)


def _event(index: int) -> RuntimeEvent:
    return RuntimeEvent(
        schema_version="1.0",
        event_id=f"{index + 1:032x}",
        trace_id="a" * 32,
        span_id="b" * 16,
        sequence=index,
        timestamp="2026-07-16T10:00:00.000Z",
        type="custom.event",
        name=f"event-{index}",
        status="unset",
        service_name="transport-tests",
        attributes={"safe": index},
    )


def _batch(tmp_path: Path, count: int = 2) -> TransportBatch:
    spool = SqliteEventSpool(tmp_path / "batch.sqlite")
    for index in range(count):
        spool.enqueue(_event(index))
    records = spool.lease(count, owner="batch-test", lease_seconds=10)
    result = TransportBatch.from_records(records)
    spool.close()
    return result


def test_spool_is_bounded_idempotent_and_recovers_expired_leases(tmp_path: Path) -> None:
    clock = [100.0]
    path = tmp_path / "spool.sqlite"
    spool = SqliteEventSpool(path, max_events=2, now=lambda: clock[0])
    assert spool.enqueue(_event(0))
    assert not spool.enqueue(_event(0))
    with pytest.raises(SpoolConflictError):
        spool.enqueue(replace(_event(0), name="different"))
    assert spool.enqueue(_event(1))
    with pytest.raises(SpoolFullError):
        spool.enqueue(_event(2))

    first = spool.lease(2, owner="crashed-worker", lease_seconds=5)
    assert first and first[0].attempts == 1
    assert not spool.lease(1, owner="new-worker", lease_seconds=5)
    clock[0] = 106.0
    recovered = spool.lease(1, owner="new-worker", lease_seconds=5)
    assert recovered[0].event_id == first[0].event_id
    assert recovered[0].attempts == 2
    assert spool.acknowledge(recovered, owner="new-worker") == 1
    spool.close()

    reopened = SqliteEventSpool(path, max_events=2, now=lambda: clock[0])
    assert reopened.stats().total_events == 1
    reopened.close()


def test_spool_dead_letters_require_explicit_requeue_or_purge(tmp_path: Path) -> None:
    spool = SqliteEventSpool(tmp_path / "dead.sqlite")
    spool.enqueue(_event(0))
    records = spool.lease(1, owner="worker", lease_seconds=5)
    dead = spool.reject(
        records,
        owner="worker",
        error=ValueError("bad destination"),
        retry_at=0,
        max_attempts=10,
        permanent=True,
    )
    assert dead == 1
    assert spool.stats().dead_letter == 1
    terminal = spool.dead_letters()
    assert terminal[0].event_id == _event(0).event_id
    assert terminal[0].error_type == "ValueError"
    assert spool.requeue_dead_letters() == 1
    assert spool.stats().pending == 1
    leased = spool.lease(1, owner="worker", lease_seconds=5)
    spool.reject(
        leased,
        owner="worker",
        error=ValueError("still bad"),
        retry_at=0,
        max_attempts=1,
    )
    assert spool.purge_dead_letters() == 1
    assert spool.stats().total_events == 0
    spool.close()


class _RecordingTransport:
    name = "recording"

    def __init__(self, failures: int = 0, permanent: bool = False) -> None:
        self.failures = failures
        self.permanent = permanent
        self.batches: list[TransportBatch] = []
        self.closed = False

    def send(self, batch: TransportBatch, *, timeout: float) -> None:
        assert timeout > 0
        if self.failures:
            self.failures -= 1
            raise TransportDeliveryError("temporarily unavailable", retryable=not self.permanent)
        self.batches.append(batch)

    def close(self, timeout: float | None = None) -> None:
        del timeout
        self.closed = True


def test_durable_exporter_retries_and_acknowledges_without_loss(tmp_path: Path) -> None:
    transport = _RecordingTransport(failures=1)
    exporter = DurableTransportExporter(
        SqliteEventSpool(tmp_path / "retry.sqlite"),
        transport,
        batch_size=2,
        poll_interval=0.01,
        delivery_timeout=1,
        lease_seconds=2,
        retry_base_delay=0.01,
        retry_max_delay=0.02,
    )
    exporter.emit(_event(0))
    exporter.emit(_event(1))
    assert exporter.flush(2)
    assert exporter.stats.total_events == 0
    delivered = [
        event["eventId"]
        for batch in transport.batches
        for event in json.loads(batch.payload)["events"]
    ]
    assert sorted(delivered) == [f"{1:032x}", f"{2:032x}"]
    assert len(delivered) == len(set(delivered))
    exporter.shutdown(2)
    exporter.shutdown(2)
    assert transport.closed


def test_durable_exporter_keeps_permanent_failures_as_dead_letters(tmp_path: Path) -> None:
    diagnostics = []
    transport = _RecordingTransport(failures=1, permanent=True)
    exporter = DurableTransportExporter(
        SqliteEventSpool(tmp_path / "permanent.sqlite"),
        transport,
        poll_interval=0.01,
        delivery_timeout=1,
        lease_seconds=2,
        on_error=diagnostics.append,
    )
    exporter.emit(_event(0))
    assert not exporter.flush(2)
    assert exporter.stats.dead_letter == 1
    assert exporter.dead_lettered_events == 1
    assert diagnostics and diagnostics[0].operation == "export"
    exporter.shutdown(2)


def test_http_transport_requires_secure_remote_and_valid_ack(tmp_path: Path) -> None:
    received: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            self.send_response(202)
            self.end_headers()

        def log_message(self, _format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    batch = _batch(tmp_path)
    transport = HttpTransport(f"http://127.0.0.1:{server.server_port}/v1/events")
    transport.send(batch, timeout=2)
    server.shutdown()
    server.server_close()
    assert received[0]["batchId"] == batch.batch_id
    with pytest.raises(ValueError, match="requires https"):
        HttpTransport("http://collector.example/v1/events")


class _KafkaProducerFake:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, object]]] = []
        self.callback: Callable[[object | None, object], None] | None = None

    def produce(self, topic: str, **kwargs: object) -> None:
        self.messages.append((topic, kwargs))
        self.callback = kwargs["on_delivery"]  # type: ignore[assignment]

    def poll(self, timeout: float) -> int:
        del timeout
        assert self.callback is not None
        self.callback(None, object())
        return 1

    def flush(self, timeout: float | None = None) -> int:
        del timeout
        return 0


class _RedisFake:
    def __init__(self) -> None:
        self.entries: list[tuple[str, Mapping[str, object]]] = []
        self.closed = False

    def xadd(self, name: str, fields: Mapping[str, object], **kwargs: object) -> str:
        del kwargs
        self.entries.append((name, fields))
        return "1-0"

    def close(self) -> None:
        self.closed = True

class _MqttInfoFake:
    rc = 0

    def __init__(self) -> None:
        self.published = False

    def wait_for_publish(self, timeout: float | None = None) -> None:
        assert timeout and timeout > 0
        self.published = True

    def is_published(self) -> bool:
        return self.published


class _MqttFake:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bytes, int, bool]] = []

    def publish(self, topic: str, payload: bytes, qos: int, retain: bool) -> _MqttInfoFake:
        self.messages.append((topic, payload, qos, retain))
        return _MqttInfoFake()

    def disconnect(self) -> None:
        pass

    def loop_stop(self) -> None:
        pass


class _WebSocketConnection(AbstractContextManager["_WebSocketConnection"]):
    def __init__(self) -> None:
        self.batch_id = ""

    def __enter__(self) -> _WebSocketConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def send(self, payload: bytes) -> None:
        self.batch_id = json.loads(payload)["batchId"]

    def recv(self, timeout: float) -> str:
        assert timeout > 0
        return json.dumps({"batchId": self.batch_id, "accepted": True})


class _NatsFake:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bytes, dict[str, str]]] = []

    async def publish(self, subject: str, payload: bytes, *, headers: dict[str, str]) -> object:
        self.messages.append((subject, payload, headers))
        return object()


def test_kafka_redis_mqtt_websocket_and_nats_ack_contracts(tmp_path: Path) -> None:
    batch = _batch(tmp_path)

    kafka_client = _KafkaProducerFake()
    kafka = KafkaTransport("agent.events", producer=kafka_client)
    kafka.send(batch, timeout=1)
    assert kafka_client.messages[0][0] == "agent.events"
    kafka.close()

    redis_client = _RedisFake()
    redis = RedisStreamsTransport("agent.events", client=redis_client)
    redis.send(batch, timeout=1)
    assert redis_client.entries[0][1]["batch_id"] == batch.batch_id
    redis.close()
    assert redis_client.closed

    mqtt_client = _MqttFake()
    mqtt = MqttTransport("agent/events", client=mqtt_client, qos=2)
    mqtt.send(batch, timeout=1)
    assert mqtt_client.messages[0][2] == 2
    mqtt.close()

    connection = _WebSocketConnection()
    websocket = WebSocketTransport(
        "ws://127.0.0.1:8765/events", connect_factory=lambda *_args, **_kwargs: connection
    )
    websocket.send(batch, timeout=1)

    nats_client = _NatsFake()
    nats = NatsJetStreamTransport("agent.events", jetstream=nats_client)
    nats.send(batch, timeout=1)
    nats.close(1)
    assert nats_client.messages[0][2]["Nats-Msg-Id"] == batch.batch_id


def test_transport_security_rejects_credential_urls_reserved_headers_and_plain_nats() -> None:
    with pytest.raises(ValueError, match="credentials"):
        HttpTransport("https://secret@collector.example/v1/events")
    with pytest.raises(ValueError, match="reserved"):
        HttpTransport(
            "https://collector.example/v1/events",
            headers={"Idempotency-Key": "override"},
        )
    with pytest.raises(ValueError, match="requires TLS"):
        NatsJetStreamTransport(servers=("nats://broker.example:4222",))
    with pytest.raises(ValueError, match="remote Kafka requires"):
        KafkaTransport(
            "events",
            config={"bootstrap.servers": "broker.example:9092"},
            producer=_KafkaProducerFake(),
        )


def test_durable_exporter_reports_transport_close_failure(tmp_path: Path) -> None:
    diagnostics = []

    class CloseFailureTransport(_RecordingTransport):
        def close(self, timeout: float | None = None) -> None:
            del timeout
            raise RuntimeError("close failed")

    exporter = DurableTransportExporter(
        SqliteEventSpool(tmp_path / "close.sqlite"),
        CloseFailureTransport(),
        poll_interval=0.01,
        on_error=diagnostics.append,
    )
    exporter.shutdown(1)
    assert diagnostics and isinstance(diagnostics[-1].error, RuntimeError)

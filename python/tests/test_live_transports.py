"""Operator-run acknowledgement tests against target transport infrastructure."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any, cast

import pytest

from causentra import (
    HttpTransport,
    KafkaTransport,
    MqttTransport,
    NatsJetStreamTransport,
    RedisStreamsTransport,
    TransportBatch,
    WebSocketTransport,
)

pytestmark = pytest.mark.live_transport

_PAYLOAD = (
    b'{"transportVersion":"1.0","batchId":"live-validation","events":[{'
    b'"schemaVersion":"1.0","eventId":"00000000000000000000000000000001",'
    b'"traceId":"00000000000000000000000000000002",'
    b'"spanId":"0000000000000003","sequence":0,'
    b'"timestamp":"2026-07-16T10:00:00.000Z","type":"custom.live",'
    b'"name":"transport-validation","status":"unset",'
    b'"serviceName":"live-validation","attributes":{}}]}'
)
_BATCH = TransportBatch(
    "live-validation",
    ("00000000000000000000000000000001",),
    _PAYLOAD,
)


def test_live_http_acknowledgement() -> None:
    endpoint = _required("CAUSENTRA_LIVE_HTTP_ENDPOINT")
    key = _required("CAUSENTRA_LIVE_HTTP_KEY")
    transport = HttpTransport(
        endpoint,
        headers={"Authorization": f"Bearer {key}"},
    )
    transport.send(_BATCH, timeout=_timeout())


def test_live_websocket_acknowledgement() -> None:
    transport = WebSocketTransport(
        _required("CAUSENTRA_LIVE_WEBSOCKET_URI"),
        headers=_json_object("CAUSENTRA_LIVE_WEBSOCKET_HEADERS", required=False),
    )
    transport.send(_BATCH, timeout=_timeout())


def test_live_kafka_acknowledgement() -> None:
    transport = KafkaTransport(
        _required("CAUSENTRA_LIVE_KAFKA_TOPIC"),
        config=_json_object("CAUSENTRA_LIVE_KAFKA_CONFIG"),
    )
    try:
        transport.send(_BATCH, timeout=_timeout())
    finally:
        transport.close(_timeout())


def test_live_nats_jetstream_acknowledgement() -> None:
    servers = tuple(
        value.strip()
        for value in _required("CAUSENTRA_LIVE_NATS_SERVERS").split(",")
        if value.strip()
    )
    transport = NatsJetStreamTransport(
        _required("CAUSENTRA_LIVE_NATS_SUBJECT"),
        servers=servers,
        connect_options=_json_object("CAUSENTRA_LIVE_NATS_OPTIONS", required=False),
    )
    try:
        transport.send(_BATCH, timeout=_timeout())
    finally:
        transport.close(_timeout())


def test_live_redis_stream_acknowledgement() -> None:
    redis = pytest.importorskip("redis")
    client = redis.Redis.from_url(
        _required("CAUSENTRA_LIVE_REDIS_URL"),
        username=os.environ.get("CAUSENTRA_LIVE_REDIS_USERNAME"),
        password=os.environ.get("CAUSENTRA_LIVE_REDIS_PASSWORD"),
        socket_connect_timeout=_timeout(),
        socket_timeout=_timeout(),
    )
    transport = RedisStreamsTransport(
        _required("CAUSENTRA_LIVE_REDIS_STREAM"),
        client=client,
    )
    try:
        transport.send(_BATCH, timeout=_timeout())
    finally:
        transport.close(_timeout())


def test_live_mqtt_acknowledgement() -> None:
    transport = MqttTransport(
        _required("CAUSENTRA_LIVE_MQTT_TOPIC"),
        host=_required("CAUSENTRA_LIVE_MQTT_HOST"),
        port=int(os.environ.get("CAUSENTRA_LIVE_MQTT_PORT", "8883")),
        qos=int(os.environ.get("CAUSENTRA_LIVE_MQTT_QOS", "1")),
        username=os.environ.get("CAUSENTRA_LIVE_MQTT_USERNAME"),
        password=os.environ.get("CAUSENTRA_LIVE_MQTT_PASSWORD"),
        tls=True,
    )
    try:
        transport.send(_BATCH, timeout=_timeout())
    finally:
        transport.close(_timeout())


def _required(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    if os.environ.get("CAUSENTRA_REQUIRE_LIVE_TRANSPORTS") == "1":
        pytest.fail(f"required live transport setting is missing: {name}")
    pytest.skip(f"live transport setting is not configured: {name}")


def _json_object(name: str, *, required: bool = True) -> Mapping[str, Any]:
    raw = _required(name) if required else os.environ.get(name, "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        pytest.fail(f"{name} must be valid JSON: {error.msg}")
    if not isinstance(value, dict):
        pytest.fail(f"{name} must be a JSON object")
    return cast(dict[str, Any], value)


def _timeout() -> float:
    try:
        value = float(os.environ.get("CAUSENTRA_LIVE_TIMEOUT", "20"))
    except ValueError:
        pytest.fail("CAUSENTRA_LIVE_TIMEOUT must be numeric")
    if value <= 0:
        pytest.fail("CAUSENTRA_LIVE_TIMEOUT must be positive")
    return value

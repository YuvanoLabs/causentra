from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from causentra import (
    CausentraRuntime,
    DurableTransportExporter,
    HttpTransport,
    MemoryExporter,
    SqliteEventSpool,
)
from causentra.collector import (
    ApiPrincipal,
    CollectorConfig,
    CollectorLimits,
    load_collector_config,
    start_collector,
)
from causentra.collector_store import SqliteCollectorStore

PROJECT_KEY = "project-key-000000000000000000000000000000000000000000000000"
OTHER_KEY = "other-key-00000000000000000000000000000000000000000000000000"
OPERATOR_KEY = "operator-key-0000000000000000000000000000000000000000000000"


def _batch() -> tuple[bytes, str, str]:
    exporter = MemoryExporter()
    runtime = CausentraRuntime("http-collector-test", exporter)
    with runtime.trace("workflow") as context, runtime.span("step"):
        pass
    batch_id = hashlib.sha256("\n".join(e.event_id for e in exporter.events).encode()).hexdigest()[
        :32
    ]
    payload = json.dumps(
        {
            "transportVersion": "1.0",
            "batchId": batch_id,
            "events": [event.to_wire() for event in exporter.events],
        },
        separators=(",", ":"),
    ).encode()
    return payload, batch_id, context.trace_id


def _request(
    url: str,
    *,
    method: str = "GET",
    key: str | None = None,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    request_headers = dict(headers or {})
    if key is not None:
        request_headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        url, data=body, method=method, headers=request_headers
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()


def _config(tmp_path: Path, *, limits: CollectorLimits | None = None) -> CollectorConfig:
    return CollectorConfig(
        database_path=tmp_path / "collector.db",
        principals=(
            ApiPrincipal.from_api_key("project", "project-a", PROJECT_KEY),
            ApiPrincipal.from_api_key("other", "project-b", OTHER_KEY),
            ApiPrincipal.from_api_key(
                "operator", "operations", OPERATOR_KEY, operator=True
            ),
        ),
        port=0,
        limits=limits or CollectorLimits(),
    )


def test_collector_http_auth_ingestion_idempotency_queries_and_metrics(
    tmp_path: Path,
) -> None:
    running = start_collector(_config(tmp_path))
    payload, batch_id, trace_id = _batch()
    try:
        status, headers, body = _request(f"{running.url}/health")
        assert status == 200
        assert json.loads(body) == {"status": "ok"}
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert _request(f"{running.url}/ready")[0] == 200

        status, headers, body = _request(
            f"{running.url}/v1/events",
            method="POST",
            body=payload,
            headers={"Content-Type": "application/json", "Idempotency-Key": batch_id},
        )
        assert status == 401
        assert "Bearer" in headers["WWW-Authenticate"]
        assert json.loads(body)["error"]["code"] == "unauthorized"

        status, _, body = _request(
            f"{running.url}/v1/events",
            method="POST",
            key=PROJECT_KEY,
            body=payload,
            headers={"Content-Type": "application/json", "Idempotency-Key": batch_id},
        )
        assert status == 202
        assert json.loads(body) == {
            "batchId": batch_id,
            "accepted": 4,
            "duplicates": 0,
            "replayedBatch": False,
        }
        replay = _request(
            f"{running.url}/v1/events",
            method="POST",
            key=PROJECT_KEY,
            body=payload,
            headers={"Content-Type": "application/json", "Idempotency-Key": batch_id},
        )
        assert replay[0] == 202
        assert json.loads(replay[2])["replayedBatch"] is True

        traces = _request(f"{running.url}/v1/traces", key=PROJECT_KEY)
        assert traces[0] == 200
        assert json.loads(traces[2])["traces"][0]["traceId"] == trace_id
        detail = _request(f"{running.url}/v1/traces/{trace_id}", key=PROJECT_KEY)
        assert detail[0] == 200
        assert len(json.loads(detail[2])["events"]) == 4
        assert _request(f"{running.url}/v1/traces/{trace_id}", key=OTHER_KEY)[0] == 404
        assert _request(f"{running.url}/metrics", key=PROJECT_KEY)[0] == 403
        metrics = _request(f"{running.url}/metrics", key=OPERATOR_KEY)
        assert metrics[0] == 200
        assert b"causentra_collector_accepted_events_total 4" in metrics[2]

        deleted = _request(
            f"{running.url}/v1/traces/{trace_id}", method="DELETE", key=PROJECT_KEY
        )
        assert deleted[0] == 200
        assert json.loads(deleted[2])["deletedEvents"] == 4
    finally:
        running.close()

def test_collector_rejects_invalid_batches_conflicts_limits_and_insecure_bind(
    tmp_path: Path,
) -> None:
    limits = CollectorLimits(max_body_bytes=4_096, requests_per_minute=10)
    running = start_collector(_config(tmp_path, limits=limits))
    payload, batch_id, _ = _batch()
    try:
        wrong_type = _request(
            f"{running.url}/v1/events",
            method="POST",
            key=PROJECT_KEY,
            body=b"{}",
            headers={"Content-Type": "text/plain"},
        )
        assert wrong_type[0] == 415
        too_large = _request(
            f"{running.url}/v1/events",
            method="POST",
            key=PROJECT_KEY,
            body=b"x" * 4_097,
            headers={"Content-Type": "application/json"},
        )
        assert too_large[0] == 413
        accepted = _request(
            f"{running.url}/v1/events",
            method="POST",
            key=PROJECT_KEY,
            body=payload,
            headers={"Content-Type": "application/json", "Idempotency-Key": batch_id},
        )
        assert accepted[0] == 202
        changed = json.loads(payload)
        changed["events"][0]["name"] = "changed"
        conflict = _request(
            f"{running.url}/v1/events",
            method="POST",
            key=PROJECT_KEY,
            body=json.dumps(changed).encode(),
            headers={"Content-Type": "application/json", "Idempotency-Key": batch_id},
        )
        assert conflict[0] == 409
    finally:
        running.close()

    with pytest.raises(ValueError, match="requires TLS"):
        CollectorConfig(
            database_path=tmp_path / "remote.db",
            principals=(ApiPrincipal.from_api_key("p", "project-a", PROJECT_KEY),),
            host="0.0.0.0",
        )


def test_collector_bounds_authentication_attempts_by_remote_identity(tmp_path: Path) -> None:
    running = start_collector(
        _config(tmp_path, limits=CollectorLimits(auth_attempts_per_minute=1))
    )
    try:
        first = _request(f"{running.url}/v1/traces", key="x" * 40)
        second = _request(f"{running.url}/v1/traces", key="y" * 40)
        assert first[0] == 401
        assert second[0] == 429
        assert second[1]["Retry-After"]
    finally:
        running.close()


def test_collector_shutdown_drains_active_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()
    original_ingest = SqliteCollectorStore.ingest

    def slow_ingest(self: SqliteCollectorStore, *args: Any, **kwargs: Any) -> Any:
        entered.set()
        assert release.wait(2)
        return original_ingest(self, *args, **kwargs)

    monkeypatch.setattr(SqliteCollectorStore, "ingest", slow_ingest)
    running = start_collector(_config(tmp_path))
    payload, batch_id, _trace_id = _batch()
    responses: list[int] = []
    request = threading.Thread(
        target=lambda: responses.append(
            _request(
                f"{running.url}/v1/events",
                method="POST",
                key=PROJECT_KEY,
                body=payload,
                headers={
                    "Content-Type": "application/json",
                    "Idempotency-Key": batch_id,
                },
            )[0]
        )
    )
    request.start()
    assert entered.wait(2)
    closed: list[bool] = []
    closer = threading.Thread(target=lambda: (running.close(3), closed.append(True)))
    closer.start()
    time.sleep(0.05)
    assert closer.is_alive()
    release.set()
    request.join(2)
    closer.join(3)
    assert responses == [202]
    assert closed == [True]


def test_collector_config_accepts_hashes_only_and_rejects_unknown_fields(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "collector.json"
    config_path.write_text(
        json.dumps(
            {
                "database": "data/collector.db",
                "listen": {"host": "127.0.0.1", "port": 0},
                "apiKeys": [
                    {
                        "id": "project",
                        "projectId": "project-a",
                        "sha256": hashlib.sha256(PROJECT_KEY.encode()).hexdigest(),
                        "role": "project",
                    }
                ],
                "limits": {"maxBatchEvents": 500},
            }
        ),
        encoding="utf-8",
    )
    config = load_collector_config(config_path)
    assert config.database_path == tmp_path / "data/collector.db"
    assert config.limits.max_batch_events == 500
    assert config.principals[0].key_sha256 != PROJECT_KEY

    value: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    value["listen"]["unknown"] = True
    config_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported listen field"):
        load_collector_config(config_path)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"database":"a.db","database":"b.db"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON field"):
        load_collector_config(duplicate)


def test_durable_http_transport_delivers_end_to_end_to_python_collector(
    tmp_path: Path,
) -> None:
    running = start_collector(_config(tmp_path))
    exporter = DurableTransportExporter(
        SqliteEventSpool(tmp_path / "producer-spool.db"),
        HttpTransport(
            f"{running.url}/v1/events",
            headers={"Authorization": f"Bearer {PROJECT_KEY}"},
        ),
        poll_interval=0.01,
        delivery_timeout=2,
        lease_seconds=3,
    )
    runtime = CausentraRuntime("end-to-end", exporter)
    try:
        with (
            runtime.trace("workflow"),
            runtime.agent("coordinator"),
            runtime.tool("lookup"),
        ):
            pass
        assert runtime.flush(5)
        response = _request(f"{running.url}/v1/traces", key=PROJECT_KEY)
        traces = json.loads(response[2])["traces"]
        assert response[0] == 200
        assert traces[0]["name"] == "workflow"
        assert traces[0]["eventCount"] == 6
    finally:
        runtime.shutdown(5)
        running.close()

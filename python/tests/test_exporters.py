from __future__ import annotations

import json
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from causentra import CausentraRuntime, HttpBatchExporter, MemoryExporter


def test_http_exporter_batches_to_runtime_wire_endpoint() -> None:
    received: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            size = int(self.headers["content-length"])
            received.append(json.loads(self.rfile.read(size)))
            self.send_response(202)
            self.end_headers()

        def log_message(self, _format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    exporter = HttpBatchExporter(f"http://127.0.0.1:{server.server_port}/v1/events", batch_size=10)
    runtime = CausentraRuntime("http-test", exporter)
    with runtime.trace("request"):
        pass
    assert runtime.flush(2.0)
    runtime.shutdown(2.0)
    server.shutdown()
    server.server_close()
    assert len(received) == 1
    assert [event["type"] for event in received[0]["events"]] == ["trace.start", "trace.end"]


def test_http_exporter_is_bounded_and_fail_open() -> None:
    errors = []
    exporter = HttpBatchExporter(
        "http://127.0.0.1:1/v1/events",
        batch_size=100,
        max_queue_size=1,
        request_timeout=0.05,
        max_retries=0,
        flush_interval=10,
        on_error=errors.append,
    )
    runtime = CausentraRuntime("bounded", exporter)
    with runtime.trace("operation"):
        pass
    assert exporter.dropped_events >= 1
    exporter.shutdown(0.2)
    assert errors


def test_http_exporter_secure_defaults_and_invalid_event_containment() -> None:
    with pytest.raises(ValueError, match="requires TLS"):
        HttpBatchExporter("http://collector.example/v1/events")
    with pytest.raises(ValueError, match="credentials"):
        HttpBatchExporter("https://key@collector.example/v1/events")
    with pytest.raises(ValueError, match="reserved"):
        HttpBatchExporter(headers={"Content-Type": "text/plain"})

    memory = MemoryExporter()
    runtime = CausentraRuntime("snapshot", memory)
    with runtime.trace("trace"):
        pass
    invalid = replace(memory.events[0], status="invalid")  # type: ignore[arg-type]
    diagnostics = []
    exporter = HttpBatchExporter(on_error=diagnostics.append)
    exporter.emit(invalid)
    assert exporter.dropped_events == 1
    assert diagnostics
    exporter.shutdown(1)

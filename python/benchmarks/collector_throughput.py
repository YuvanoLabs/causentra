"""Reproducible durable collector benchmark with conservative local gates."""

from __future__ import annotations

import hashlib
import tempfile
import time
from pathlib import Path

from causentra import RuntimeEvent, SqliteCollectorStore


def event(index: int) -> RuntimeEvent:
    return RuntimeEvent(
        schema_version="1.0",
        event_id=f"{index + 1:032x}",
        trace_id=f"{index // 20 + 1:032x}",
        span_id=f"{index + 1:016x}",
        sequence=index % 20,
        timestamp="2026-07-16T10:00:00.000Z",
        type="model.end",
        name="generate",
        status="ok",
        service_name="collector-benchmark",
        attributes={"gen_ai.provider.name": "benchmark", "safe.index": index},
    )


def main() -> None:
    count = 10_000
    batch_size = 100
    with tempfile.TemporaryDirectory(prefix="causentra-collector-benchmark-") as directory:
        store = SqliteCollectorStore(
            Path(directory) / "collector.db",
            max_events=count,
            max_project_events=count,
        )
        events = tuple(event(index) for index in range(count))
        started = time.perf_counter()
        for offset in range(0, count, batch_size):
            batch = events[offset : offset + batch_size]
            batch_id = hashlib.sha256(str(offset).encode()).hexdigest()[:32]
            store.ingest(
                "benchmark",
                batch_id,
                hashlib.sha256(batch_id.encode()).hexdigest(),
                batch,
            )
        elapsed = time.perf_counter() - started
        throughput = count / elapsed
        stats = store.stats("benchmark")
        store.close()
    print(
        f"Python collector: {throughput:.0f} events/s, "
        f"{elapsed:.3f}s total, {stats.payload_bytes} durable bytes"
    )
    if stats.events != count:
        raise SystemExit("collector benchmark lost events")
    if throughput < 1_000:
        raise SystemExit("collector throughput is below the 1,000 events/s local gate")


if __name__ == "__main__":
    main()

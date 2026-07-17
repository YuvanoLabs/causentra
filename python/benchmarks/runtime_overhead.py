"""Reproducible local hot-path benchmark; excludes network delivery."""

from __future__ import annotations

import statistics
import time

from causentra import CausentraRuntime, MemoryExporter


def sample(spans: int = 100) -> float:
    exporter = MemoryExporter()
    runtime = CausentraRuntime("benchmark", exporter)
    started = time.perf_counter()
    with runtime.trace("workflow"):
        for index in range(spans):
            with runtime.tool(f"tool-{index}", attributes={"index": index}):
                pass
    elapsed_ms = (time.perf_counter() - started) * 1_000
    return elapsed_ms / len(exporter.events)


def main() -> None:
    for _ in range(5):
        sample()
    samples = [sample() for _ in range(50)]
    p95 = statistics.quantiles(samples, n=20)[18]
    print(f"Python runtime overhead: median={statistics.median(samples):.4f} ms/event")
    print(f"Python runtime overhead: p95={p95:.4f} ms/event (network excluded)")
    if p95 >= 5.0:
        raise SystemExit("p95 exceeds the 5 ms/event M0 budget")


if __name__ == "__main__":
    main()

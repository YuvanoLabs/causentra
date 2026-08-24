"""Reproducible local deep-trace benchmark; excludes network delivery."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from causentra import CausentraRuntime, LoopDetectionPolicy, MemoryExporter


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def benchmark(iterations: int, *, loop_detection: bool) -> dict[str, Any]:
    exporter = MemoryExporter()
    policy = LoopDetectionPolicy(threshold=3) if loop_detection else None
    runtime = CausentraRuntime("deep-trace-benchmark", exporter, loop_detection=policy)
    latencies: list[float] = []
    started = time.perf_counter_ns()
    with runtime.trace("repeated-operations"):
        for index in range(iterations):
            operation_started = time.perf_counter_ns()
            with runtime.tool("repeat-tool", attributes={"iteration": index}):
                pass
            latencies.append((time.perf_counter_ns() - operation_started) / 1_000_000)
            operation_started = time.perf_counter_ns()
            with runtime.model("repeat-model", attributes={"iteration": index}):
                pass
            latencies.append((time.perf_counter_ns() - operation_started) / 1_000_000)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    operation_count = iterations * 2
    return {
        "loopDetection": loop_detection,
        "operationCount": operation_count,
        "emittedEventCount": len(exporter.events),
        "elapsedMs": round(elapsed_ms, 6),
        "eventsPerSecond": round(len(exporter.events) / (elapsed_ms / 1_000), 3),
        "operationLatencyP50Ms": round(percentile(latencies, 0.50), 6),
        "operationLatencyP95Ms": round(percentile(latencies, 0.95), 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count",
        type=int,
        default=128,
        help="repetitions of each same-name tool/model operation (default: 128)",
    )
    arguments = parser.parse_args()
    if arguments.count < 1:
        parser.error("--count must be positive")
    # Warm the interpreter without including startup effects in the report.
    benchmark(min(arguments.count, 8), loop_detection=False)
    result = {
        "iterationsPerOperation": arguments.count,
        "runs": [
            benchmark(arguments.count, loop_detection=False),
            benchmark(arguments.count, loop_detection=True),
        ],
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

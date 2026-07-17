"""Send a deterministic Python multi-agent trace to the local collector."""

from __future__ import annotations

import os

from causentra import CausentraRuntime, HttpBatchExporter


def main() -> None:
    endpoint = os.environ.get(
        "CAUSENTRA_ENDPOINT", "http://127.0.0.1:4318/v1/events"
    )
    exporter = HttpBatchExporter(endpoint, batch_size=20)
    runtime = CausentraRuntime("python-multi-agent-demo", exporter)
    with runtime.trace("resolve-support-ticket"):
        with runtime.agent("triage"):
            with runtime.model(
                "classify",
                provider_name="anthropic",
                request_model="synthetic-model",
                input_tokens=11,
                output_tokens=4,
            ):
                pass
        with runtime.handoff("triage", "billing"):
            with runtime.tool("lookup-account"):
                pass
    if not runtime.flush(5.0):
        raise RuntimeError("collector did not acknowledge the trace")
    runtime.shutdown(5.0)


if __name__ == "__main__":
    main()

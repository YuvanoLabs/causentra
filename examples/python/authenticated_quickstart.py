"""Emit a privacy-safe multi-agent trace to an authenticated Causentra collector."""

from __future__ import annotations

import os
from pathlib import Path

from causentra import (
    CausentraRuntime,
    DurableTransportExporter,
    HttpTransport,
    SqliteEventSpool,
)


def _collector_key() -> str:
    key_file = Path(os.environ.get("CAUSENTRA_KEY_FILE", ".causentra/collector.key"))
    try:
        key = key_file.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(
            f"cannot read collector key file {key_file}; run `causentra init` first"
        ) from error
    if not key:
        raise RuntimeError(f"collector key file {key_file} is empty")
    return key


def main() -> None:
    endpoint = os.environ.get(
        "CAUSENTRA_ENDPOINT", "http://127.0.0.1:4318/v1/events"
    )
    spool = Path(os.environ.get("CAUSENTRA_SPOOL", ".causentra/onboarding-spool.db"))
    exporter = DurableTransportExporter(
        SqliteEventSpool(spool),
        HttpTransport(
            endpoint,
            headers={"Authorization": f"Bearer {_collector_key()}"},
        ),
        poll_interval=0.05,
        delivery_timeout=3.0,
        lease_seconds=5.0,
    )
    runtime = CausentraRuntime("onboarding-demo", exporter)
    try:
        with runtime.trace("resolve-support-ticket"):
            with runtime.agent("triage"):
                with runtime.model(
                    "classify",
                    provider_name="openai",
                    request_model="example-model",
                    input_tokens=12,
                    output_tokens=4,
                ):
                    pass
            with runtime.handoff("triage", "billing"):
                with runtime.tool("lookup-account"):
                    pass
        if not runtime.flush(5.0):
            raise RuntimeError("collector did not acknowledge the trace within five seconds")
    finally:
        runtime.shutdown(5.0)

    print("Causentra quickstart trace delivered.")


if __name__ == "__main__":
    main()

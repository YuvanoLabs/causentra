"""Production-oriented durable producer for an authenticated Causentra collector.

The example emits synthetic lifecycle facts only. Replace the marked blocks with
application work; never pass prompts, responses, tool payloads, keys, or raw
exception messages to Causentra.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from causentra import (
    CausentraRuntime,
    DurableTransportExporter,
    HttpTransport,
    SqliteEventSpool,
)


def _project_key() -> str:
    """Read the project key from an operator-provided secret file."""

    try:
        value = Path(os.environ["CAUSENTRA_KEY_FILE"]).read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError("CAUSENTRA_KEY_FILE could not be read") from error
    if not 32 <= len(value) <= 512:
        raise RuntimeError("collector project key must contain 32 to 512 characters")
    return value


def _endpoint() -> str:
    """Validate that remote delivery uses HTTPS and has no embedded credentials."""

    value = os.environ["CAUSENTRA_ENDPOINT"]
    parsed = urlparse(value)
    if parsed.path != "/v1/events" or parsed.query or parsed.fragment:
        raise RuntimeError("CAUSENTRA_ENDPOINT must end in /v1/events")
    if parsed.username or parsed.password or not parsed.hostname:
        raise RuntimeError("CAUSENTRA_ENDPOINT must not embed credentials")
    loopback = parsed.hostname.lower() == "localhost" or parsed.hostname.startswith("127.")
    if parsed.scheme not in {"http", "https"} or (not loopback and parsed.scheme != "https"):
        raise RuntimeError("a remote CAUSENTRA_ENDPOINT must use HTTPS")
    return value


def _process_ticket(runtime: CausentraRuntime) -> None:
    """Instrument an application operation without recording application content."""

    with runtime.trace("resolve-support-ticket"):
        with runtime.agent("triage"):
            with runtime.model(
                "classify", provider_name="openai", request_model="deployment-model-id"
            ):
                # Call the application's model client here.
                pass
        with runtime.handoff("triage", "billing"):
            with runtime.tool("lookup-account"):
                # Call the application's business operation here.
                pass


def main() -> int:
    """Durably emit one synthetic operation and drain delivery before exit."""

    exporter = DurableTransportExporter(
        SqliteEventSpool(Path(os.environ.get("CAUSENTRA_SPOOL", ".causentra/outbox.db"))),
        HttpTransport(_endpoint(), headers={"Authorization": f"Bearer {_project_key()}"}),
        batch_size=100,
        delivery_timeout=10.0,
        lease_seconds=30.0,
    )
    runtime = CausentraRuntime(os.environ.get("CAUSENTRA_SERVICE", "support-service"), exporter)
    try:
        _process_ticket(runtime)
        if not runtime.flush(10.0):
            print("Causentra has pending or dead-lettered delivery work", file=sys.stderr)
            return 1
        return 0
    finally:
        runtime.shutdown(10.0)


if __name__ == "__main__":
    raise SystemExit(main())

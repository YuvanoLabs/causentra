"""Production-oriented durable producer example for an authenticated collector.

This example intentionally emits only synthetic lifecycle facts. Replace the
``process_ticket`` body with application work; do not pass prompts, model
responses, tool arguments, credentials, or exception messages to Causentra.
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


def _read_project_key() -> str:
    """Read the project key from a secret file without logging its value."""

    key_path = Path(os.environ["CAUSENTRA_KEY_FILE"])
    try:
        key = key_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError("CAUSENTRA_KEY_FILE could not be read") from error
    if not 32 <= len(key) <= 512:
        raise RuntimeError("collector project key must contain 32 to 512 characters")
    return key


def _collector_endpoint() -> str:
    """Return a valid collector ingestion URL, requiring TLS off loopback."""

    endpoint = os.environ["CAUSENTRA_ENDPOINT"]
    parsed = urlparse(endpoint)
    if parsed.path != "/v1/events" or parsed.query or parsed.fragment:
        raise RuntimeError("CAUSENTRA_ENDPOINT must be an origin ending in /v1/events")
    if parsed.username or parsed.password or not parsed.hostname:
        raise RuntimeError("CAUSENTRA_ENDPOINT must not embed credentials")
    is_loopback = parsed.hostname.lower() == "localhost" or parsed.hostname.startswith("127.")
    if parsed.scheme not in {"http", "https"} or (not is_loopback and parsed.scheme != "https"):
        raise RuntimeError("a remote CAUSENTRA_ENDPOINT must use HTTPS")
    return endpoint


def process_ticket(runtime: CausentraRuntime) -> None:
    """Instrument an application operation without capturing application content."""

    with runtime.trace("resolve-support-ticket"):
        with runtime.agent("triage"):
            with runtime.model(
                "classify",
                provider_name="openai",
                request_model="deployment-model-id",
            ):
                # Call the application's model client here.
                pass
        with runtime.handoff("triage", "billing"):
            with runtime.tool("lookup-account"):
                # Call the application's business operation here.
                pass


def main() -> int:
    """Emit one synthetic operation and durably drain it before exit."""

    spool_path = Path(os.environ.get("CAUSENTRA_SPOOL", ".causentra/producer-spool.db"))
    exporter = DurableTransportExporter(
        SqliteEventSpool(spool_path),
        HttpTransport(
            _collector_endpoint(),
            headers={"Authorization": f"Bearer {_read_project_key()}"},
        ),
        batch_size=100,
        delivery_timeout=10.0,
        lease_seconds=30.0,
    )
    runtime = CausentraRuntime(os.environ.get("CAUSENTRA_SERVICE", "support-service"), exporter)
    try:
        process_ticket(runtime)
        if not runtime.flush(10.0):
            print("Causentra has pending or dead-lettered delivery work", file=sys.stderr)
            return 1
        return 0
    finally:
        runtime.shutdown(10.0)


if __name__ == "__main__":
    raise SystemExit(main())

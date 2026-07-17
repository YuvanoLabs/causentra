from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from causentra import (
    ApiPrincipal,
    CausentraRuntime,
    CollectorConfig,
    DurableTransportExporter,
    HttpTransport,
    SqliteEventSpool,
    load_collector_config,
    start_collector,
)
from causentra.cli import main

_KEY = "cli-project-key-material-that-is-long-enough-0001"


def test_cli_initializes_secret_separately_and_operates_local_store(tmp_path: Path) -> None:
    config_path = tmp_path / "collector.json"
    key_path = tmp_path / "collector.key"
    assert main(
        [
            "init",
            "--config",
            str(config_path),
            "--key-output",
            str(key_path),
            "--project",
            "example_project",
            "--database",
            str(tmp_path / "collector.db"),
            "--port",
            "0",
        ]
    ) == 0
    key = key_path.read_text(encoding="utf-8").strip()
    config = load_collector_config(config_path)
    assert config.principals[0].project_id == "example_project"
    assert config.principals[0].key_sha256 == hashlib.sha256(key.encode()).hexdigest()
    assert key not in config_path.read_text(encoding="utf-8")
    assert main(["backup", "--config", str(config_path), "--output", str(tmp_path / "b.db")]) == 0
    assert (tmp_path / "b.db").is_file()
    assert main(
        [
            "prune-idempotency",
            "--config",
            str(config_path),
            "--older-than-days",
            "1",
        ]
    ) == 0
    assert main(["init", "--config", str(config_path), "--key-output", str(key_path)]) == 1


def test_cli_checks_auth_reads_and_safely_deletes_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    running = start_collector(
        CollectorConfig(
            database_path=tmp_path / "collector.db",
            principals=(ApiPrincipal.from_api_key("cli", "project-a", _KEY),),
            port=0,
        )
    )
    key_path = tmp_path / "project.key"
    key_path.write_text(_KEY, encoding="utf-8")
    exporter = DurableTransportExporter(
        SqliteEventSpool(tmp_path / "spool.db"),
        HttpTransport(
            f"{running.url}/v1/events",
            headers={"Authorization": f"Bearer {_KEY}"},
        ),
        poll_interval=0.005,
    )
    runtime = CausentraRuntime("cli-test", exporter)
    with runtime.trace("cli-trace"):
        pass
    assert runtime.flush(2)
    runtime.shutdown(2)

    base = ["--url", running.url, "--key-file", str(key_path)]
    assert main([*base, "doctor"]) == 0
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["ready"]["status"] == "ready"
    assert doctor["authentication"]["status"] == "ok"

    assert main([*base, "traces", "--limit", "1"]) == 0
    traces = json.loads(capsys.readouterr().out)["traces"]
    trace_id = traces[0]["traceId"]
    assert main([*base, "trace", trace_id]) == 0
    detail = json.loads(capsys.readouterr().out)
    assert detail["traceId"] == trace_id
    assert main([*base, "delete", trace_id, "--confirm", "0" * 32]) == 1
    capsys.readouterr()
    assert main([*base, "delete", trace_id, "--confirm", trace_id]) == 0
    deleted = json.loads(capsys.readouterr().out)
    assert deleted["deletedEvents"] == 2
    running.close()


def test_cli_refuses_plaintext_remote_origin(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--url", "http://collector.example", "doctor"]) == 1
    assert "requires HTTPS" in capsys.readouterr().err

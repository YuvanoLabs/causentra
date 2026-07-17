from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from causentra import ApiPrincipal, CollectorConfig, CollectorLimits, start_collector

_KEY = "onboarding-project-key-material-that-is-long-enough-0001"


def test_authenticated_quickstart_delivers_a_trace(tmp_path: Path) -> None:
    config = CollectorConfig(
        database_path=tmp_path / "collector.db",
        host="127.0.0.1",
        port=0,
        allow_insecure_remote=False,
        principals=(ApiPrincipal.from_api_key("onboarding", "local_project", _KEY),),
        limits=CollectorLimits(),
        tls_certificate=None,
        tls_private_key=None,
    )
    key_file = tmp_path / "collector.key"
    key_file.write_text(_KEY + "\n", encoding="utf-8")
    collector = start_collector(config)
    environment = {
        **os.environ,
        "CAUSENTRA_ENDPOINT": f"{collector.url}/v1/events",
        "CAUSENTRA_KEY_FILE": str(key_file),
        "CAUSENTRA_SPOOL": str(tmp_path / "producer-spool.db"),
    }
    example = Path(__file__).parents[2] / "examples" / "python" / "authenticated_quickstart.py"
    try:
        completed = subprocess.run(
            [sys.executable, str(example)],
            check=False,
            capture_output=True,
            env=environment,
            text=True,
            timeout=15,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == "Causentra quickstart trace delivered."
        request = urllib.request.Request(
            f"{collector.url}/v1/traces",
            headers={"Authorization": f"Bearer {_KEY}"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            traces = json.loads(response.read())["traces"]
        assert len(traces) == 1
        assert traces[0]["serviceName"] == "onboarding-demo"
    finally:
        collector.close()

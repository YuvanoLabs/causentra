"""Build-gate smoke test for the wheel in an isolated virtual environment."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    python_root = Path(__file__).parents[1]
    wheels = sorted((python_root / "dist").glob("causentra-*.whl"))
    if not wheels:
        raise SystemExit("no wheel found; run python:build first")
    clean_environment = os.environ.copy()
    clean_environment.pop("PYTHONHOME", None)
    clean_environment.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(prefix="causentra-wheel-") as directory:
        environment = Path(directory)
        subprocess.run(
            [sys.executable, "-m", "venv", str(environment)],
            check=True,
            env=clean_environment,
        )
        interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(
            [
                str(interpreter),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--force-reinstall",
                "--no-deps",
                str(wheels[-1]),
            ],
            check=True,
            env=clean_environment,
        )
        smoke = """
from causentra import CausentraRuntime, MemoryExporter
exporter = MemoryExporter()
runtime = CausentraRuntime('clean-wheel', exporter)
with runtime.trace('smoke'):
    with runtime.agent('worker'):
        pass
assert [event.type for event in exporter.events] == [
    'trace.start', 'agent.start', 'agent.end', 'trace.end'
]
print('clean wheel: PASS')
"""
        subprocess.run([str(interpreter), "-c", smoke], check=True, env=clean_environment)
        cli = environment / ("Scripts/causentra.exe" if os.name == "nt" else "bin/causentra")
        help_result = subprocess.run(
            [str(cli), "--help"],
            check=True,
            capture_output=True,
            env=clean_environment,
            text=True,
        )
        if "Operate the authenticated Causentra Python collector" not in help_result.stdout:
            raise SystemExit("clean wheel CLI entry point did not return expected help")


if __name__ == "__main__":
    main()

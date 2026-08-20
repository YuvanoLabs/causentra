from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from causentra import EventEngine, RuntimeEvent
from causentra.plugins import (
    PLUGIN_API_VERSION,
    PluginEngine,
    PluginManifest,
    PluginPolicy,
    PluginPolicyError,
    PluginRuntime,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ack_plugin.py"


def _event(index: int = 0) -> RuntimeEvent:
    return RuntimeEvent(
        schema_version="1.0",
        event_id=f"{index + 1:032x}",
        trace_id="a" * 32,
        span_id="b" * 16,
        sequence=index,
        timestamp="2026-07-16T10:00:00.000Z",
        type="model.end",
        name="generate",
        status="ok",
        service_name="plugin-test",
        attributes={"safe": "metadata", "password": "[REDACTED]"},
    )


def _manifest(tmp_path: Path, *, attributes: bool = False) -> PluginManifest:
    del tmp_path
    permissions = {"secrets"}
    if attributes:
        permissions.add("event.attributes")
    return PluginManifest(
        plugin_id="example.capture",
        version="1.0.0",
        root=FIXTURE.parent.resolve(),
        entrypoint=(sys.executable, str(FIXTURE)),
        event_types=("model.*",),
        permissions=frozenset(permissions),
        environment=("CAPTURE_PATH",),
        integrity=((FIXTURE.name, hashlib.sha256(FIXTURE.read_bytes()).hexdigest()),),
    )


def _policy(tmp_path: Path, *, attributes: bool = False) -> PluginPolicy:
    permissions = {"secrets"}
    if attributes:
        permissions.add("event.attributes")
    return PluginPolicy(
        allowed_permissions=frozenset(permissions),
        allowed_executables=frozenset({Path(sys.executable).resolve()}),
        environment={"CAPTURE_PATH": str(tmp_path / "captured.jsonl")},
        trusted_plugin_ids=frozenset({"example.capture"}),
    )


def test_plugin_engine_routes_out_of_process_and_strips_attributes_by_default(
    tmp_path: Path,
) -> None:
    event_engine = EventEngine(tmp_path / "events.db", worker_count=1, poll_interval=0.005)
    plugin = PluginRuntime(_manifest(tmp_path), policy=_policy(tmp_path))
    plugins = PluginEngine(event_engine)
    plugins.register(plugin)
    event_engine.publish(_event())
    assert event_engine.flush(5)
    plugins.close()
    event_engine.shutdown(2)
    captured = json.loads((tmp_path / "captured.jsonl").read_text(encoding="utf-8"))
    assert captured["eventId"] == _event().event_id
    assert captured["attributes"] == {}


def test_plugin_attributes_require_manifest_and_operator_grants(tmp_path: Path) -> None:
    with pytest.raises(PluginPolicyError, match="not explicitly trusted"):
        PluginRuntime(_manifest(tmp_path), policy=PluginPolicy())
    with pytest.raises(PluginPolicyError, match=r"event\.attributes"):
        PluginRuntime(_manifest(tmp_path, attributes=True), policy=_policy(tmp_path))

    plugin = PluginRuntime(
        _manifest(tmp_path, attributes=True), policy=_policy(tmp_path, attributes=True)
    )
    plugin.handle(_event())
    plugin.close()
    captured = json.loads((tmp_path / "captured.jsonl").read_text(encoding="utf-8"))
    assert captured["attributes"]["safe"] == "metadata"
    assert captured["attributes"]["password"] == "[REDACTED]"


def test_plugin_manifest_loader_is_strict_and_resolves_entrypoint(tmp_path: Path) -> None:
    executable = tmp_path / "plugin.exe"
    executable.touch()
    manifest_path = tmp_path / "plugin.json"
    manifest_path.write_text(
        json.dumps(
            {
                "apiVersion": PLUGIN_API_VERSION,
                "id": "example.strict",
                "version": "1.2.3",
                "entrypoint": ["plugin.exe"],
                "subscriptions": {"eventTypes": ["tool.*"]},
                "permissions": [],
                "environment": [],
                "integrity": {
                    "plugin.exe": hashlib.sha256(executable.read_bytes()).hexdigest()
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = PluginManifest.load(manifest_path)
    assert manifest.entrypoint[0] == str(executable.resolve())
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    value["unexpected"] = True
    manifest_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        PluginManifest.load(manifest_path)

    manifest_path.write_text(
        '{"apiVersion":"causentra.io/plugin/v1","id":"example.one",'
        '"id":"example.two"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON field"):
        PluginManifest.load(manifest_path)


def test_plugin_integrity_is_reverified_before_process_start(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    corrupted = PluginManifest(
        plugin_id=manifest.plugin_id,
        version=manifest.version,
        root=manifest.root,
        entrypoint=manifest.entrypoint,
        event_types=manifest.event_types,
        permissions=manifest.permissions,
        environment=manifest.environment,
        integrity=((FIXTURE.name, "0" * 64),),
    )
    plugin = PluginRuntime(corrupted, policy=_policy(tmp_path))
    with pytest.raises(PluginPolicyError, match="integrity verification failed"):
        plugin.handle(_event())


def test_plugin_integrity_must_cover_entrypoint_artifacts(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    uncovered = PluginManifest(
        plugin_id=manifest.plugin_id,
        version=manifest.version,
        root=manifest.root,
        entrypoint=manifest.entrypoint,
        event_types=manifest.event_types,
        permissions=manifest.permissions,
        environment=manifest.environment,
        integrity=(("__init__.py", hashlib.sha256(b"").hexdigest()),),
    )
    with pytest.raises(PluginPolicyError, match="entrypoint artifact"):
        PluginRuntime(uncovered, policy=_policy(tmp_path))

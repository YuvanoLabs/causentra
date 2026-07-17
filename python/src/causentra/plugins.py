"""Versioned, out-of-process community plugin SDK and host."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import subprocess
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO, cast

from .event_engine import EventEngine, NonRetryableEventError, RetryPolicy
from .types import RuntimeEvent

PLUGIN_API_VERSION = "causentra.io/plugin/v1"
_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$")
_VERSION = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PERMISSIONS = frozenset({"event.attributes", "network", "secrets"})


class PluginError(RuntimeError):
    """Base class for plugin configuration and protocol failures."""


class PluginPolicyError(PluginError):
    """A plugin requested authority not granted by operator policy."""


class PluginProtocolError(PluginError):
    """A plugin violated the bounded JSON-lines protocol."""


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """Strict v1 plugin identity, routing, process, and permission declaration."""

    plugin_id: str
    version: str
    root: Path
    entrypoint: tuple[str, ...]
    event_types: tuple[str, ...]
    services: tuple[str, ...] = ()
    permissions: frozenset[str] = frozenset()
    environment: tuple[str, ...] = ()
    integrity: tuple[tuple[str, str], ...] = ()
    api_version: str = PLUGIN_API_VERSION

    def __post_init__(self) -> None:
        if self.api_version != PLUGIN_API_VERSION:
            raise ValueError(f"api_version must equal {PLUGIN_API_VERSION}")
        if not _PLUGIN_ID.fullmatch(self.plugin_id):
            raise ValueError("plugin_id must be a dot-namespaced lowercase identifier")
        if not _VERSION.fullmatch(self.version):
            raise ValueError("version must be a stable semantic version")
        if not self.root.is_absolute():
            raise ValueError("plugin root must be absolute")
        if not self.root.is_dir():
            raise ValueError("plugin root must be an existing directory")
        if not self.entrypoint:
            raise ValueError("plugin entrypoint cannot be empty")
        if len(self.entrypoint) > 64 or any(
            not value or len(value) > 4_096 for value in self.entrypoint
        ):
            raise ValueError("plugin entrypoint must contain 1-64 bounded arguments")
        if not self.event_types:
            raise ValueError("plugin event_types cannot be empty")
        unknown = self.permissions - _PERMISSIONS
        if unknown:
            raise ValueError(f"unsupported plugin permission: {sorted(unknown)[0]}")
        if self.environment and "secrets" not in self.permissions:
            raise ValueError("plugins declaring environment values require secrets permission")
        for value in (*self.event_types, *self.services, *self.environment):
            if not value or len(value) > 256:
                raise ValueError("plugin routing and environment values must be 1-256 characters")
        for name in self.environment:
            if not name.replace("_", "A").isalnum() or not name[0].isalpha():
                raise ValueError(f"invalid plugin environment name: {name}")
        if len(set(self.environment)) != len(self.environment):
            raise ValueError("plugin environment names must be unique")
        if len({relative for relative, _digest in self.integrity}) != len(self.integrity):
            raise ValueError("plugin integrity paths must be unique")
        for relative, digest in self.integrity:
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts or not relative:
                raise ValueError("plugin integrity paths must remain inside the plugin root")
            if not _SHA256.fullmatch(digest):
                raise ValueError("plugin integrity values must be lowercase SHA-256 digests")

    @classmethod
    def load(cls, path: str | Path) -> PluginManifest:
        """Load a strict manifest and resolve relative entrypoint paths."""

        source = Path(path).resolve()
        if not source.is_file() or source.stat().st_size > 1024 * 1024:
            raise ValueError("plugin manifest must be an existing file of at most 1 MiB")
        try:
            value = json.loads(
                source.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_json_object,
            )
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as error:
            raise ValueError("plugin manifest must be valid UTF-8 JSON") from error
        if not isinstance(value, dict):
            raise ValueError("plugin manifest must be an object")
        allowed = {
            "apiVersion",
            "id",
            "version",
            "entrypoint",
            "subscriptions",
            "permissions",
            "environment",
            "integrity",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unsupported plugin manifest field: {sorted(unknown)[0]}")
        subscriptions = _object(value.get("subscriptions"), "subscriptions")
        if set(subscriptions) - {"eventTypes", "services"}:
            raise ValueError("subscriptions contains an unsupported field")
        entrypoint = _string_list(value.get("entrypoint"), "entrypoint")
        integrity_value = _object(value.get("integrity"), "integrity")
        integrity = tuple(
            sorted(
                (
                    _string(relative, "integrity path"),
                    _string(digest, "integrity digest"),
                )
                for relative, digest in integrity_value.items()
            )
        )
        resolved_entrypoint = list(entrypoint)
        if entrypoint and not Path(entrypoint[0]).is_absolute():
            resolved_entrypoint[0] = str((source.parent / entrypoint[0]).resolve())
        return cls(
            plugin_id=_string(value.get("id"), "id"),
            version=_string(value.get("version"), "version"),
            root=source.parent,
            entrypoint=tuple(resolved_entrypoint),
            event_types=_string_list(subscriptions.get("eventTypes"), "eventTypes"),
            services=_string_list(subscriptions.get("services", []), "services"),
            permissions=frozenset(
                _string_list(value.get("permissions", []), "permissions")
            ),
            environment=_string_list(value.get("environment", []), "environment"),
            integrity=integrity,
            api_version=_string(value.get("apiVersion"), "apiVersion"),
        )


@dataclass(frozen=True, slots=True)
class PluginPolicy:
    """Explicit operator grants; default policy supplies no sensitive authority."""

    allowed_permissions: frozenset[str] = frozenset()
    allowed_executables: frozenset[Path] = frozenset()
    environment: Mapping[str, str] = field(default_factory=dict)
    trusted_plugin_ids: frozenset[str] = frozenset()
    require_integrity: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))
        unknown = self.allowed_permissions - _PERMISSIONS
        if unknown:
            raise ValueError(f"unsupported policy permission: {sorted(unknown)[0]}")
        for executable in self.allowed_executables:
            if not executable.is_absolute():
                raise ValueError("allowed executable paths must be absolute")
        if not isinstance(self.require_integrity, bool):
            raise ValueError("require_integrity must be a boolean")


class PluginRuntime:
    """Supervise one serialized, bounded JSON-lines plugin process."""

    def __init__(
        self,
        manifest: PluginManifest,
        *,
        policy: PluginPolicy | None = None,
        startup_timeout: float = 5.0,
        delivery_timeout: float = 10.0,
        shutdown_timeout: float = 3.0,
        max_response_bytes: int = 64 * 1024,
    ) -> None:
        self.manifest = manifest
        self.policy = policy or PluginPolicy()
        self._startup_timeout = _positive(startup_timeout, "startup_timeout")
        self._delivery_timeout = _positive(delivery_timeout, "delivery_timeout")
        self._shutdown_timeout = _positive(shutdown_timeout, "shutdown_timeout")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._max_response_bytes = max_response_bytes
        self._process: subprocess.Popen[bytes] | None = None
        self._responses: queue.Queue[bytes | BaseException | None] = queue.Queue(maxsize=8)
        self._reader: threading.Thread | None = None
        self._lock = threading.RLock()
        self._closed = False
        self._validate_policy()

    def handle(self, event: RuntimeEvent) -> None:
        """Deliver one event or raise for EventEngine retry/dead-letter handling."""

        with self._lock:
            if self._closed:
                raise PluginError("plugin runtime is closed")
            self._ensure_started()
            delivery_id = secrets.token_hex(16)
            self._write(
                {
                    "type": "event",
                    "protocolVersion": "1.0",
                    "deliveryId": delivery_id,
                    "event": self._event_payload(event),
                }
            )
            response = self._read(self._delivery_timeout)
            if (
                response.get("type") != "ack"
                or response.get("deliveryId") != delivery_id
                or not isinstance(response.get("accepted"), bool)
            ):
                self._terminate()
                raise PluginProtocolError("plugin returned an invalid acknowledgement")
            if response["accepted"] is not True:
                retryable = response.get("retryable") is True
                if retryable:
                    raise PluginError("plugin temporarily rejected the event")
                raise NonRetryableEventError("plugin permanently rejected the event")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            process = self._process
            if process is None:
                return
            try:
                self._write({"type": "shutdown", "protocolVersion": "1.0"})
                process.wait(self._shutdown_timeout)
            except (PluginError, subprocess.TimeoutExpired):
                self._terminate()
            finally:
                self._process = None

    def _ensure_started(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self._verify_integrity()
        self._responses = queue.Queue(maxsize=8)
        environment = _minimal_environment()
        for name in self.manifest.environment:
            environment[name] = self.policy.environment[name]
        self._process = subprocess.Popen(
            self.manifest.entrypoint,
            cwd=self.manifest.root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        assert self._process.stdout is not None
        self._reader = threading.Thread(
            target=self._read_responses,
            args=(self._process.stdout, self._responses),
            name=f"causentra-plugin-{self.manifest.plugin_id}",
            daemon=True,
        )
        self._reader.start()
        self._write(
            {
                "type": "initialize",
                "protocolVersion": "1.0",
                "pluginId": self.manifest.plugin_id,
                "pluginVersion": self.manifest.version,
                "permissions": sorted(self.manifest.permissions),
            }
        )
        response = self._read(self._startup_timeout)
        if response != {"type": "ready", "protocolVersion": "1.0"}:
            self._terminate()
            raise PluginProtocolError("plugin initialization handshake failed")

    def _event_payload(self, event: RuntimeEvent) -> dict[str, Any]:
        payload = event.to_wire()
        if "event.attributes" not in self.manifest.permissions:
            payload["attributes"] = {}
        return payload

    def _write(self, value: Mapping[str, Any]) -> None:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise PluginError("plugin process is unavailable")
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
        try:
            process.stdin.write(encoded)
            process.stdin.flush()
        except OSError as error:
            self._terminate()
            raise PluginError("plugin process input failed") from error

    def _read(self, timeout: float) -> dict[str, Any]:
        try:
            value = self._responses.get(timeout=timeout)
        except queue.Empty as error:
            self._terminate()
            raise TimeoutError("plugin response timed out") from error
        if value is None:
            self._terminate()
            raise PluginError("plugin process exited before responding")
        if isinstance(value, BaseException):
            self._terminate()
            raise PluginProtocolError("plugin output violated the protocol") from value
        try:
            decoded = json.loads(value, object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError) as error:
            self._terminate()
            raise PluginProtocolError("plugin output was not UTF-8 JSON") from error
        if not isinstance(decoded, dict):
            self._terminate()
            raise PluginProtocolError("plugin response must be an object")
        return cast(dict[str, Any], decoded)

    def _read_responses(
        self,
        stream: BinaryIO,
        responses: queue.Queue[bytes | BaseException | None],
    ) -> None:
        while True:
            try:
                line = stream.readline(self._max_response_bytes + 1)
                if not line:
                    self._put_response(responses, None)
                    return
                if len(line) > self._max_response_bytes or not line.endswith(b"\n"):
                    self._put_response(
                        responses, PluginProtocolError("plugin response exceeded limit")
                    )
                    return
                self._put_response(responses, line)
            except BaseException as error:
                self._put_response(responses, error)
                return

    @staticmethod
    def _put_response(
        responses: queue.Queue[bytes | BaseException | None],
        value: bytes | BaseException | None,
    ) -> None:
        try:
            responses.put_nowait(value)
        except queue.Full:
            return

    def _terminate(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(self._shutdown_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(self._shutdown_timeout)

    def _validate_policy(self) -> None:
        if self.manifest.plugin_id not in self.policy.trusted_plugin_ids:
            raise PluginPolicyError("plugin ID was not explicitly trusted by operator policy")
        if self.policy.require_integrity and not self.manifest.integrity:
            raise PluginPolicyError("plugin manifest must declare integrity hashes")
        denied = self.manifest.permissions - self.policy.allowed_permissions
        if denied:
            raise PluginPolicyError(f"plugin permission was not granted: {sorted(denied)[0]}")
        missing_environment = set(self.manifest.environment) - set(self.policy.environment)
        if missing_environment:
            raise PluginPolicyError(
                f"plugin environment was not supplied: {sorted(missing_environment)[0]}"
            )
        executable = Path(self.manifest.entrypoint[0]).resolve()
        if not executable.is_file():
            raise PluginPolicyError("plugin executable does not exist or is not a file")
        inside_root = _is_relative_to(executable, self.manifest.root.resolve())
        explicitly_allowed = executable in {
            path.resolve() for path in self.policy.allowed_executables
        }
        if not inside_root and not explicitly_allowed:
            raise PluginPolicyError(
                "plugin executable must be inside its root or explicitly allowlisted"
            )
        covered = {
            (self.manifest.root / relative).resolve()
            for relative, _digest in self.manifest.integrity
        }
        entrypoint_artifacts = {executable} if inside_root else set()
        for argument in self.manifest.entrypoint[1:]:
            candidate = Path(argument)
            candidate = candidate.resolve() if candidate.is_absolute() else (
                self.manifest.root / candidate
            ).resolve()
            if _is_relative_to(candidate, self.manifest.root.resolve()) and (
                Path(argument).is_absolute() or candidate.is_file()
            ):
                entrypoint_artifacts.add(candidate)
        if self.policy.require_integrity and not entrypoint_artifacts.issubset(covered):
            raise PluginPolicyError("every plugin entrypoint artifact requires an integrity hash")

    def _verify_integrity(self) -> None:
        for relative, expected in self.manifest.integrity:
            artifact = (self.manifest.root / relative).resolve()
            if (
                not _is_relative_to(artifact, self.manifest.root.resolve())
                or not artifact.is_file()
            ):
                raise PluginPolicyError("plugin integrity artifact is missing or outside its root")
            if artifact.stat().st_size > 100 * 1024 * 1024:
                raise PluginPolicyError("plugin integrity artifact exceeds 100 MiB")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            if not hmac.compare_digest(digest, expected):
                raise PluginPolicyError("plugin integrity verification failed")


class PluginEngine:
    """Register supervised plugin runtimes as durable EventEngine subscriptions."""

    def __init__(self, event_engine: EventEngine) -> None:
        self._event_engine = event_engine
        self._plugins: dict[str, PluginRuntime] = {}
        self._lock = threading.RLock()

    def register(
        self, plugin: PluginRuntime, *, retry: RetryPolicy | None = None
    ) -> None:
        with self._lock:
            plugin_id = plugin.manifest.plugin_id
            if plugin_id in self._plugins:
                raise ValueError(f"plugin is already registered: {plugin_id}")
            self._event_engine.subscribe(
                f"plugin:{plugin_id}",
                plugin.handle,
                event_types=plugin.manifest.event_types,
                services=plugin.manifest.services,
                retry=retry,
            )
            self._plugins[plugin_id] = plugin

    def close(self) -> None:
        with self._lock:
            plugins = tuple(self._plugins.values())
            self._plugins.clear()
        for plugin in plugins:
            plugin.close()


def _minimal_environment() -> dict[str, str]:
    result = {"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    for name in ("SYSTEMROOT", "WINDIR"):
        value = os.environ.get(name)
        if value:
            result[name] = value
    return result


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _string_list(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be an array of strings")
    return tuple(value)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _positive(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)

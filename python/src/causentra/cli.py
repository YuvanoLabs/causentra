"""Safe operator CLI for the authenticated Python collector."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import secrets
import stat
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from .collector import CollectorConfig, load_collector_config
from .collector_store import SqliteCollectorStore

_MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class CliError(RuntimeError):
    """Expected operator-facing failure without sensitive response details."""


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Python operator CLI."""

    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 2
    try:
        result = _dispatch(arguments)
    except (CliError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if result is not None:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="causentra",
        description="Operate the authenticated Causentra Python collector.",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("CAUSENTRA_URL", "http://127.0.0.1:4318"),
        help="Collector base URL (default: CAUSENTRA_URL or loopback)",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        help="File containing the bearer key; otherwise CAUSENTRA_API_KEY is used",
    )
    parser.add_argument(
        "--allow-insecure-remote",
        action="store_true",
        help="Development only: permit plaintext HTTP to a non-loopback host",
    )
    subcommands = parser.add_subparsers(dest="command")

    subcommands.add_parser("doctor", help="Check liveness, readiness, and authentication")
    traces = subcommands.add_parser("traces", help="List project-scoped traces")
    traces.add_argument("--limit", type=int, default=50)
    trace = subcommands.add_parser("trace", help="Read one complete project trace")
    trace.add_argument("trace_id")
    delete = subcommands.add_parser("delete", help="Delete one complete project trace")
    delete.add_argument("trace_id")
    delete.add_argument(
        "--confirm",
        required=True,
        help="Must exactly repeat the trace ID to prevent accidental deletion",
    )

    initialize = subcommands.add_parser(
        "init", help="Create a collector config and high-entropy project-key file"
    )
    initialize.add_argument("--config", type=Path, default=Path("collector.json"))
    initialize.add_argument("--key-output", type=Path, default=Path("collector.key"))
    initialize.add_argument("--project", default="local_project")
    initialize.add_argument("--database", default=".causentra/collector.db")
    initialize.add_argument("--port", type=int, default=4318)

    backup = subcommands.add_parser("backup", help="Create a consistent collector backup")
    backup.add_argument("--config", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    prune = subcommands.add_parser(
        "prune-idempotency", help="Delete expired batch-idempotency tombstones"
    )
    prune.add_argument("--config", type=Path, required=True)
    prune.add_argument("--older-than-days", type=int, required=True)
    prune.add_argument("--limit", type=int, default=10_000)
    return parser


def _dispatch(arguments: argparse.Namespace) -> Mapping[str, Any] | None:
    command = str(arguments.command)
    if command == "init":
        return _initialize(arguments)
    if command == "backup":
        config = load_collector_config(arguments.config)
        store = _open_store(config)
        try:
            destination = store.backup(arguments.output)
        finally:
            store.close()
        return {"backup": str(destination), "status": "created"}
    if command == "prune-idempotency":
        if arguments.older_than_days <= 0:
            raise CliError("older-than-days must be positive")
        config = load_collector_config(arguments.config)
        store = _open_store(config)
        try:
            removed = store.prune_batches(
                older_than=time.time() - arguments.older_than_days * 86_400,
                limit=arguments.limit,
            )
        finally:
            store.close()
        return {"removedBatchTombstones": removed}

    base_url = _base_url(arguments.url, arguments.allow_insecure_remote)
    key = _api_key(arguments.key_file, required=command != "doctor")
    if command == "doctor":
        result: dict[str, Any] = {
            "health": _request(base_url, "/health", key=None),
            "ready": _request(base_url, "/ready", key=None),
        }
        if key is not None:
            _request(base_url, "/v1/traces?limit=1", key=key)
            result["authentication"] = {"status": "ok"}
        else:
            result["authentication"] = {"status": "not_checked"}
        return result
    if command == "traces":
        if not 1 <= arguments.limit <= 200:
            raise CliError("limit must be between 1 and 200")
        return _request(base_url, f"/v1/traces?limit={arguments.limit}", key=key)
    trace_id = _trace_id(arguments.trace_id)
    path = f"/v1/traces/{quote(trace_id, safe='')}"
    if command == "trace":
        return _request(base_url, path, key=key)
    if command == "delete":
        if arguments.confirm != trace_id:
            raise CliError("--confirm must exactly match the trace ID")
        return _request(base_url, path, key=key, method="DELETE")
    raise CliError(f"unsupported command: {command}")


def _initialize(arguments: argparse.Namespace) -> Mapping[str, Any]:
    if not 0 <= arguments.port <= 65_535:
        raise CliError("port must be between 0 and 65535")
    project = str(arguments.project)
    key = secrets.token_urlsafe(48)
    config = {
        "database": str(arguments.database),
        "listen": {
            "host": "127.0.0.1",
            "port": arguments.port,
            "allowInsecureRemote": False,
        },
        "apiKeys": [
            {
                "id": "local-project",
                "projectId": project,
                "sha256": hashlib.sha256(key.encode()).hexdigest(),
                "role": "project",
            }
        ],
        "limits": {},
        "tls": {},
    }
    config_path = Path(arguments.config).expanduser().resolve()
    key_path = Path(arguments.key_output).expanduser().resolve()
    _exclusive_write(config_path, json.dumps(config, indent=2) + "\n")
    try:
        _exclusive_write(key_path, key + "\n")
    except BaseException:
        config_path.unlink(missing_ok=True)
        raise
    for path in (config_path, key_path):
        with suppress(PermissionError):
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    try:
        load_collector_config(config_path)
    except BaseException:
        config_path.unlink(missing_ok=True)
        key_path.unlink(missing_ok=True)
        raise
    return {
        "config": str(config_path),
        "keyFile": str(key_path),
        "projectId": project,
        "status": "created",
    }


def _request(
    base_url: str,
    path: str,
    *,
    key: str | None,
    method: str = "GET",
) -> Mapping[str, Any]:
    headers = {"Accept": "application/json", "X-Request-Id": secrets.token_hex(16)}
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(f"{base_url}{path}", headers=headers, method=method)
    try:
        # Base URL validation permits only HTTP(S).
        with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(payload) > _MAX_RESPONSE_BYTES:
                raise CliError("collector response exceeded 16 MiB")
    except urllib.error.HTTPError as error:
        raise CliError(f"collector rejected the request with HTTP {error.code}") from error
    except (TimeoutError, urllib.error.URLError) as error:
        raise CliError("collector request failed") from error
    try:
        value = json.loads(payload, object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError) as error:
        raise CliError("collector returned invalid JSON") from error
    if not isinstance(value, dict):
        raise CliError("collector returned a non-object response")
    return value


def _api_key(path: Path | None, *, required: bool) -> str | None:
    value: str | None
    if path is None:
        value = os.environ.get("CAUSENTRA_API_KEY")
    else:
        source = path.expanduser().resolve()
        if not source.is_file() or source.stat().st_size > 4_096:
            raise CliError("key file must exist and be at most 4 KiB")
        value = source.read_text(encoding="utf-8").strip()
    if value is None and not required:
        return None
    if value is None or not 32 <= len(value) <= 512:
        raise CliError("a 32-512 character key is required through key file or environment")
    return value


def _base_url(value: str, allow_insecure_remote: bool) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise CliError("collector URL must be an HTTP(S) origin")
    if parsed.username is not None or parsed.password is not None:
        raise CliError("collector URL must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise CliError("collector URL must not contain a path, query, or fragment")
    try:
        port = parsed.port
    except ValueError as error:
        raise CliError("collector URL contains an invalid port") from error
    del port
    if (
        parsed.scheme == "http"
        and not _is_loopback(parsed.hostname)
        and not allow_insecure_remote
    ):
        raise CliError("remote collector URL requires HTTPS")
    return value.rstrip("/")


def _trace_id(value: str) -> str:
    if len(value) != 32 or any(character not in "0123456789abcdef" for character in value):
        raise CliError("trace ID must contain 32 lowercase hexadecimal characters")
    return value


def _open_store(config: CollectorConfig) -> SqliteCollectorStore:
    return SqliteCollectorStore(
        config.database_path,
        max_events=config.limits.max_store_events,
        max_payload_bytes=config.limits.max_store_bytes,
        max_project_events=config.limits.max_project_events,
        max_project_payload_bytes=config.limits.max_project_bytes,
    )


def _exclusive_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

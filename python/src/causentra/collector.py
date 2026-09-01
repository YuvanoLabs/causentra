"""Authenticated, tenant-isolated Python HTTP collector."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import signal
import ssl
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from .collector_store import (
    CollectorCapacityError,
    IdempotencyConflictError,
    SqliteCollectorStore,
)
from .signatures import (
    SignatureVerificationResult,
    batch_signature_artifact,
    verify_detached_signature,
)
from .types import JsonValue, RuntimeEvent
from .validation import EventValidationError, event_from_wire

_PROJECT_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KEY_HASH = re.compile(r"^[0-9a-f]{64}$")
_BATCH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_SIGNING_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SIGNING_KEY_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_LOGGER = logging.getLogger("causentra.collector")

_SCOPES = frozenset(
    {
        "events:ingest",
        "traces:read",
        "traces:debug",
        "traces:delete",
        "metrics:read",
        "audit:read",
    }
)
_PROJECT_SCOPES = frozenset(
    {"events:ingest", "traces:read", "traces:debug", "traces:delete"}
)


@dataclass(frozen=True, slots=True)
class ApiPrincipal:
    """One API credential identity; only its SHA-256 digest is retained."""

    key_id: str
    project_id: str
    key_sha256: str
    operator: bool = False
    scopes: frozenset[str] = field(default_factory=lambda: _PROJECT_SCOPES)

    def __post_init__(self) -> None:
        if not _KEY_ID.fullmatch(self.key_id):
            raise ValueError("key_id has an invalid format")
        if not _PROJECT_ID.fullmatch(self.project_id):
            raise ValueError("project_id has an invalid format")
        if not _KEY_HASH.fullmatch(self.key_sha256):
            raise ValueError("key_sha256 must be a lowercase SHA-256 digest")
        if not isinstance(self.operator, bool):
            raise ValueError("operator must be a boolean")
        if not isinstance(self.scopes, frozenset) or not self.scopes <= _SCOPES:
            raise ValueError("scopes must be a known immutable scope set")

    def has_scope(self, scope: str) -> bool:
        """Return whether this principal is authorized for one API capability."""

        return self.operator or scope in self.scopes

    @classmethod
    def from_api_key(
        cls,
        key_id: str,
        project_id: str,
        api_key: str,
        *,
        operator: bool = False,
        scopes: frozenset[str] | None = None,
    ) -> ApiPrincipal:
        """Build a principal for tests/bootstrap without retaining the raw key."""

        if len(api_key) < 32:
            raise ValueError("API keys must contain at least 32 characters")
        return cls(
            key_id,
            project_id,
            hashlib.sha256(api_key.encode("utf-8")).hexdigest(),
            operator,
            _PROJECT_SCOPES if scopes is None else scopes,
        )


@dataclass(frozen=True, slots=True)
class SignatureVerificationKey:
    """Public verification material retained by the collector configuration."""

    key_id: str
    key_version: str
    public_key: str
    revoked: bool = False

    def __post_init__(self) -> None:
        if not _SIGNING_KEY_ID.fullmatch(self.key_id):
            raise ValueError("signature key ID has an invalid format")
        if not _SIGNING_KEY_VERSION.fullmatch(self.key_version):
            raise ValueError("signature key version has an invalid format")
        if not isinstance(self.public_key, str) or not self.public_key.strip():
            raise ValueError("signature public key must be a non-empty PEM string")
        if len(self.public_key.encode("utf-8")) > 16 * 1024:
            raise ValueError("signature public key exceeds 16 KiB")
        if not isinstance(self.revoked, bool):
            raise ValueError("signature revoked must be a boolean")


@dataclass(frozen=True, slots=True)
class SignatureVerificationConfig:
    """Fail-closed detached signature policy for event-batch ingestion."""

    require_verification: bool = False
    keys: tuple[SignatureVerificationKey, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.require_verification, bool):
            raise ValueError("require_verification must be a boolean")
        pairs = {(key.key_id, key.key_version) for key in self.keys}
        if len(pairs) != len(self.keys):
            raise ValueError("signature key ID/version pairs must be unique")
        if self.require_verification and not self.keys:
            raise ValueError("require_verification requires at least one public key")

    def resolve_key(self, key_id: str, key_version: str) -> dict[str, Any] | None:
        for key in self.keys:
            if key.key_id == key_id and key.key_version == key_version:
                return {"publicKey": key.public_key, "revoked": key.revoked}
        return None


@dataclass(frozen=True, slots=True)
class CollectorLimits:
    max_body_bytes: int = 2 * 1024 * 1024
    max_batch_events: int = 1_000
    requests_per_minute: int = 600
    auth_attempts_per_minute: int = 600
    events_per_minute: int = 100_000
    max_store_events: int = 10_000_000
    max_store_bytes: int = 20 * 1024 * 1024 * 1024
    max_project_events: int = 2_000_000
    max_project_bytes: int = 4 * 1024 * 1024 * 1024
    max_concurrent_requests: int = 128
    request_timeout_seconds: int = 15
    max_audit_records: int = 1_000_000

    def __post_init__(self) -> None:
        for name in (
            "max_body_bytes",
            "max_batch_events",
            "requests_per_minute",
            "auth_attempts_per_minute",
            "events_per_minute",
            "max_store_events",
            "max_store_bytes",
            "max_project_events",
            "max_project_bytes",
            "max_concurrent_requests",
            "request_timeout_seconds",
            "max_audit_records",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_project_events > self.max_store_events:
            raise ValueError("max_project_events cannot exceed max_store_events")
        if self.max_project_bytes > self.max_store_bytes:
            raise ValueError("max_project_bytes cannot exceed max_store_bytes")


@dataclass(frozen=True, slots=True)
class CollectorConfig:
    database_path: Path
    principals: tuple[ApiPrincipal, ...]
    host: str = "127.0.0.1"
    port: int = 4318
    limits: CollectorLimits = field(default_factory=CollectorLimits)
    tls_certificate: Path | None = None
    tls_private_key: Path | None = None
    allow_insecure_remote: bool = False
    signatures: SignatureVerificationConfig = field(
        default_factory=SignatureVerificationConfig
    )

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, Path):
            raise ValueError("database_path must be a pathlib.Path")
        if not self.principals:
            raise ValueError("at least one API principal is required")
        if len(self.principals) > 10_000:
            raise ValueError("at most 10,000 API principals may be configured")
        if len({principal.key_id for principal in self.principals}) != len(self.principals):
            raise ValueError("API principal key IDs must be unique")
        if len({principal.key_sha256 for principal in self.principals}) != len(
            self.principals
        ):
            raise ValueError("API principal hashes must be unique")
        if not 0 <= self.port <= 65_535:
            raise ValueError("port must be between 0 and 65535")
        if (self.tls_certificate is None) != (self.tls_private_key is None):
            raise ValueError("tls_certificate and tls_private_key must be configured together")
        if (
            not _is_loopback(self.host)
            and self.tls_certificate is None
            and not self.allow_insecure_remote
        ):
            raise ValueError("non-loopback collector binding requires TLS")


@dataclass(frozen=True, slots=True)
class RunningCollector:
    """Background collector handle used by embedding applications and tests."""

    url: str
    _server: _CollectorHttpServer
    _thread: threading.Thread

    @property
    def is_running(self) -> bool:
        """Return whether the embedded serving thread is alive."""

        return self._thread.is_alive()

    def close(self, timeout: float = 10.0) -> None:
        started = time.monotonic()
        self._server.begin_shutdown()
        self._server.shutdown()
        self._thread.join(max(0.0, timeout - (time.monotonic() - started)))
        if self._thread.is_alive():
            raise TimeoutError("collector did not stop before the timeout")
        if not self._server.wait_for_requests(
            max(0.0, timeout - (time.monotonic() - started))
        ):
            raise TimeoutError("collector requests did not drain before the timeout")
        self._server.server_close()
        self._server.store.checkpoint()
        self._server.store.close()


class _Authenticator:
    def __init__(self, principals: Sequence[ApiPrincipal]) -> None:
        self._principals = tuple(principals)

    def authenticate(self, authorization: str | None) -> ApiPrincipal | None:
        if authorization is None or not authorization.startswith("Bearer "):
            return None
        raw = authorization[7:]
        if len(raw) < 32 or len(raw) > 512:
            return None
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        matched: ApiPrincipal | None = None
        for principal in self._principals:
            if hmac.compare_digest(digest, principal.key_sha256):
                matched = principal
        return matched


class _RateLimiter:
    def __init__(
        self,
        requests_per_minute: int,
        events_per_minute: int,
        auth_attempts_per_minute: int,
        *,
        max_identities: int = 10_000,
    ) -> None:
        self._limits = {
            "request": requests_per_minute,
            "event": events_per_minute,
            "auth": auth_attempts_per_minute,
        }
        self._max_identities = max_identities
        self._windows: dict[tuple[str, str], tuple[int, int]] = {}
        self._lock = threading.Lock()

    def allow(self, key_id: str, category: str, cost: int = 1) -> tuple[bool, int]:
        window = int(time.time() // 60)
        identifier = (key_id, category)
        limit = self._limits[category]
        with self._lock:
            if identifier not in self._windows and len(self._windows) >= self._max_identities:
                self._windows = {
                    key: value
                    for key, value in self._windows.items()
                    if value[0] == window
                }
                if len(self._windows) >= self._max_identities:
                    return False, max(1, 60 - int(time.time() % 60))
            existing_window, used = self._windows.get(identifier, (window, 0))
            if existing_window != window:
                existing_window, used = window, 0
            if cost > limit or used + cost > limit:
                return False, max(1, 60 - int(time.time() % 60))
            self._windows[identifier] = (existing_window, used + cost)
        return True, 0


class _Metrics:
    def __init__(self) -> None:
        self._values = {
            "requests": 0,
            "auth_failures": 0,
            "rate_limited": 0,
            "accepted_events": 0,
            "duplicate_events": 0,
            "request_failures": 0,
        }
        self._lock = threading.Lock()

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._values[name] += value

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._values)


class _CollectorHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 256

    def __init__(self, config: CollectorConfig, store: SqliteCollectorStore) -> None:
        self.config = config
        self.store = store
        self.authenticator = _Authenticator(config.principals)
        self.rate_limiter = _RateLimiter(
            config.limits.requests_per_minute,
            config.limits.events_per_minute,
            config.limits.auth_attempts_per_minute,
        )
        self.metrics = _Metrics()
        self._request_slots = threading.BoundedSemaphore(
            config.limits.max_concurrent_requests
        )
        self._active_condition = threading.Condition()
        self._active_requests = 0
        self._stopping = False
        super().__init__((config.host, config.port), _CollectorRequestHandler)
        if config.tls_certificate is not None and config.tls_private_key is not None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(config.tls_certificate, config.tls_private_key)
            self.socket = context.wrap_socket(self.socket, server_side=True)

    def get_request(self) -> tuple[Any, Any]:
        request, address = super().get_request()
        request.settimeout(self.config.limits.request_timeout_seconds)
        return request, address

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            self.metrics.increment("rate_limited")
            return
        with self._active_condition:
            if self._stopping:
                self._request_slots.release()
                self.shutdown_request(request)
                return
            self._active_requests += 1
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            with self._active_condition:
                self._active_requests -= 1
                self._active_condition.notify_all()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()
            with self._active_condition:
                self._active_requests -= 1
                self._active_condition.notify_all()

    def begin_shutdown(self) -> None:
        with self._active_condition:
            self._stopping = True

    def wait_for_requests(self, timeout: float | None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._active_condition:
            while self._active_requests:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._active_condition.wait(remaining)
        return True

    def handle_error(self, request: Any, client_address: Any) -> None:
        del request
        _LOGGER.exception("collector_request_failed remote=%s", client_address[0])


class _CollectorRequestHandler(BaseHTTPRequestHandler):
    server: _CollectorHttpServer
    protocol_version = "HTTP/1.1"
    server_version = "CausentraCollector/1"
    sys_version = ""

    def do_GET(self) -> None:
        request_id = self._request_id()
        path = urlsplit(self.path)
        if path.path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok"}, request_id)
            return
        if path.path == "/ready":
            ready = self.server.store.ready()
            self._json(
                HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
                {"status": "ready" if ready else "not_ready"},
                request_id,
            )
            return
        principal = self._authorize(request_id)
        if principal is None:
            return
        if path.path == "/metrics":
            if not self._require_scope(principal, "metrics:read", "metrics.read", request_id):
                return
            self._metrics(principal, request_id)
            return
        if path.path == "/v1/audit":
            if not self._require_scope(principal, "audit:read", "audit.read", request_id):
                return
            query = parse_qs(path.query, keep_blank_values=True)
            try:
                limit = int(query.get("limit", ["100"])[0])
                decisions = self.server.store.list_audit(limit)
            except (ValueError, TypeError):
                self._error(
                    HTTPStatus.BAD_REQUEST,
                    "invalid_limit",
                    "limit must be an integer between 1 and 500",
                    request_id,
                )
                return
            self._json(HTTPStatus.OK, {"decisions": decisions}, request_id)
            return
        if path.path == "/v1/traces":
            if not self._require_scope(principal, "traces:read", "traces.list", request_id):
                return
            query = parse_qs(path.query, keep_blank_values=True)
            try:
                limit = int(query.get("limit", ["50"])[0])
                traces = self.server.store.list_traces(principal.project_id, limit)
            except (ValueError, TypeError):
                self._error(
                    HTTPStatus.BAD_REQUEST,
                    "invalid_limit",
                    "limit must be an integer between 1 and 200",
                    request_id,
                )
                return
            self._json(HTTPStatus.OK, {"traces": traces}, request_id)
            return
        prefix = "/v1/traces/"
        if path.path.startswith(prefix):
            if not self._require_scope(principal, "traces:read", "traces.read", request_id):
                return
            trace_id = path.path[len(prefix) :]
            if not _TRACE_ID.fullmatch(trace_id):
                self._error(
                    HTTPStatus.BAD_REQUEST,
                    "invalid_trace_id",
                    "trace ID has an invalid format",
                    request_id,
                )
                return
            events = self.server.store.get_trace(principal.project_id, trace_id)
            if not events:
                self._error(
                    HTTPStatus.NOT_FOUND,
                    "trace_not_found",
                    "trace was not found",
                    request_id,
                )
                return
            self._json(
                HTTPStatus.OK,
                {
                    "traceId": trace_id,
                    "projection": (
                        "debug" if principal.has_scope("traces:debug") else "summary"
                    ),
                    "events": [
                        _event_projection(
                            event, include_attributes=principal.has_scope("traces:debug")
                        )
                        for event in events
                    ],
                },
                request_id,
            )
            return
        self._error(HTTPStatus.NOT_FOUND, "not_found", "route was not found", request_id)

    def do_POST(self) -> None:
        request_id = self._request_id()
        if urlsplit(self.path).path != "/v1/events":
            self._error(HTTPStatus.NOT_FOUND, "not_found", "route was not found", request_id)
            return
        principal = self._authorize(request_id)
        if principal is None:
            return
        if not self._require_scope(principal, "events:ingest", "events.ingest", request_id):
            return
        body = self._read_json(request_id)
        if body is None:
            return
        if not isinstance(body, dict):
            self._error(
                HTTPStatus.BAD_REQUEST,
                "invalid_batch",
                "request body must be an object",
                request_id,
            )
            return
        unknown = set(body) - {"transportVersion", "batchId", "events", "signature"}
        if unknown:
            self._error(
                HTTPStatus.BAD_REQUEST,
                "invalid_batch",
                f"unsupported batch field: {sorted(unknown)[0]}",
                request_id,
            )
            return
        if body.get("transportVersion", "1.0") != "1.0":
            self._error(
                HTTPStatus.BAD_REQUEST,
                "unsupported_transport_version",
                "transportVersion must equal 1.0",
                request_id,
            )
            return
        raw_events = body.get("events")
        if not isinstance(raw_events, list) or not (
            1 <= len(raw_events) <= self.server.config.limits.max_batch_events
        ):
            self._error(
                HTTPStatus.BAD_REQUEST,
                "invalid_batch",
                "events must be a non-empty array within the configured batch limit",
                request_id,
            )
            return
        header_batch_id = self.headers.get("Idempotency-Key")
        body_batch_id = body.get("batchId")
        if body_batch_id is not None and not isinstance(body_batch_id, str):
            body_batch_id = None
        if header_batch_id and body_batch_id and header_batch_id != body_batch_id:
            self._error(
                HTTPStatus.CONFLICT,
                "idempotency_conflict",
                "header and body batch identifiers differ",
                request_id,
            )
            return
        batch_id = header_batch_id or body_batch_id
        if batch_id is None or not _BATCH_ID.fullmatch(batch_id):
            self._error(
                HTTPStatus.BAD_REQUEST,
                "invalid_idempotency_key",
                "a valid Idempotency-Key or batchId is required",
                request_id,
            )
            return
        allowed, retry_after = self.server.rate_limiter.allow(
            principal.key_id, "event", len(raw_events)
        )
        if not allowed:
            self.server.metrics.increment("rate_limited")
            self._error(
                HTTPStatus.TOO_MANY_REQUESTS,
                "rate_limited",
                "event rate limit exceeded",
                request_id,
                {"Retry-After": str(retry_after)},
            )
            return
        verification = self._verify_batch_signature(
            batch_id,
            cast(list[JsonValue], raw_events),
            body.get("signature"),
            principal,
            request_id,
        )
        if verification is None:
            return
        try:
            events = tuple(
                event_from_wire(cast(Mapping[str, Any], item))
                if isinstance(item, dict)
                else _raise_invalid_event()
                for item in raw_events
            )
            # Signatures are randomized. Idempotency is therefore based on the
            # covered payload rather than a detachable envelope's wire bytes.
            digest = hashlib.sha256(
                json.dumps(
                    batch_signature_artifact(
                        batch_id, cast(list[JsonValue], raw_events)
                    )["value"],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            result = self.server.store.ingest(
                principal.project_id, batch_id, digest, events
            )
        except EventValidationError as error:
            self._error(
                HTTPStatus.BAD_REQUEST,
                "invalid_event",
                str(error),
                request_id,
                extra={"X-Causentra-Invalid-Field": error.field[:128]},
            )
            return
        except IdempotencyConflictError:
            self._error(
                HTTPStatus.CONFLICT,
                "idempotency_conflict",
                "an identifier was reused for different data",
                request_id,
            )
            return
        except CollectorCapacityError:
            self._error(
                HTTPStatus.INSUFFICIENT_STORAGE,
                "collector_capacity_reached",
                "collector storage capacity has been reached",
                request_id,
            )
            return
        self.server.metrics.increment("accepted_events", result.accepted)
        self.server.metrics.increment("duplicate_events", result.duplicates)
        self._json(
            HTTPStatus.ACCEPTED,
            {
                "batchId": batch_id,
                "accepted": result.accepted,
                "duplicates": result.duplicates,
                "replayedBatch": result.replayed_batch,
                "verification": verification,
            },
            request_id,
        )

    def do_DELETE(self) -> None:
        request_id = self._request_id()
        principal = self._authorize(request_id)
        if principal is None:
            return
        if not self._require_scope(principal, "traces:delete", "traces.delete", request_id):
            return
        prefix = "/v1/traces/"
        path = urlsplit(self.path).path
        trace_id = path[len(prefix) :] if path.startswith(prefix) else ""
        if not _TRACE_ID.fullmatch(trace_id):
            self._error(
                HTTPStatus.BAD_REQUEST,
                "invalid_trace_id",
                "trace ID has an invalid format",
                request_id,
            )
            return
        deleted = self.server.store.delete_trace(principal.project_id, trace_id)
        if deleted == 0:
            self._error(
                HTTPStatus.NOT_FOUND,
                "trace_not_found",
                "trace was not found",
                request_id,
            )
            return
        self._json(
            HTTPStatus.OK,
            {"traceId": trace_id, "deletedEvents": deleted},
            request_id,
        )

    def _authorize(self, request_id: str) -> ApiPrincipal | None:
        self.server.metrics.increment("requests")
        allowed, retry_after = self.server.rate_limiter.allow(
            f"remote:{self.client_address[0]}", "auth"
        )
        if not allowed:
            self.server.metrics.increment("rate_limited")
            self._error(
                HTTPStatus.TOO_MANY_REQUESTS,
                "rate_limited",
                "authentication attempt rate limit exceeded",
                request_id,
                {"Retry-After": str(retry_after)},
            )
            self._audit("anonymous", "", "authenticate", "rate_limited", request_id)
            return None
        principal = self.server.authenticator.authenticate(self.headers.get("Authorization"))
        if principal is None:
            self.server.metrics.increment("auth_failures")
            self._error(
                HTTPStatus.UNAUTHORIZED,
                "unauthorized",
                "a valid bearer API key is required",
                request_id,
                {"WWW-Authenticate": 'Bearer realm="causentra"'},
            )
            self._audit("anonymous", "", "authenticate", "denied", request_id)
            return None
        allowed, retry_after = self.server.rate_limiter.allow(principal.key_id, "request")
        if not allowed:
            self.server.metrics.increment("rate_limited")
            self._error(
                HTTPStatus.TOO_MANY_REQUESTS,
                "rate_limited",
                "request rate limit exceeded",
                request_id,
                {"Retry-After": str(retry_after)},
            )
            self._audit(
                principal.key_id,
                principal.project_id,
                "authenticate",
                "rate_limited",
                request_id,
            )
            return None
        return principal

    def _require_scope(
        self, principal: ApiPrincipal, scope: str, action: str, request_id: str
    ) -> bool:
        if principal.has_scope(scope):
            self._audit(principal.key_id, principal.project_id, action, "allowed", request_id)
            return True
        self._audit(principal.key_id, principal.project_id, action, "denied", request_id)
        self._error(
            HTTPStatus.FORBIDDEN,
            "forbidden",
            f"the authenticated key lacks {scope} scope",
            request_id,
        )
        return False

    def _verify_batch_signature(
        self,
        batch_id: str,
        events: list[JsonValue],
        envelope: Any,
        principal: ApiPrincipal,
        request_id: str,
    ) -> str | None:
        if envelope is None:
            if not self.server.config.signatures.require_verification:
                return "unsigned"
            self._audit(
                principal.key_id,
                principal.project_id,
                "events.ingest",
                "signature_required",
                request_id,
            )
            self._error(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "signature_required",
                "collector policy requires a detached batch signature",
                request_id,
            )
            return None
        try:
            result: SignatureVerificationResult = verify_detached_signature(
                batch_signature_artifact(batch_id, events),
                envelope,
                resolve_key=self.server.config.signatures.resolve_key,
            )
        except (TypeError, ValueError, RuntimeError):
            result = {"verified": False, "reason": "verification-unavailable"}
        if result.get("verified") is True:
            return "verified"
        self._audit(
            principal.key_id,
            principal.project_id,
            "events.ingest",
            f"signature_{result.get('reason', 'invalid')}",
            request_id,
        )
        self._error(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "signature_invalid",
            "detached batch signature could not be verified",
            request_id,
        )
        return None

    def _audit(
        self, key_id: str, project_id: str, action: str, outcome: str, request_id: str
    ) -> None:
        try:
            self.server.store.record_audit(
                key_id=key_id,
                project_id=project_id,
                action=action,
                outcome=outcome,
                request_id=request_id,
            )
        except Exception:  # pragma: no cover
            # Preserve the response if audit storage is unavailable.
            _LOGGER.exception("collector_audit_write_failed request_id=%s", request_id)

    _raw_body: bytes = b""

    def _read_json(self, request_id: str) -> Any | None:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._error(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "unsupported_media_type",
                "Content-Type must be application/json",
                request_id,
            )
            return None
        if self.headers.get("Transfer-Encoding") is not None:
            self._error(
                HTTPStatus.BAD_REQUEST,
                "unsupported_transfer_encoding",
                "chunked request bodies are not supported",
                request_id,
            )
            return None
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if length < 0:
            self._error(
                HTTPStatus.LENGTH_REQUIRED,
                "content_length_required",
                "a valid Content-Length header is required",
                request_id,
            )
            return None
        if length > self.server.config.limits.max_body_bytes:
            self._error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "body_too_large",
                "request body exceeds the configured limit",
                request_id,
            )
            return None
        self._raw_body = self.rfile.read(length)
        if len(self._raw_body) != length:
            self._error(
                HTTPStatus.BAD_REQUEST,
                "incomplete_body",
                "request body was incomplete",
                request_id,
            )
            return None
        try:
            return json.loads(self._raw_body, object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError):
            self._error(
                HTTPStatus.BAD_REQUEST,
                "invalid_json",
                "request body is not valid UTF-8 JSON",
                request_id,
            )
            return None

    def _metrics(self, principal: ApiPrincipal, request_id: str) -> None:
        values = self.server.metrics.snapshot()
        del principal
        stats = self.server.store.stats()
        lines = [
            "# TYPE causentra_collector_requests_total counter",
            f"causentra_collector_requests_total {values['requests']}",
            "# TYPE causentra_collector_auth_failures_total counter",
            f"causentra_collector_auth_failures_total {values['auth_failures']}",
            "# TYPE causentra_collector_rate_limited_total counter",
            f"causentra_collector_rate_limited_total {values['rate_limited']}",
            "# TYPE causentra_collector_accepted_events_total counter",
            f"causentra_collector_accepted_events_total {values['accepted_events']}",
            "# TYPE causentra_collector_duplicate_events_total counter",
            f"causentra_collector_duplicate_events_total {values['duplicate_events']}",
            "# TYPE causentra_collector_store_projects gauge",
            f"causentra_collector_store_projects {stats.projects}",
            "# TYPE causentra_collector_store_traces gauge",
            f"causentra_collector_store_traces {stats.traces}",
            "# TYPE causentra_collector_store_events gauge",
            f"causentra_collector_store_events {stats.events}",
            "# TYPE causentra_collector_store_payload_bytes gauge",
            f"causentra_collector_store_payload_bytes {stats.payload_bytes}",
            "# TYPE causentra_collector_store_batches gauge",
            f"causentra_collector_store_batches {stats.batches}",
            "",
        ]
        payload = "\n".join(lines).encode("utf-8")
        self._send(
            HTTPStatus.OK,
            payload,
            request_id,
            {"Content-Type": "text/plain; version=0.0.4; charset=utf-8"},
        )

    def _json(self, status: HTTPStatus, value: Any, request_id: str) -> None:
        payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self._send(
            status,
            payload,
            request_id,
            {"Content-Type": "application/json; charset=utf-8"},
        )

    def _error(
        self,
        status: HTTPStatus,
        code: str,
        message: str,
        request_id: str,
        headers: Mapping[str, str] | None = None,
        extra: Mapping[str, str] | None = None,
    ) -> None:
        self.server.metrics.increment("request_failures")
        self.close_connection = True
        combined = dict(headers or {})
        combined.update(extra or {})
        payload = json.dumps(
            {"error": {"code": code, "message": message, "requestId": request_id}},
            separators=(",", ":"),
        ).encode("utf-8")
        combined["Content-Type"] = "application/json; charset=utf-8"
        self._send(status, payload, request_id, combined)

    def _send(
        self,
        status: HTTPStatus,
        payload: bytes,
        request_id: str,
        headers: Mapping[str, str],
    ) -> None:
        self.send_response(status.value)
        safe_headers = {
            "Cache-Control": "no-store",
            "Content-Length": str(len(payload)),
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-Request-Id": request_id,
            **headers,
        }
        for name, value in safe_headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def _request_id(self) -> str:
        candidate = self.headers.get("X-Request-Id")
        return (
            candidate
            if candidate and _REQUEST_ID.fullmatch(candidate)
            else secrets.token_hex(16)
        )

    def log_message(self, format: str, *args: Any) -> None:
        del format
        result = args[1] if len(args) > 1 else "unknown"
        _LOGGER.info("collector_request remote=%s result=%s", self.client_address[0], result)


def start_collector(config: CollectorConfig) -> RunningCollector:
    """Start the collector in a background thread for embedding or tests."""

    store = SqliteCollectorStore(
        config.database_path,
        max_events=config.limits.max_store_events,
        max_payload_bytes=config.limits.max_store_bytes,
        max_project_events=config.limits.max_project_events,
        max_project_payload_bytes=config.limits.max_project_bytes,
        max_audit_records=config.limits.max_audit_records,
    )
    try:
        server = _CollectorHttpServer(config, store)
    except BaseException:
        store.close()
        raise
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.2},
        name="causentra-collector",
        daemon=True,
    )
    thread.start()
    host, port = server.server_address[:2]
    if not isinstance(host, str) or not isinstance(port, int):
        server.shutdown()
        server.server_close()
        store.close()
        raise RuntimeError("collector server returned an unsupported socket address")
    scheme = "https" if config.tls_certificate is not None else "http"
    rendered_host = f"[{host}]" if ":" in str(host) else str(host)
    return RunningCollector(f"{scheme}://{rendered_host}:{port}", server, thread)


def load_collector_config(path: str | Path) -> CollectorConfig:
    """Load a strict JSON configuration containing only API key hashes."""

    source = Path(path)
    if not source.is_file() or source.stat().st_size > 1024 * 1024:
        raise ValueError("collector configuration must be an existing file of at most 1 MiB")
    try:
        value = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as error:
        raise ValueError("collector configuration must be valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValueError("collector configuration must be an object")
    unknown = set(value) - {
        "database",
        "listen",
        "apiKeys",
        "limits",
        "tls",
        "signatures",
    }
    if unknown:
        raise ValueError(f"unsupported collector configuration field: {sorted(unknown)[0]}")
    api_keys = value.get("apiKeys")
    if not isinstance(api_keys, list):
        raise ValueError("apiKeys must be an array")
    principals = tuple(_principal_from_config(item) for item in api_keys)
    listen = _mapping(value.get("listen", {}), "listen")
    limits_value = _mapping(value.get("limits", {}), "limits")
    tls_value = _mapping(value.get("tls", {}), "tls")
    signatures_value = _mapping(value.get("signatures", {}), "signatures")
    _reject_unknown(listen, {"host", "port", "allowInsecureRemote"}, "listen")
    _reject_unknown(
        limits_value,
        {
            "maxBodyBytes",
            "maxBatchEvents",
            "requestsPerMinute",
            "authAttemptsPerMinute",
            "eventsPerMinute",
            "maxStoreEvents",
            "maxStoreBytes",
            "maxProjectEvents",
            "maxProjectBytes",
            "maxConcurrentRequests",
            "requestTimeoutSeconds",
            "maxAuditRecords",
        },
        "limits",
    )
    _reject_unknown(tls_value, {"certificate", "privateKey"}, "tls")
    _reject_unknown(signatures_value, {"requireVerification", "keys"}, "signatures")
    limits = CollectorLimits(
        max_body_bytes=_integer(limits_value, "maxBodyBytes", 2 * 1024 * 1024),
        max_batch_events=_integer(limits_value, "maxBatchEvents", 1_000),
        requests_per_minute=_integer(limits_value, "requestsPerMinute", 600),
        auth_attempts_per_minute=_integer(
            limits_value, "authAttemptsPerMinute", 600
        ),
        events_per_minute=_integer(limits_value, "eventsPerMinute", 100_000),
        max_store_events=_integer(limits_value, "maxStoreEvents", 10_000_000),
        max_store_bytes=_integer(
            limits_value, "maxStoreBytes", 20 * 1024 * 1024 * 1024
        ),
        max_project_events=_integer(limits_value, "maxProjectEvents", 2_000_000),
        max_project_bytes=_integer(
            limits_value, "maxProjectBytes", 4 * 1024 * 1024 * 1024
        ),
        max_concurrent_requests=_integer(
            limits_value, "maxConcurrentRequests", 128
        ),
        request_timeout_seconds=_integer(limits_value, "requestTimeoutSeconds", 15),
        max_audit_records=_integer(limits_value, "maxAuditRecords", 1_000_000),
    )
    database = value.get("database")
    if not isinstance(database, str) or not database.strip():
        raise ValueError("database must be a non-empty path")
    certificate = tls_value.get("certificate")
    private_key = tls_value.get("privateKey")
    if certificate is not None and not isinstance(certificate, str):
        raise ValueError("tls.certificate must be a path")
    if private_key is not None and not isinstance(private_key, str):
        raise ValueError("tls.privateKey must be a path")
    keys_value = signatures_value.get("keys", [])
    if not isinstance(keys_value, list):
        raise ValueError("signatures.keys must be an array")
    signature_keys = tuple(_signature_key_from_config(item) for item in keys_value)
    return CollectorConfig(
        database_path=_relative_path(source, database),
        principals=principals,
        host=_string(listen, "host", "127.0.0.1"),
        port=_integer(listen, "port", 4318),
        limits=limits,
        tls_certificate=(
            None if certificate is None else _relative_path(source, certificate)
        ),
        tls_private_key=(
            None if private_key is None else _relative_path(source, private_key)
        ),
        allow_insecure_remote=_boolean(listen, "allowInsecureRemote", False),
        signatures=SignatureVerificationConfig(
            require_verification=_boolean(
                signatures_value, "requireVerification", False
            ),
            keys=signature_keys,
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the collector until SIGINT/SIGTERM without performing deployment."""

    parser = argparse.ArgumentParser(prog="causentra-collector")
    parser.add_argument("--config", required=True, help="Path to collector JSON config")
    arguments = parser.parse_args(argv)
    config = load_collector_config(arguments.config)
    store = SqliteCollectorStore(
        config.database_path,
        max_events=config.limits.max_store_events,
        max_payload_bytes=config.limits.max_store_bytes,
        max_project_events=config.limits.max_project_events,
        max_project_payload_bytes=config.limits.max_project_bytes,
        max_audit_records=config.limits.max_audit_records,
    )
    try:
        server = _CollectorHttpServer(config, store)
    except BaseException:
        store.close()
        raise
    stopped = threading.Event()

    def stop(signum: int, frame: Any) -> None:
        del signum, frame
        stopped.set()
        server.begin_shutdown()
        threading.Thread(target=server.shutdown, daemon=True).start()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    scheme = "https" if config.tls_certificate is not None else "http"
    _LOGGER.info("collector_started url=%s://%s:%d", scheme, config.host, config.port)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.begin_shutdown()
        if not server.wait_for_requests(config.limits.request_timeout_seconds + 5):
            _LOGGER.error("collector_shutdown_request_drain_timed_out")
        server.server_close()
        store.checkpoint()
        store.close()
    return 0 if stopped.is_set() else 1


def _raise_invalid_event() -> RuntimeEvent:
    raise EventValidationError("events", "items must be objects")


def _event_projection(event: RuntimeEvent, *, include_attributes: bool) -> dict[str, Any]:
    """Render the documented trace projection without mutating stored telemetry."""

    value = event.to_wire()
    if not include_attributes:
        value["attributes"] = {}
    return value


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _principal_from_config(value: Any) -> ApiPrincipal:
    item = _mapping(value, "apiKeys item")
    if not {"id", "projectId", "sha256"}.issubset(item) or set(item) - {
        "id",
        "projectId",
        "sha256",
        "role",
        "scopes",
    }:
        raise ValueError(
            "each apiKeys item requires id, projectId, sha256, and optional role/scopes"
        )
    role = _string(item, "role", "project")
    role_scopes = {
        "project": _PROJECT_SCOPES,
        "reader": frozenset({"traces:read"}),
        "debug": frozenset({"traces:read", "traces:debug"}),
        "writer": frozenset({"events:ingest"}),
        "operator": frozenset(),
    }
    if role not in role_scopes:
        raise ValueError("apiKeys role must be project, reader, debug, writer, or operator")
    configured_scopes = item.get("scopes")
    if configured_scopes is None:
        scopes = role_scopes[role]
    else:
        if role == "operator":
            raise ValueError("operator role cannot declare a limited scopes list")
        if not isinstance(configured_scopes, list) or not all(
            isinstance(scope, str) for scope in configured_scopes
        ):
            raise ValueError("apiKeys scopes must be an array of strings")
        scopes = frozenset(cast(list[str], configured_scopes))
        if not scopes <= _SCOPES:
            raise ValueError("apiKeys scopes contain an unsupported value")
    return ApiPrincipal(
        _string(item, "id", ""),
        _string(item, "projectId", ""),
        _string(item, "sha256", ""),
        role == "operator",
        scopes,
    )


def _signature_key_from_config(value: Any) -> SignatureVerificationKey:
    item = _mapping(value, "signatures.keys item")
    _reject_unknown(item, {"id", "version", "publicKey", "revoked"}, "signatures.keys item")
    if not {"id", "version", "publicKey"}.issubset(item):
        raise ValueError("each signatures.keys item requires id, version, and publicKey")
    return SignatureVerificationKey(
        key_id=_string(item, "id", ""),
        key_version=_string(item, "version", ""),
        public_key=_string(item, "publicKey", ""),
        revoked=_boolean(item, "revoked", False),
    )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _integer(value: Mapping[str, Any], key: str, default: int) -> int:
    candidate = value.get(key, default)
    if isinstance(candidate, bool) or not isinstance(candidate, int):
        raise ValueError(f"{key} must be an integer")
    return cast(int, candidate)


def _string(value: Mapping[str, Any], key: str, default: str) -> str:
    candidate = value.get(key, default)
    if not isinstance(candidate, str):
        raise ValueError(f"{key} must be a string")
    return candidate


def _boolean(value: Mapping[str, Any], key: str, default: bool) -> bool:
    candidate = value.get(key, default)
    if not isinstance(candidate, bool):
        raise ValueError(f"{key} must be a boolean")
    return candidate


def _relative_path(config: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else config.parent / path


def hash_api_key(api_key: str) -> str:
    """Hash a high-entropy API key for safe collector configuration storage."""

    if len(api_key) < 32:
        raise ValueError("API keys must contain at least 32 characters")
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def hash_key_main(argv: Sequence[str] | None = None) -> int:
    """Prompt without terminal echo and print a collector-compatible key hash."""

    parser = argparse.ArgumentParser(prog="causentra-key-hash")
    parser.parse_args(argv)
    api_key = getpass.getpass("API key: ")
    print(hash_api_key(api_key))
    return 0


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unsupported {name} field: {sorted(unknown)[0]}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

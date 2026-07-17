"""Safe bridge for framework lifecycle callbacks."""

from __future__ import annotations

import hashlib
import secrets
import threading
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timezone

from .redaction import default_redactor
from .types import (
    SCHEMA_VERSION,
    EventAttributes,
    EventExporter,
    EventStatus,
    Redactor,
    RuntimeErrorContext,
    RuntimeEvent,
    TraceContext,
)
from .validation import validate_attributes, validate_event


class AdapterEventBridge:
    """Normalize unstable external IDs into the Causentra v1 contract."""

    def __init__(
        self,
        service_name: str,
        exporter: EventExporter,
        *,
        redactor: Redactor = default_redactor,
        on_error: Callable[[RuntimeErrorContext], None] | None = None,
        parent_context: TraceContext | None = None,
    ) -> None:
        if not service_name.strip():
            raise ValueError("service_name must not be empty")
        self._service_name = service_name
        self._exporter = exporter
        self._redactor = redactor
        self._on_error = on_error or (lambda _context: None)
        self._parent_context = parent_context
        self._sequences: dict[str, int] = {}
        self._lock = threading.Lock()

    def emit(
        self,
        *,
        external_trace_id: str,
        external_span_id: str,
        event_type: str,
        name: str,
        attributes: EventAttributes | None = None,
        external_parent_span_id: str | None = None,
        external_session_id: str | None = None,
        status: EventStatus = "unset",
        timestamp: datetime | None = None,
        duration_ms: float | None = None,
    ) -> bool:
        try:
            trace_id = (
                self._parent_context.trace_id
                if self._parent_context is not None
                else _canonical(external_trace_id, 32)
            )
            span_id = _canonical(external_span_id, 16)
            if external_parent_span_id is not None:
                parent_id = _canonical(external_parent_span_id, 16)
            elif self._parent_context is not None:
                parent_id = self._parent_context.span_id[-16:]
            else:
                parent_id = None
            raw = attributes or {}
            validate_attributes(raw)
            safe = self._redactor(raw)
            validate_attributes(safe)
            when = timestamp or datetime.now(timezone.utc)
            event = RuntimeEvent(
                schema_version=SCHEMA_VERSION,
                event_id=secrets.token_hex(16),
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_id,
                session_id=(
                    _canonical(external_session_id, 32)
                    if external_session_id
                    else self._parent_context.session_id
                    if self._parent_context
                    else None
                ),
                sequence=self._next(trace_id),
                timestamp=when.astimezone(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
                type=event_type,
                name=name[:256],
                status=status,
                duration_ms=duration_ms,
                service_name=self._service_name,
                attributes=safe,
            )
            validate_event(event)
            self._exporter.emit(event)
            return True
        except BaseException as error:
            with suppress(BaseException):
                self._on_error(RuntimeErrorContext("adapter", error, 1))
            return False

    def flush(self, timeout: float | None = None) -> bool:
        return self._exporter.flush(timeout)

    def shutdown(self, timeout: float | None = None) -> None:
        self._exporter.shutdown(timeout)

    def _next(self, trace_id: str) -> int:
        with self._lock:
            value = self._sequences.get(trace_id, 0)
            self._sequences[trace_id] = value + 1
            return value


def _canonical(value: str, length: int) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]

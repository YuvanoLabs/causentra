"""Optional projection of Causentra lifecycles into OpenTelemetry spans."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import datetime
from typing import Any

from .types import RuntimeErrorContext, RuntimeEvent


class OpenTelemetryEventExporter:
    """Pair runtime start/end events into spans created by an OTel tracer."""

    def __init__(
        self,
        tracer: Any,
        *,
        force_flush: Callable[[], bool | None] | None = None,
        shutdown_provider: Callable[[], None] | None = None,
        on_error: Callable[[RuntimeErrorContext], None] | None = None,
    ) -> None:
        self._tracer = tracer
        self._force_flush = force_flush or (lambda: True)
        self._shutdown_provider = shutdown_provider
        self._on_error = on_error or (lambda _context: None)
        self._active: dict[tuple[str, str], Any] = {}
        self._lock = threading.RLock()
        self._closed = False

    def emit(self, event: RuntimeEvent) -> None:
        if self._closed:
            self._report(RuntimeError("OpenTelemetry exporter is closed"), 1)
            return
        try:
            if event.type.endswith(".start"):
                self._start(event)
            elif event.type.endswith(".end"):
                self._end(event)
            else:
                with self._lock:
                    span = self._active.get((event.trace_id, event.span_id))
                if span is not None:
                    span.add_event(
                        event.name,
                        attributes=_otel_attributes(event.attributes),
                        timestamp=_unix_nano(event.timestamp),
                    )
        except BaseException as error:
            self._report(error, 1)

    def flush(self, timeout: float | None = None) -> bool:
        del timeout
        try:
            result = self._force_flush()
            return result is not False
        except BaseException as error:
            self._report(error, 0)
            return False

    def shutdown(self, timeout: float | None = 5.0) -> None:
        del timeout
        if self._closed:
            return
        self._closed = True
        with self._lock:
            active = list(self._active.values())
            self._active.clear()
        for span in active:
            with suppress(BaseException):
                span.end()
        try:
            if self._shutdown_provider is not None:
                self._shutdown_provider()
            else:
                self._force_flush()
        except BaseException as error:
            self._report(error, 0)

    def _start(self, event: RuntimeEvent) -> None:
        from opentelemetry import trace
        from opentelemetry.trace import SpanKind

        parent = None
        if event.parent_span_id is not None:
            with self._lock:
                parent_span = self._active.get((event.trace_id, event.parent_span_id))
            if parent_span is not None:
                parent = trace.set_span_in_context(parent_span)
        span = self._tracer.start_span(
            event.name,
            context=parent,
            kind=SpanKind.INTERNAL,
            attributes={
                "causentra.trace.id": event.trace_id,
                "causentra.span.id": event.span_id,
                "causentra.event.type": event.type,
                **_otel_attributes(event.attributes),
            },
            start_time=_unix_nano(event.timestamp),
        )
        with self._lock:
            self._active[(event.trace_id, event.span_id)] = span

    def _end(self, event: RuntimeEvent) -> None:
        from opentelemetry.trace import Status, StatusCode

        with self._lock:
            span = self._active.pop((event.trace_id, event.span_id), None)
        if span is None:
            self._start(event)
            with self._lock:
                span = self._active.pop((event.trace_id, event.span_id))
        span.set_attributes(_otel_attributes(event.attributes))
        status = {
            "ok": StatusCode.OK,
            "error": StatusCode.ERROR,
            "unset": StatusCode.UNSET,
        }[event.status]
        span.set_status(Status(status))
        span.end(end_time=_unix_nano(event.timestamp))

    def _report(self, error: BaseException, dropped: int) -> None:
        with suppress(BaseException):
            self._on_error(RuntimeErrorContext("export", error, dropped))


def start_otlp_exporter(
    service_name: str,
    endpoint: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    on_error: Callable[[RuntimeErrorContext], None] | None = None,
) -> OpenTelemetryEventExporter:
    """Create an official OTel provider with OTLP/HTTP protobuf delivery."""

    if not service_name.strip():
        raise ValueError("service_name must not be empty")
    if not endpoint.startswith(("http://", "https://")):
        raise ValueError("endpoint must be an http:// or https:// URL")
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    otlp = OTLPSpanExporter(endpoint=endpoint, headers=dict(headers or {}), timeout=timeout)
    provider.add_span_processor(BatchSpanProcessor(otlp))
    tracer = provider.get_tracer("causentra", "0.1.0a1")
    return OpenTelemetryEventExporter(
        tracer,
        force_flush=provider.force_flush,
        shutdown_provider=provider.shutdown,
        on_error=on_error,
    )


def _unix_nano(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp() * 1_000_000_000)


def _otel_attributes(attributes: Mapping[str, Any]) -> dict[str, str | int | float | bool]:
    result: dict[str, str | int | float | bool] = {}
    for key, value in attributes.items():
        if isinstance(value, str | int | float | bool):
            result[key] = value
        elif value is not None:
            result[key] = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return result

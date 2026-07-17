"""Strict W3C Trace Context injection and extraction."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .types import TraceContext

_TRACEPARENT = re.compile(
    r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$",
    re.IGNORECASE,
)


def inject_trace_context(
    context: TraceContext,
    carrier: Mapping[str, str] | None = None,
    *,
    sampled: bool = True,
) -> dict[str, str]:
    """Return a copy of a carrier containing a canonical W3C traceparent."""

    result = dict(carrier or {})
    flags = "01" if sampled else "00"
    result["traceparent"] = f"00-{context.trace_id}-{context.span_id[-16:]}-{flags}"
    return result


def extract_trace_context(carrier: Mapping[str, str]) -> TraceContext | None:
    """Parse a supported W3C carrier, rejecting invalid and all-zero IDs."""

    value = next((v for k, v in carrier.items() if k.lower() == "traceparent"), None)
    if value is None:
        return None
    match = _TRACEPARENT.fullmatch(value.strip())
    if match is None:
        return None
    trace_id, span_id, _flags = (item.lower() for item in match.groups())
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return None
    return TraceContext(trace_id=trace_id, span_id=span_id)

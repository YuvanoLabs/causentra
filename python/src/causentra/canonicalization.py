"""Optional RFC 8785 canonicalization for the signing prerequisite."""

from __future__ import annotations

import math
from typing import Any, cast

from .types import JsonValue


def canonicalize_json(value: JsonValue) -> bytes:
    """Return RFC 8785 JCS UTF-8 bytes for the existing JSON value domain.

    This helper is infrastructure only. It does not sign, verify, or alter
    runtime events. Values outside the JSON domain are rejected explicitly.
    """

    _validate_json_value(value)
    try:
        import rfc8785

        return cast(bytes, rfc8785.dumps(value))
    except ImportError as error:
        raise RuntimeError("RFC 8785 support is optional; install causentra[signing]") from error


def _validate_json_value(value: Any) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        if not -(2**53 - 1) <= value <= 2**53 - 1:
            raise ValueError("integer is outside the RFC 8785 interoperable safe range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON values cannot contain non-finite numbers")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            _validate_json_value(item)
        return
    raise TypeError("value must be a Causentra JSON value")

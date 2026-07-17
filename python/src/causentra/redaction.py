"""Recursive privacy controls applied before exporter access."""

from __future__ import annotations

import copy
import re
from typing import Any, cast

from .types import EventAttributes

_SENSITIVE_KEY = re.compile(
    r"(?:^|[._-])(authorization|api[_-]?key|password|secret|cookie|token)(?:$|[._-])",
    re.IGNORECASE,
)


def default_redactor(attributes: EventAttributes) -> EventAttributes:
    """Clone attributes and replace recursively named sensitive fields."""

    cloned = copy.deepcopy(attributes)
    return cast(EventAttributes, _redact_object(cloned))


def _redact_object(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact_object(item) for item in value]
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SENSITIVE_KEY.search(key) else _redact_object(item)
            for key, item in value.items()
        }
    return value

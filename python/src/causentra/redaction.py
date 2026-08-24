"""Recursive privacy controls applied before exporter access."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any, cast

from .types import EventAttributes

_SENSITIVE_KEY = re.compile(
    r"(?:^|[._-])(authorization|api[_-]?key|password|secret|cookie|token)(?:$|[._-])",
    re.IGNORECASE,
)
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9_%+-]+(?:\.[A-Za-z0-9_%+-]+)*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![A-Za-z0-9-])"
)
_CARD = re.compile(r"(?<![A-Za-z0-9])(?:\d[ -]?){12,18}\d(?![A-Za-z0-9])")
_PAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{5}\d{4}[A-Z](?![A-Za-z0-9])", re.IGNORECASE)


def default_redactor(attributes: EventAttributes) -> EventAttributes:
    """Clone attributes and replace recursively named sensitive fields."""

    cloned = copy.deepcopy(attributes)
    return cast(EventAttributes, _redact_object(cloned))


class PolicyRedactor:
    """Opt-in bounded value detector composed with key-based redaction."""

    def __init__(
        self,
        *,
        replacement: str = "[REDACTED]",
        redact_emails: bool = True,
        redact_cards: bool = True,
        redact_pans: bool = True,
        base_redactor: Callable[[EventAttributes], EventAttributes] = default_redactor,
    ) -> None:
        if not replacement:
            raise ValueError("replacement must not be empty")
        self.replacement = replacement
        self.redact_emails = redact_emails
        self.redact_cards = redact_cards
        self.redact_pans = redact_pans
        self.base_redactor = base_redactor

    def __call__(self, attributes: EventAttributes) -> EventAttributes:
        """Clone, apply key redaction, then redact configured value formats."""
        return cast(EventAttributes, _redact_values(self.base_redactor(attributes), self))

    def redact_text(self, value: str) -> str:
        result = value
        if self.redact_cards:
            result = _CARD.sub(self._card_replacement, result)
        if self.redact_emails:
            result = _EMAIL.sub(self.replacement, result)
        if self.redact_pans:
            result = _PAN.sub(self.replacement, result)
        return result

    def _card_replacement(self, match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        return self.replacement if _luhn_valid(digits) else match.group(0)


def _redact_object(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact_object(item) for item in value]
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SENSITIVE_KEY.search(key) else _redact_object(item)
            for key, item in value.items()
        }
    return value


def _redact_values(value: Any, policy: PolicyRedactor) -> Any:
    if isinstance(value, list):
        return [_redact_values(item, policy) for item in value]
    if isinstance(value, dict):
        return {key: _redact_values(item, policy) for key, item in value.items()}
    if isinstance(value, str):
        return policy.redact_text(value)
    return value


def _luhn_valid(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    parity = len(digits) % 2
    for index, character in enumerate(digits):
        digit = int(character)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0

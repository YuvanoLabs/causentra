from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pytest

from causentra import canonicalize_json

_VECTORS = (
    Path(__file__).parents[2] / "packages/sdk/fixtures/signature/v1/canonicalization/vectors.json"
)


def test_rfc8785_vectors_match_utf8_and_sha256() -> None:
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for vector in vectors:
        encoded = canonicalize_json(vector["input"])
        assert encoded.decode("utf-8") == vector["canonical"], vector["name"]
        assert hashlib.sha256(encoded).hexdigest() == vector["sha256"], vector["name"]


@pytest.mark.parametrize(
    "value",
    [math.nan, math.inf, 2**53, -(2**53), ("tuple",)],
)
def test_canonicalizer_rejects_non_interoperable_values(value: Any) -> None:
    with pytest.raises((TypeError, ValueError), match=r"JSON|finite|safe range"):
        canonicalize_json(value)  # type: ignore[arg-type]


def test_canonicalizer_rejects_non_string_object_keys() -> None:
    with pytest.raises(TypeError, match="keys must be strings"):
        canonicalize_json({1: "not a JSON object"})  # type: ignore[arg-type]

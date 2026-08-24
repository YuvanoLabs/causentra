from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

import causentra.signatures as signatures
from causentra import sign_detached_artifact, verify_detached_signature

ARTIFACT: dict[str, Any] = {
    "kind": "trace-bundle",
    "identity": "trace:test-signature",
    "schemaVersion": "1.0",
    "value": {"message": "safe", "nested": [1, True, None]},
}


def keys() -> tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
    private = ec.generate_private_key(ec.SECP256R1())
    return private, private.public_key()


def signed() -> tuple[dict[str, Any], ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
    private, public = keys()
    return (
        sign_detached_artifact(
            ARTIFACT, key_id="local:test-key", key_version="1", private_key=private
        ),
        private,
        public,
    )


def resolve(public: Any) -> Callable[..., dict[str, Any]]:
    return lambda *_: {"publicKey": public}


def test_signs_and_verifies_without_private_material_in_envelope() -> None:
    envelope, private, public = signed()
    assert envelope["signatureEncoding"] == "base64-der"
    assert "PRIVATE KEY" not in str(envelope)
    assert verify_detached_signature(ARTIFACT, envelope, resolve_key=resolve(public)) == {
        "verified": True,
        "keyId": "local:test-key",
        "keyVersion": "1",
    }
    assert private is not None


def test_rejects_artifact_and_metadata_tampering() -> None:
    envelope, _, public = signed()
    tampered = {**ARTIFACT, "value": {"message": "tampered"}}
    assert (
        verify_detached_signature(tampered, envelope, resolve_key=resolve(public))["reason"]
        == "artifact-digest-mismatch"
    )
    metadata = {**envelope, "keyVersion": "2"}
    assert (
        verify_detached_signature(ARTIFACT, metadata, resolve_key=resolve(public))["reason"]
        == "invalid-signature"
    )


def test_rejects_wrong_unknown_revoked_and_private_keys() -> None:
    envelope, private, public = signed()
    _, wrong_public = keys()
    assert (
        verify_detached_signature(ARTIFACT, envelope, resolve_key=resolve(wrong_public))["reason"]
        == "invalid-signature"
    )
    assert (
        verify_detached_signature(ARTIFACT, envelope, resolve_key=lambda *_: None)["reason"]
        == "unknown-key"
    )
    assert (
        verify_detached_signature(
            ARTIFACT, envelope, resolve_key=lambda *_: {"publicKey": public, "revoked": True}
        )["reason"]
        == "revoked-key"
    )
    assert (
        verify_detached_signature(ARTIFACT, envelope, resolve_key=resolve(private))["reason"]
        == "invalid-key"
    )


def test_rejects_schema_valid_unsupported_profile_and_bad_base64() -> None:
    envelope, _, public = signed()
    assert (
        verify_detached_signature(
            ARTIFACT,
            {**envelope, "algorithm": "ED25519", "signatureEncoding": "base64-raw"},
            resolve_key=resolve(public),
        )["reason"]
        == "unsupported-algorithm"
    )
    assert (
        verify_detached_signature(
            ARTIFACT, {**envelope, "signatureEncoding": "base64-raw"}, resolve_key=resolve(public)
        )["reason"]
        == "unsupported-encoding"
    )
    assert (
        verify_detached_signature(
            ARTIFACT, {**envelope, "signature": "AAAA="}, resolve_key=resolve(public)
        )["reason"]
        == "malformed-envelope"
    )
    assert (
        verify_detached_signature(
            ARTIFACT, {**envelope, "extra": True}, resolve_key=resolve(public)
        )["reason"]
        == "malformed-envelope"
    )


def test_rejects_runtime_shapes_and_key_curves() -> None:
    private, _ = keys()
    with pytest.raises(ValueError, match="unsupported artifact kind"):
        sign_detached_artifact(
            {**ARTIFACT, "kind": "bad"}, key_id="key", key_version="1", private_key=private
        )
    with pytest.raises(TypeError, match="exact JSON mapping"):
        sign_detached_artifact(
            dict(ARTIFACT, extra=True), key_id="key", key_version="1", private_key=private
        )
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(TypeError, match="EC P-256"):
        sign_detached_artifact(ARTIFACT, key_id="key", key_version="1", private_key=rsa_key)


def test_rejects_custom_mapping_equivalent_objects() -> None:
    envelope, _, public = signed()

    class CustomDict(dict[str, Any]):
        pass

    assert (
        verify_detached_signature(ARTIFACT, CustomDict(envelope), resolve_key=resolve(public))[
            "reason"
        ]
        == "malformed-envelope"
    )


def test_missing_optional_crypto_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        signatures, "_crypto", lambda: (_ for _ in ()).throw(RuntimeError("optional"))
    )
    with pytest.raises(RuntimeError, match="optional"):
        sign_detached_artifact(ARTIFACT, key_id="key", key_version="1", private_key=b"not-a-key")

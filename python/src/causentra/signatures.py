"""Optional detached ECDSA P-256 signatures for finalized artifacts."""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Callable, Mapping
from typing import Any, Literal, TypedDict, cast

from .canonicalization import canonicalize_json
from .types import JsonValue

SignatureAlgorithm = Literal["ECDSA_P256_SHA256"]
SignatureEncoding = Literal["base64-der"]
SignatureArtifactKind = Literal["event-batch", "trace-bundle"]


class DetachedArtifact(TypedDict):
    kind: SignatureArtifactKind
    identity: str
    schemaVersion: Literal["1.0"]
    value: JsonValue


class ArtifactDescriptor(TypedDict):
    kind: SignatureArtifactKind
    identity: str
    schemaVersion: Literal["1.0"]
    sha256: str


class DetachedSignatureEnvelope(TypedDict):
    signatureVersion: Literal["causentra.signature/v1"]
    artifact: ArtifactDescriptor
    canonicalization: Literal["RFC8785-JCS"]
    algorithm: str
    keyId: str
    keyVersion: str
    signatureEncoding: str
    signature: str


VerificationKey = Mapping[str, Any]

SignatureKeyResolver = Callable[[str, str], VerificationKey | None]


class SignatureVerificationResult(TypedDict, total=False):
    verified: bool
    keyId: str
    keyVersion: str
    reason: str


_ID_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:/-"
_VERSION_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
_ENVELOPE_KEYS = frozenset(
    {
        "signatureVersion",
        "artifact",
        "canonicalization",
        "algorithm",
        "keyId",
        "keyVersion",
        "signatureEncoding",
        "signature",
    }
)
_ARTIFACT_KEYS = frozenset({"kind", "identity", "schemaVersion", "sha256"})


def sign_detached_artifact(
    artifact: Mapping[str, Any],
    *,
    key_id: str,
    key_version: str,
    private_key: Any,
) -> DetachedSignatureEnvelope:
    """Sign a JSON artifact with an opt-in local ECDSA P-256 private key."""

    _validate_artifact(artifact)
    _validate_identity(key_id, _ID_CHARS, "key ID")
    _validate_identity(key_version, _VERSION_CHARS, "key version")
    private = _load_private_key(private_key)
    typed_artifact = cast(DetachedArtifact, artifact)
    digest = _digest_artifact(typed_artifact["value"])
    descriptor = _descriptor(typed_artifact, digest, key_id, key_version)
    signature = private.sign(_canonical_descriptor(descriptor), _ecdsa_sha256())
    return {
        "signatureVersion": "causentra.signature/v1",
        "artifact": {
            "kind": typed_artifact["kind"],
            "identity": typed_artifact["identity"],
            "schemaVersion": "1.0",
            "sha256": digest,
        },
        "canonicalization": "RFC8785-JCS",
        "algorithm": "ECDSA_P256_SHA256",
        "keyId": key_id,
        "keyVersion": key_version,
        "signatureEncoding": "base64-der",
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def verify_detached_signature(
    artifact: Mapping[str, Any],
    envelope: Any,
    *,
    resolve_key: SignatureKeyResolver,
) -> SignatureVerificationResult:
    """Verify a detached signature and return a bounded fail-closed result."""

    try:
        _validate_artifact(artifact)
    except (TypeError, ValueError):
        return {"verified": False, "reason": "malformed-envelope"}
    parsed = _parse_envelope(envelope)
    if parsed is None:
        return {"verified": False, "reason": "malformed-envelope"}
    if parsed["algorithm"] != "ECDSA_P256_SHA256":
        return {"verified": False, "reason": "unsupported-algorithm"}
    if parsed["signatureEncoding"] != "base64-der":
        return {"verified": False, "reason": "unsupported-encoding"}
    signature = _decode_signature(parsed["signature"])
    if signature is None:
        return {"verified": False, "reason": "malformed-envelope"}
    typed_artifact = cast(DetachedArtifact, artifact)
    digest = _digest_artifact(typed_artifact["value"])
    covered = parsed["artifact"]
    if (
        digest != covered["sha256"]
        or covered["kind"] != typed_artifact["kind"]
        or covered["identity"] != typed_artifact["identity"]
        or covered["schemaVersion"] != typed_artifact["schemaVersion"]
    ):
        return {"verified": False, "reason": "artifact-digest-mismatch"}
    try:
        key = resolve_key(parsed["keyId"], parsed["keyVersion"])
    except Exception:
        return {"verified": False, "reason": "key-resolution-failed"}
    if key is None:
        return {"verified": False, "reason": "unknown-key"}
    if key.get("revoked") is True:
        return {"verified": False, "reason": "revoked-key"}
    public_material = key.get("publicKey")
    if public_material is None:
        return {"verified": False, "reason": "invalid-key"}
    try:
        public = _load_public_key(public_material)
    except Exception:
        return {"verified": False, "reason": "invalid-key"}
    try:
        valid = _verify_signature(
            public,
            signature,
            _canonical_descriptor(_envelope_descriptor(parsed)),
        )
    except Exception:
        return {"verified": False, "reason": "invalid-key"}
    if not valid:
        return {"verified": False, "reason": "invalid-signature"}
    return {"verified": True, "keyId": parsed["keyId"], "keyVersion": parsed["keyVersion"]}


def _crypto() -> tuple[Any, Any, Any, Any, Any]:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.ec import (
            EllipticCurvePrivateKey,
            EllipticCurvePublicKey,
        )
    except ImportError as error:
        raise RuntimeError("ECDSA support is optional; install causentra[signing]") from error
    return hashes, serialization, ec, EllipticCurvePrivateKey, EllipticCurvePublicKey


def _verify_signature(public: Any, signature: bytes, message: bytes) -> bool:
    try:
        from cryptography.exceptions import InvalidSignature
    except ImportError as error:
        raise RuntimeError("ECDSA support is optional; install causentra[signing]") from error
    try:
        public.verify(signature, message, _ecdsa_sha256())
    except InvalidSignature:
        return False
    return True


def _ecdsa_sha256() -> Any:
    hashes, _, ec, _, _ = _crypto()
    return ec.ECDSA(hashes.SHA256())


def _load_private_key(value: Any) -> Any:
    _, serialization, ec, private_type, _ = _crypto()
    if isinstance(value, private_type):
        key = value
    elif isinstance(value, (bytes, str)):
        pem = value.encode("ascii") if isinstance(value, str) else value
        key = serialization.load_pem_private_key(pem, password=None)
    else:
        raise TypeError("private key must be an EC P-256 key")
    if not isinstance(key, private_type) or not isinstance(key.curve, ec.SECP256R1):
        raise TypeError("private key must be an EC P-256 key")
    return key


def _load_public_key(value: Any) -> Any:
    _, serialization, ec, private_type, public_type = _crypto()
    if isinstance(value, private_type):
        raise TypeError("verification key must be public")
    if isinstance(value, public_type):
        key = value
    elif isinstance(value, (bytes, str)):
        pem = value.encode("ascii") if isinstance(value, str) else value
        try:
            serialization.load_pem_private_key(pem, password=None)
        except (ValueError, TypeError):
            key = serialization.load_pem_public_key(pem)
        else:
            raise TypeError("verification key must be public")
    else:
        raise TypeError("verification key must be an EC public key or PEM")
    if not isinstance(key, public_type) or not isinstance(key.curve, ec.SECP256R1):
        raise TypeError("public key must be an EC P-256 key")
    return key


def _digest_artifact(value: JsonValue) -> str:
    return hashlib.sha256(canonicalize_json(value)).hexdigest()


def _descriptor(
    artifact: DetachedArtifact, digest: str, key_id: str, key_version: str
) -> dict[str, JsonValue]:
    return {
        "signatureVersion": "causentra.signature/v1",
        "artifact": {
            "kind": artifact["kind"],
            "identity": artifact["identity"],
            "schemaVersion": "1.0",
            "sha256": digest,
        },
        "canonicalization": "RFC8785-JCS",
        "algorithm": "ECDSA_P256_SHA256",
        "keyId": key_id,
        "keyVersion": key_version,
        "signatureEncoding": "base64-der",
    }


def _envelope_descriptor(envelope: DetachedSignatureEnvelope) -> dict[str, JsonValue]:
    return {
        "signatureVersion": envelope["signatureVersion"],
        "artifact": envelope["artifact"],
        "canonicalization": envelope["canonicalization"],
        "algorithm": envelope["algorithm"],
        "keyId": envelope["keyId"],
        "keyVersion": envelope["keyVersion"],
        "signatureEncoding": envelope["signatureEncoding"],
    }


def _canonical_descriptor(descriptor: Mapping[str, Any]) -> bytes:
    return canonicalize_json(cast(JsonValue, dict(descriptor)))


def _validate_artifact(value: Mapping[str, Any]) -> None:
    if type(value) is not dict or set(value) != {"kind", "identity", "schemaVersion", "value"}:
        raise TypeError("artifact must be an exact JSON mapping")
    if value["kind"] not in ("event-batch", "trace-bundle"):
        raise ValueError("unsupported artifact kind")
    if not isinstance(value["identity"], str) or not _matches(value["identity"], _ID_CHARS, 256):
        raise ValueError("invalid artifact identity")
    if value["schemaVersion"] != "1.0":
        raise ValueError("unsupported artifact schema")
    canonicalize_json(cast(JsonValue, value["value"]))


def _parse_envelope(value: Any) -> DetachedSignatureEnvelope | None:
    if type(value) is not dict or set(value) != _ENVELOPE_KEYS:
        return None
    artifact = value["artifact"]
    if type(artifact) is not dict or set(artifact) != _ARTIFACT_KEYS:
        return None
    if (
        value["signatureVersion"] != "causentra.signature/v1"
        or value["canonicalization"] != "RFC8785-JCS"
    ):
        return None
    if not isinstance(value["algorithm"], str) or not isinstance(value["signatureEncoding"], str):
        return None
    if not isinstance(value["keyId"], str) or not _matches(value["keyId"], _ID_CHARS, 256):
        return None
    if not isinstance(value["keyVersion"], str) or not _matches(
        value["keyVersion"], _VERSION_CHARS, 64
    ):
        return None
    if artifact["kind"] not in ("event-batch", "trace-bundle") or not isinstance(
        artifact["identity"], str
    ):
        return None
    if (
        artifact["schemaVersion"] != "1.0"
        or not isinstance(artifact["sha256"], str)
        or not _matches(artifact["sha256"], "0123456789abcdef", 64)
    ):
        return None
    if not isinstance(value["signature"], str):
        return None
    return cast(DetachedSignatureEnvelope, value)


def _decode_signature(value: str) -> bytes | None:
    if len(value) < 4 or len(value) > 2048 or len(value) % 4:
        return None
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        return None
    return decoded if decoded and base64.b64encode(decoded).decode("ascii") == value else None


def _validate_identity(value: str, chars: str, label: str) -> None:
    if not _matches(value, chars, 256 if label == "key ID" else 64):
        raise ValueError(f"invalid {label}")


def _matches(value: str, chars: str, maximum: int) -> bool:
    return (
        bool(value)
        and len(value) <= maximum
        and value[0].isalnum()
        and all(char in chars for char in value)
    )

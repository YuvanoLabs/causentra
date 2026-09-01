from __future__ import annotations

import base64
import hashlib
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from causentra import (
    KmsDigestSigner,
    VaultTransitDigestSigner,
    sign_detached_artifact_with_signer,
    verify_detached_signature,
)

ARTIFACT: dict[str, Any] = {
    "kind": "trace-bundle",
    "identity": "trace:external-signer",
    "schemaVersion": "1.0",
    "value": {"safe": True},
}


class _Kms:
    def __init__(self, private: ec.EllipticCurvePrivateKey) -> None:
        self.private = private
        self.request: dict[str, Any] | None = None

    def sign(self, **kwargs: Any) -> dict[str, bytes]:
        self.request = kwargs
        return {
            "Signature": self.private.sign(
                kwargs["Message"], ec.ECDSA(utils.Prehashed(hashes.SHA256()))
            )
        }


def test_kms_digest_adapter_selects_ecdsa_sha256_digest_mode() -> None:
    private = ec.generate_private_key(ec.SECP256R1())
    client = _Kms(private)
    envelope = sign_detached_artifact_with_signer(
        ARTIFACT,
        key_id="kms:telemetry",
        key_version="7",
        sign_descriptor=KmsDigestSigner(client, "arn:aws:kms:example"),
    )
    assert client.request is not None
    assert client.request["KeyId"] == "arn:aws:kms:example"
    assert client.request["MessageType"] == "DIGEST"
    assert client.request["SigningAlgorithm"] == "ECDSA_SHA_256"
    assert len(client.request["Message"]) == hashlib.sha256().digest_size
    assert verify_detached_signature(
        ARTIFACT,
        envelope,
        resolve_key=lambda *_: {"publicKey": private.public_key()},
    )["verified"] is True


def test_vault_transit_adapter_decodes_versioned_signature_without_secret_logging() -> None:
    private = ec.generate_private_key(ec.SECP256R1())
    captured: list[tuple[str, bytes]] = []

    def request(key_name: str, digest: bytes) -> str:
        captured.append((key_name, digest))
        signature = private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return f"vault:v4:{base64.b64encode(signature).decode('ascii')}"

    envelope = sign_detached_artifact_with_signer(
        ARTIFACT,
        key_id="vault:telemetry",
        key_version="4",
        sign_descriptor=VaultTransitDigestSigner("telemetry", request),
    )
    assert captured[0][0] == "telemetry"
    assert len(captured[0][1]) == hashlib.sha256().digest_size
    assert verify_detached_signature(
        ARTIFACT,
        envelope,
        resolve_key=lambda *_: {"publicKey": private.public_key()},
    )["verified"] is True

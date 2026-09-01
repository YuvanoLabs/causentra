"""Dependency-free adapters for externally managed ECDSA signing services."""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class KmsSignClient(Protocol):
    """Small structural subset of the AWS KMS ``Sign`` client method."""

    def sign(self, **kwargs: Any) -> Mapping[str, Any]: ...


VaultDigestRequest = Callable[[str, bytes], str | bytes]


@dataclass(frozen=True, slots=True)
class KmsDigestSigner:
    """Use an AWS KMS ECDSA P-256 key in digest mode without importing boto3."""

    client: KmsSignClient
    key_arn: str

    def __post_init__(self) -> None:
        if not self.key_arn.strip() or len(self.key_arn) > 2_048:
            raise ValueError("key_arn must be a bounded non-empty string")

    def __call__(self, descriptor: bytes) -> bytes:
        digest = hashlib.sha256(descriptor).digest()
        response = self.client.sign(
            KeyId=self.key_arn,
            Message=digest,
            MessageType="DIGEST",
            SigningAlgorithm="ECDSA_SHA_256",
        )
        signature = response.get("Signature")
        if not isinstance(signature, bytes) or not 8 <= len(signature) <= 2_048:
            raise ValueError("KMS returned an invalid ECDSA signature")
        return signature


@dataclass(frozen=True, slots=True)
class VaultTransitDigestSigner:
    """Adapt an explicit Vault Transit digest callback to the signer contract.

    ``request`` should invoke a configured Vault Transit key with SHA-2-256
    digest semantics and return its ``vault:v<version>:<base64>`` signature.
    HTTP authentication, retries and endpoint selection stay with the caller.
    """

    key_name: str
    request: VaultDigestRequest

    def __post_init__(self) -> None:
        if not self.key_name.strip() or len(self.key_name) > 256:
            raise ValueError("key_name must be a bounded non-empty string")

    def __call__(self, descriptor: bytes) -> bytes:
        response = self.request(self.key_name, hashlib.sha256(descriptor).digest())
        value = response.decode("ascii") if isinstance(response, bytes) else response
        if not isinstance(value, str):
            raise ValueError("Vault Transit returned a non-string signature")
        prefix, separator, encoded = value.rpartition(":")
        if not separator or not prefix.startswith("vault:v") or not encoded:
            raise ValueError("Vault Transit returned an invalid signature envelope")
        try:
            signature = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("Vault Transit returned invalid base64 signature bytes") from error
        if not 8 <= len(signature) <= 2_048:
            raise ValueError("Vault Transit returned an invalid ECDSA signature")
        return signature

# ADR-006: Versioned detached telemetry signatures

Status: accepted (contract/fixtures and TypeScript local ECDSA implementation complete; Python/KMS/collector enforcement pending)

## Context

The v1 `RuntimeEvent` contract is shared by Python, TypeScript, OTLP and local
storage. Adding signing fields to that object would change schema 1.0 and make
otherwise compatible producers diverge. Signatures therefore belong to a
versioned transport/export envelope that references, but does not mutate, the
covered artifact.

Two integrity problems must remain distinct:

1. **Batch-in-transit integrity** protects an accepted event batch while it is
   moving between a producer, spool, broker or collector. A shared-secret HMAC
   can detect mutation when all parties possess the secret. It is integrity
   authentication, not audit provenance or non-repudiation.
2. **Finalized trace/export integrity** binds a completed trace bundle or
   exported artifact to an asymmetric signing identity. A verifier with the
   public key can check that the artifact has not changed and that the claimed
   signing key produced the signature. This is the audit-provenance profile.

The repository currently has event/payload SHA-256 digests for idempotency and
API-key authentication, but no detached signature protocol. The existing event
schema, project isolation and local-first operation must remain compatible while
this capability is designed.

## Decision

Define a separate, versioned detached signature envelope. The envelope is not a
`RuntimeEvent` and must not be embedded in schema 1.0 events.

The signed bytes are RFC 8785 JSON Canonicalization Scheme (JCS) bytes of an
explicit artifact descriptor and covered-artifact identity. Implementations
must not rely on ad-hoc language JSON serialization. JCS rules, including
property ordering, number serialization and UTF-8 generation, are part of the
cross-language contract; interoperability fixtures are required before any
production signer is shipped.

The v1 envelope design is:

```json
{
  "signatureVersion": "causentra.signature/v1",
  "artifact": {
    "kind": "trace-bundle",
    "identity": "<stable artifact identity>",
    "schemaVersion": "1.0",
    "sha256": "<lowercase digest of canonical artifact bytes>"
  },
  "canonicalization": "RFC8785-JCS",
  "algorithm": "ECDSA_P256_SHA256",
  "keyId": "<non-secret key identity>",
  "keyVersion": "<operator key version>",
  "signatureEncoding": "<algorithm-specific encoding>",
  "signature": "<base64 signature bytes>"
}
```

The exact descriptor field set and encoding are implementation tasks, but every
field that affects verification must be covered by the canonical signed bytes.
The envelope carries algorithm, key identity/version, canonicalization/version,
signature bytes and covered-artifact identity. Timestamps, validity windows and
issuer metadata may be added only when their semantics and clock handling are
specified in the implementation contract.

The enterprise/FIPS-compatible baseline is ECDSA P-256 with SHA-256. AWS KMS
exposes `ECDSA_SHA_256` for asymmetric `SIGN_VERIFY` keys, and Vault Transit
supports `ecdsa-p256`; these are integration targets, not current dependencies
or certification claims. Ed25519 may be an optional non-FIPS profile only when a
deployment policy permits it. The product must never imply that Causentra is
FIPS certified merely because a deployment uses a compatible primitive.

Key purposes are separate: audit-signing keys, batch HMAC keys and encryption
keys must have distinct identities and policy grants. Key rotation, revocation,
unknown-key handling and retention of public verification material follow an
operator-managed lifecycle. No private key, raw secret, bearer key or KMS/Vault
credential may be logged, persisted in telemetry, or included in fixtures.

Application instrumentation remains fail-open: a signing or verification
failure must not replace the caller's result or exception. A collector/operator
that explicitly configures `requireVerification` must reject or quarantine an
unverifiable batch/export and report a bounded reason; it must not silently
downgrade to unsigned acceptance. Legacy unsigned artifacts remain readable in
an explicit compatibility mode and are labeled unsigned.

## Consequences

- RuntimeEvent 1.0 fixtures, adapters and OTLP mappings remain unchanged.
- Producers may attach a detached envelope to transport batches or exported
  bundles without forcing every local event to carry cryptographic metadata.
- A finalized export can provide audit provenance; an HMAC-protected batch only
  provides shared-secret integrity and must never be described as
  non-repudiation.
- JCS support becomes a cross-language dependency/implementation boundary and
  requires golden vectors for Python and TypeScript.
- KMS/Vault calls may be unavailable or eventually consistent; signing and
  verification states must be observable without leaking secrets.
- This ADR authorizes design and fixtures only. It does not add a dependency,
  promise a security certification, or claim that production signing exists.

## Incremental implementation and acceptance fixtures

1. Specify the descriptor, envelope schema, artifact identity, JCS profile,
   signature encoding (standard padded `base64-der`) and status/error vocabulary. **Completed:**
   `packages/sdk/schema/signature-v1.schema.json` and language-neutral fixtures
   define the standalone contract. The TypeScript local signer/verifier now consumes this contract; Python and remote signer/verifier implementations remain pending.
2. Add RFC 8785 JCS golden vectors, including nested objects, Unicode, numbers,
   property-order permutations, `-0` normalization and invalid JSON. Acceptance:
   Python and TypeScript produce byte-identical canonical output.
3. **Completed for TypeScript local use:** add the opt-in ECDSA P-256 signer/verifier using caller-supplied keys. Acceptance includes valid, tampered, wrong-key, unknown-key, revoked-key, and invalid-envelope tests. Python parity, KMS/Vault adapters and collector enforcement remain follow-up work.
4. Add detached signing to export/batch interfaces without changing
   RuntimeEvent. Acceptance: export/import preserves the artifact identity and
   signature; unsigned legacy mode is explicit.
5. Add optional KMS/Vault signer/verifier adapters. Acceptance: mocked contract
   tests cover algorithm/key-version selection, digest-vs-raw message mode,
   transient errors and no-secret logging; live tests remain operator-supplied.
6. Add collector `requireVerification` rejection/quarantine behavior and audit
   metrics. Acceptance: unverifiable payloads cannot enter the verified path,
   are not silently downgraded, and application-side failures remain fail-open.

## Implementation-readiness checklist

- [x] Freeze the v1 envelope schema, signed descriptor fields and artifact identity shape.
- [x] Select and test exact optional RFC 8785 implementations: TypeScript
      `canonicalize@4.0.0` and Python `rfc8785>=0.1.4,<0.2`.
- [x] Publish cross-language golden vectors, including invalid-number policy.
- [ ] Confirm ECDSA P-256/SHA-256 encoding and KMS/Vault digest-mode semantics.
- [ ] Define public-key distribution, key-purpose policy, rotation and revocation
      records without persisting private material.
- [ ] Define fail-open application behavior and collector reject/quarantine
      observability for every verification failure class.
- [ ] Add legacy unsigned compatibility tests and explicit unsigned labeling.
- [ ] Complete threat review and target-infrastructure/interoperability tests.
- [ ] Keep all KMS/Vault/live-broker checks operator-supplied; do not claim
      certification from algorithm selection alone.

The canonicalization helpers are prerequisite infrastructure only. They do not
sign or verify artifacts, and their dependency/security/maintenance review is a
release gate.

## References

- [RFC 8785 — JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785.html)
- [NIST FIPS 186-5 — Digital Signature Standard](https://csrc.nist.gov/pubs/fips/186-5/final)
- [NIST SP 800-57 Part 1 Revision 5 — Recommendation for Key Management](https://csrc.nist.gov/pubs/sp/800/57/pt1/r5/final)
- [AWS KMS Sign API](https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html)
- [HashiCorp Vault Transit secrets engine](https://developer.hashicorp.com/vault/docs/secrets/transit)
- [HashiCorp Vault Transit HTTP API](https://developer.hashicorp.com/vault/api-docs/secret/transit)

# Local assurance controls

These controls are implemented for the supported single-node Python collector.
They are opt-in and do not imply a hosted control plane, SSO, compliance
certification, or an independently reviewed production deployment.

## Signed batch ingestion

The detached `causentra.signature/v1` envelope covers the normalized event
batch: `transportVersion`, the idempotency `batchId`, and its `events`. A
collector can accept legacy unsigned batches and labels them `unsigned`, or it
can fail closed with `signatures.requireVerification: true`. Invalid, revoked,
unknown, and malformed signatures are rejected before event storage.

The Python `signing` extra provides local ECDSA P-256 signing. The explicit
`KmsDigestSigner` and `VaultTransitDigestSigner` adapters accept caller-managed
clients/callbacks and sign SHA-256 descriptor digests; neither stores a private
key, token, endpoint, or cloud credential. Live key-management configuration,
public-key distribution, rotation, and revocation are operator responsibilities.

`HttpTransport(batch_signature_factory=...)` invokes the caller-supplied
factory for each durable batch before delivery, so a verification-required
collector can be used with `DurableTransportExporter` without placing a
signature inside RuntimeEvent 1.0.

```json
{
  "signatures": {
    "requireVerification": true,
    "keys": [{
      "id": "telemetry-prod",
      "version": "7",
      "publicKey": "-----BEGIN PUBLIC KEY-----\\n...\\n-----END PUBLIC KEY-----"
    }]
  }
}
```

## Scoped collector access

Each hash-only API key has a project and either a compatibility `project` role
or a least-privilege role/scope set:

| Scope | Capability |
|---|---|
| `events:ingest` | Submit event batches |
| `traces:read` | List and read project traces with attributes stripped |
| `traces:debug` | Include stored attributes in trace details |
| `traces:delete` | Delete a project trace |
| `metrics:read` | Read process metrics |
| `audit:read` | Read metadata-only authorization decisions |

`reader`, `debug`, and `writer` roles supply the corresponding default scopes;
`operator` is a single-node operator role. All reads/deletes remain project
scoped. `GET /v1/audit` is restricted to `audit:read` and records no event
payloads. This is deliberately not organization/team RBAC.

## Loop aggregation

Wrap a normal exporter in `LoopAggregationExporter` only after inspecting
repetition evidence. It keeps the initial operation pairs, aggregates later
consecutive empty leaf pairs, and emits a regular `custom.loop.aggregated`
event at trace completion. The summary contains the operation family/name,
repeat count, represented event count, and first/last sequence; no source
attributes are copied. Nested, payload-bearing, interrupted, and nonmatching
lifecycles pass through unchanged. Application behavior is never suppressed or
changed.

## Offline evaluation and price estimates

`evaluate_trace` and `evaluate_trace_bundle` evaluate one trace with explicit
rules only: required event types, error limits, duration limits, and event-count
minimums. Their deterministic score attributes can be written as an
`evaluation.score` extension event by the caller. They do not use an LLM or a
network service.

`PriceCatalog` is caller-supplied and versioned. Rates use integer
microdollars-per-million tokens with effective dates. Unknown model/rate and
unsupported cached-token pricing return no estimate. A result is explicitly
labelled `causentra.cost.basis = catalog_estimate`; Causentra ships no provider
price table and never guesses a price.

## Production boundary

Local tests prove the contracts above. Independent security review, target TLS
and restore testing, external onboarding, publisher protection, package
provenance, and a representative soak remain evidence gates before a final
public package release. See [production-readiness verification](36-production-readiness-verification.md).

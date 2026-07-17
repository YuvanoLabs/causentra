# Data, API, and security design

## Event envelope

Every event contains `schemaVersion`, `eventId`, `traceId`, optional `parentSpanId`, `spanId`, `sessionId`, `sequence`, `timestamp`, `type`, `name`, `status`, `durationMs`, and bounded JSON attributes. Names identify operations; types provide stable semantics.

Initial types: `trace.start`, `trace.end`, `span.start`, `span.end`, `agent.*`, `model.*`, `tool.*`, `error`, and `custom`.

The SDK does not automatically capture prompts, model outputs, tool arguments, environment variables, or hidden reasoning. Applications may add payloads explicitly after redaction.

## Local inspection API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness and store counts |
| `POST` | `/v1/events` | Accept `{ events: Event[] }` |
| `POST` | `/v1/traces` | Accept OTLP/HTTP JSON or protobuf traces, optionally gzip-compressed |
| `GET` | `/api/traces?limit=50` | Recent trace summaries; safe metadata search and framework/provider/model/status/session/tool filters |
| `GET` | `/api/traces/:traceId` | Summary and ordered events |
| `GET` | `/api/traces/:traceId/export` | Versioned portable trace bundle |
| `DELETE` | `/api/traces/:traceId` | Delete one complete local trace |
| `POST` | `/api/traces/import` | Validate and import one portable bundle |
| `POST` | `/api/retention/prune` | Explicitly keep only the newest N traces |

Native API errors use `{ "error": { "code": string, "message": string } }`. Native ingestion rejects the entire batch when any event is invalid. OTLP ingestion returns the same media type as the request and uses the OTLP `partial_success` contract for rejected spans.

## Authenticated Python collector API

| Method | Path | Authorization | Purpose |
|---|---|---|---|
| `GET` | `/health` | None | Process liveness |
| `GET` | `/ready` | None | SQLite integrity/readiness |
| `POST` | `/v1/events` | Project bearer key | Atomic, idempotent batch ingestion |
| `GET` | `/v1/traces?limit=50` | Project bearer key | Project-scoped summaries |
| `GET` | `/v1/traces/:traceId` | Project bearer key | Project-scoped ordered events |
| `DELETE` | `/v1/traces/:traceId` | Project bearer key | Delete one project trace |
| `GET` | `/metrics` | Operator bearer key | Process and scoped storage metrics |

Only SHA-256 key digests are configured. Keys should be randomly generated with at least 256 bits of entropy. Batch/event uniqueness includes project scope; identifier reuse with different bytes is a conflict. JSON fields and types are strict. Body, batch, request rate, event rate, concurrency, socket time, total store, and per-project store limits are configurable. See [Python collector OpenAPI](openapi-collector.yaml).

OTLP conversion preserves trace/span/parent IDs, timestamps, status, service, instrumentation scope, provider, model and usage facts. It omits known content-bearing GenAI, OpenInference, LangSmith, tool and exception fields before applying recursive redaction. This is a safe metadata bridge, not lossless archival of arbitrary OTLP span content.

Trace-list search and filters operate only on normalized summary facets. `q` searches trace, service, framework, provider, model, tool and agent names; it never indexes prompt, output, arbitrary attributes, or error messages. Framework, provider, model and tool values use bounded case-insensitive substring matching; status is an enum and session is an exact canonical identifier. Invalid bounded values receive `invalid_trace_filter` rather than widening a query silently.

## Compatibility

- Semantic version the envelope separately from packages.
- Additive optional fields are minor changes.
- Changed meaning, removal, or required fields are major changes.
- Readers preserve unknown event types and attributes.
- Maintain shared fixtures and cross-language compatibility tests for every schema change.

## Data lifecycle

| Class | M0 default | Cloud target |
|---|---|---|
| Event metadata | Local until explicit trace deletion/pruning or operator database lifecycle | Plan-based 7/30/90/custom days |
| Explicit payloads | Same as event | Separately configurable; encryption required |
| Audit data | Not applicable | ≥365 days, immutable tier |
| Billing aggregates | Not applicable | Contract and tax retention policy |

Deletion in cloud must cover primary stores, projections, caches, and scheduled backup expiry, with a deletion receipt.

## Threat model

| Threat | M0 control | Cloud control |
|---|---|---|
| Sensitive prompt leakage | Opt-in payloads, redactor | Policy redaction, DLP patterns, field encryption |
| Network exposure | Local UI collector is loopback by default; Python remote collector requires TLS and bearer keys | TLS, scoped ingest keys, WAF |
| Malformed/oversized input | Schema and 1 MiB limits | Gateway limits and quotas |
| Cross-project access | Hashed key maps to one project; every store/query key is scoped | Tenant-scoped authorization and store keys |
| Key theft | Digests at rest; TLS remotely; key values never logged | Rotation, short-lived admin tokens |
| Plugin supply chain | Explicit trust, SHA-256 artifacts, minimal environment, no shell, process protocol | Signatures, container/OS sandbox, policy/audit |
| Replay side effects | Stored-event redelivery only; idempotent handlers required | Tool execution remains a separate approved product boundary |
| Dependency compromise | Lockfile and audit | SBOM, provenance, signing, continuous scanning |

## Security roadmap

Public beta requires dependency scanning, secret scanning, coordinated disclosure, abuse limits, security contact, and an external review of ingestion. Cloud GA requires SSO-ready identity, RBAC, audit logging, encryption in transit/at rest, backup restore tests, incident response, subprocessors, and privacy terms. Enterprise readiness then adds SAML/OIDC, SCIM, customer-managed keys where justified, residency, private networking, and SOC 2 evidence collection.

# Solution architecture

## Architecture objectives

- Keep application instrumentation independent of storage and UI.
- Preserve a portable, versioned semantic contract.
- Make local use dependency-light and offline-capable.
- Allow managed ingestion and advanced controls without replacing SDKs.
- Degrade telemetry without breaking the instrumented application.

## Public Python logical design

```text
Instrumented app / native framework adapter / OTel source
  -> RuntimeEvent + W3C context + privacy allowlist
  -> durable SQLite producer outbox
  -> HTTP | WebSocket | Kafka | NATS | Redis | MQTT
  -> authenticated collector or durable EventEngine
  -> project-scoped store / idempotent handler / process plugin

Local inspection peer:
  -> loopback Node.js collector -> causal REST API -> dashboard / CLI

Alternative export: redacted events -> official OpenTelemetry SDK bridge -> OTLP/HTTP protobuf
Standards ingress: OTel/OpenInference producer -> OTLP/HTTP JSON or protobuf -> privacy filter -> common event store
```

| Component | Responsibility | Boundary |
|---|---|---|
| SDK | Context, lifecycle events, redaction, export | Never stores server state |
| Exporter | Durable outbox, batch, acknowledgement, retry, dead letter, flush | At-least-once delivery across restart |
| Python collector | Authenticate, isolate, validate, ingest, persist, query, delete, expose readiness/metrics | Single-node multi-project data plane |
| Event engine | Named fan-out, filtering, lease, retry, dead letter, explicit replay | Metadata processing; handlers must be idempotent |
| Plugin host | Supervise versioned process protocol under explicit permissions | Trusted process boundary; OS sandbox is external |
| Local server | Ingest, persist, query, serve UI | Loopback single-user inspection boundary |
| Store | Append accepted events, rebuild projections | Replaceable behind interface |
| Dashboard | Filter traces; inspect relationships, causal operations and events; export/delete | Local API consumer; no direct store access |
| CLI | Start, diagnose, demo, query, export/import/delete/prune | Same public API as UI |

## Deployment evolution

| Stage | Data plane | Control plane |
|---|---|---|
| Local | In-process SDK + localhost inspection service | None |
| Release candidate | SDKs, six Python adapters, durable transports/engine, authenticated self-host collector | Local key/project config |
| Future managed deployment | Regional ingest, stream processing, object/column stores | Identity, organizations, projects, billing, alerts, policy and audit |

## Cloud target architecture

Regional HTTPS ingest authenticates project keys, applies quotas and redaction policy, writes to a durable log, and asynchronously builds trace, cost, and search projections. Object storage holds compressed payloads; a columnar analytics store supports aggregation; a relational control store holds tenants, policies, and billing metadata. Query services enforce tenant and project scope. The UI never accesses stores directly.

## Reliability semantics

The Python durable exporter commits before delivery and provides at-least-once semantics. Receiver acknowledgements occur only after broker or collector acceptance; duplicates remain possible after an interrupted acknowledgement and are resolved by batch/event IDs. The collector commits an entire batch atomically. Event handlers use durable leases and explicit terminal dead letters. Ordering is reconstructed from timestamp, lifecycle phase, producer-local sequence, and event ID; multi-worker completion ordering is not promised.

## Extension model

Adapters translate official framework callbacks to the common schema. Exporters and transports implement public protocols. Plugins use an integrity-checked child-process protocol with default-deny permissions; untrusted code additionally requires an OS/container sandbox. Schema additions are backward-compatible within a major version; unknown event types remain queryable.

## Build versus buy

- Build: agent semantic schema, adapters, trace projection, debugging UX, governance semantics.
- Reuse: OpenTelemetry conventions, cloud identity, billing, managed databases, queues, object storage, Kubernetes primitives.
- Avoid: custom cryptography, custom identity provider, or bespoke message broker.

## Architecture fitness functions

- SDK core imports no server or UI modules.
- All stored records validate against the public schema.
- Every maintained adapter passes the public conformance verifier.
- A real mixed-framework integration keeps one canonical trace and causal parent chain.
- The adapter template compiles and passes conformance in the root suite.
- Trace discovery dimensions are derived from safe stored metadata, never raw payload search.
- A new exporter requires no runtime API change.
- Every authenticated collector key, query, and uniqueness constraint carries project scope.
- A trace exported from local can be ingested by cloud without transformation.
- Tenant scope is mandatory in every future cloud query/store key.

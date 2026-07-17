# Production Python runtime

## Supported architecture

The Python package is the primary runtime and includes four independent planes:

| Plane | Public components |
|---|---|
| Instrument | `CausentraRuntime`, provider mappings, W3C context, OTel bridge, six native framework adapters |
| Process | Durable `EventEngine`, named subscriptions, retries, dead letters, explicit replay |
| Deliver | SQLite spool plus HTTP, WebSocket, Kafka, NATS JetStream, Redis Streams, MQTT |
| Collect | Authenticated HTTP collector, project isolation, durable SQLite WAL store, query/delete API, health/readiness, operator metrics |
| Operate | Python CLI for safe initialization, checks, trace lifecycle, backup, and idempotency retention |

Every boundary uses `RuntimeEvent` schema 1.0. Optional frameworks and transports remain extras; the base wheel has no mandatory third-party dependency.

## Framework compatibility

| Framework | Supported Python band | Official extension surface |
|---|---|---|
| OpenAI Agents | `>=0.18,<0.19` | `TracingProcessor` |
| LangGraph / LangChain | `langgraph >=1.2,<1.3`; `langchain-core >=1.4,<1.5` | callback handler |
| CrewAI | `>=1.15.3,<1.16` | event bus listener |
| Google ADK | `>=2.4,<2.5` | `BasePlugin` on `App` |
| Semantic Kernel | `>=1.44,<1.45` | function invocation filter |
| Microsoft AutoGen | `autogen-core/agentchat >=0.7.5,<0.8` | OpenTelemetry `TracerProvider` |

Compatibility tests install these exact bands and verify native registration. Adapters allowlist identity, lifecycle, timing, model and usage facts; prompt, state, message, tool argument, result and exception-message bodies are excluded.

## Delivery guarantees

- Producer events are committed to SQLite before broker or network delivery.
- Delivery is at least once. Receivers must deduplicate by `batchId` or `eventId`.
- HTTP collector ingestion is atomic per batch and rejects identifier reuse with different data.
- Kafka enables idempotence and `acks=all`; JetStream uses `Nats-Msg-Id`; MQTT requires QoS 1 or 2; WebSocket requires an application acknowledgement; Redis requires an `XADD` response.
- Retry exhaustion and permanent errors remain operator-visible dead letters. Nothing is deleted implicitly.
- Persisted dead-letter diagnostics contain exception types, not arbitrary exception messages; detailed callbacks remain application controlled.
- `flush()` returns false on pending, dead-lettered, or undrainable work. Worker death is observable.

## Collector security

- Bearer API keys are stored only as SHA-256 digests and must be high entropy.
- A credential maps to exactly one project; storage uniqueness and every query include project scope.
- Operator credentials are required for process-wide metrics.
- Remote binding requires TLS unless an explicit unsafe development override is set.
- Request bodies, batches, per-key traffic, per-remote authentication attempts, limiter identities, project quotas, total storage, concurrent requests and socket time are bounded.
- Database writes use WAL, `synchronous=FULL`, foreign keys and atomic transactions.
- `SqliteCollectorStore.backup(path)` creates a transactionally consistent atomic backup while the embedded collector is running.
- Security headers, request IDs and generic external errors are enabled. Keys and payloads are never logged.

The public collector is a production single-node data plane. Multi-region replication, SSO, organization RBAC, billing and contracted HA belong to the separate enterprise control plane. SQLite files should reside on durable local block storage with filesystem-level encryption and tested backup/restore. Batch idempotency tombstones intentionally survive trace deletion so a delayed retry cannot resurrect deleted data; prune them only under an explicit retention policy.

## Plugin security

Plugins use a versioned JSON-lines child-process protocol, never Python imports. Default policy trusts no plugin. Activation requires an explicit plugin ID, executable allowlist where needed, declared permissions, supplied environment names and verified SHA-256 artifacts. Attribute access is denied unless both manifest and operator policy grant it.

Process separation is not an operating-system sandbox. Third-party code still requires operator trust or an external container/OS sandbox. The host limits protocol bytes and time, strips inherited environment, suppresses plugin stderr, uses no shell and integrates failures with durable retries/dead letters.

## Production shutdown order

1. Stop accepting application work.
2. Call runtime or event-engine `flush(timeout)`.
3. Close plugin runtimes.
4. Call runtime/exporter/event-engine `shutdown(timeout)`.
5. Stop the collector and checkpoint its WAL.
6. Alert if any flush returned false or dead-letter count is non-zero.

Abrupt termination can interrupt an in-flight remote acknowledgement, causing a safe duplicate on restart. It does not remove the durable local event.

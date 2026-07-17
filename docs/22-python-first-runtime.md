# Python-first runtime architecture

## Product boundary

`causentra` observes, normalizes, delivers, and processes operational agent events. It does not orchestrate agents, own model credentials, execute tools, capture hidden reasoning, or replay side effects.

## Runtime components

| Component | Contract |
|---|---|
| `CausentraRuntime` | Sync/async trace, workflow, agent, model, tool, handoff, delegation, and custom lifecycles |
| Provider support | Eight deep privacy-safe extractors; seven compatible profiles; arbitrary normalized custom IDs |
| Framework adapters | Native OpenAI Agents, LangGraph/LangChain, CrewAI, Google ADK, Semantic Kernel, and AutoGen surfaces |
| OTel bridge | Lifecycle projection into real spans and official OTLP/HTTP protobuf export |
| `SqliteEventSpool` | Durable bounded producer outbox, leases, dead letters, and explicit recovery |
| Transports | HTTP, WebSocket, Kafka, NATS JetStream, Redis Streams, and MQTT acknowledgement contracts |
| `EventEngine` | Durable multi-subscriber routing, filtering, retry, dead letters, and explicit redelivery |
| Plugin SDK | Versioned child-process protocol with explicit trust, permissions, environment, executable, and integrity policy |
| Python collector | Authenticated project-scoped ingest/query/delete API, WAL store, quotas, health/readiness, and metrics |

## Compatibility

Python 3.10–3.13 is declared. Framework peer bands are narrow and listed in `python/pyproject.toml`; exact-version tests verify all six official registration surfaces. The base wheel has no mandatory third-party dependency. Framework, transport, and OTel dependencies are optional extras.

## Trust controls

- Maintained adapters omit prompts, outputs, messages, state, tool arguments/results, and exception messages.
- Recursive sensitive-key redaction runs before exporter access.
- Remote transports require secure schemes/configuration unless an explicit development override exists.
- Producer and processing queues are durable and bounded; retries never delete terminal failures silently.
- Collector credentials are hashed; every data operation is project scoped; remote binding requires TLS by default.
- Plugins are out of process and default-deny, but require an OS/container sandbox for untrusted code.

## Verification claim

The workspace establishes implementation, deterministic compatibility, packaging, and local integration evidence. Production approval for a particular deployment additionally requires its live brokers, TLS path, capacity, restore, failure recovery, long-duration soak, dependency review, and independent security results. See [verification evidence](26-verification-evidence.md).

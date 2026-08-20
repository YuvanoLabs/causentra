# Original vision traceability

This matrix maps the product's original vision to the release-candidate implementation. “Implemented” means code and deterministic tests exist; it does not imply hosted operation or external certification.

| Original capability | Public implementation | Status/boundary |
|---|---|---|
| Core SDK and lifecycle | Python-first `CausentraRuntime`; TypeScript protocol peer; schema 1.0 | Implemented |
| LangGraph | Native Python and TypeScript adapters | Implemented |
| OpenAI Agents SDK | Native Python and TypeScript adapters | Implemented |
| CrewAI | Native Python event-bus adapter | Implemented |
| AutoGen | Native Python OTel exporter/provider adapter | Implemented |
| Google ADK | Native Python `App` plugin | Implemented |
| Semantic Kernel | Native Python function-invocation filter | Implemented |
| Custom agents | Explicit Python/TypeScript runtime APIs and OTel ingress | Implemented |
| Event engine/retries | Durable named routing, filters, leases, retry, dead letters | Implemented |
| Replay | Explicit stored-event redelivery to idempotent handlers | Implemented with safety boundary |
| Execution graph/debugging | Causal tree, timeline, relationships, filters, trace API/CLI | Implemented |
| Telemetry/tracing | Privacy-safe events, W3C propagation, OTel projection/export, OTLP ingress | Implemented |
| Provider/model/cost facts | Eight deep mappings, seven compatible profiles, explicit cost provenance | Implemented; no silent price table |
| HTTP/WebSocket/Kafka/NATS/Redis/MQTT | Durable producer outbox and acknowledgement-aware transports | Implemented; live target proof is operator-run |
| Plugin SDK | Default-deny, integrity-checked child-process protocol | Implemented for trusted plugins |
| Python collector | Auth, project isolation, quotas, WAL, query/delete, backup, readiness, metrics | Implemented single-node self-hosted data plane |
| CLI | Python init/doctor/traces/trace/delete/backup/retention plus Node local UI CLI | Implemented |
| Local dashboard | Node.js loopback dashboard over the same event contract | Implemented public protocol peer |
| Governance | Capture policy, project authorization and plugin permissions | Implemented runtime controls |
| Managed cloud/team collaboration/SSO/SCIM/audit/SLA | Future Causentra capabilities | Not launched; gated by recurring adoption |
| Prompt/reasoning/tool-output replay | Excluded by default | Intentional privacy/safety boundary |
| VS Code extension/marketplace | No release-candidate code | Demand and maintainer gated |

## Interpretation

The release candidate implements the infrastructure spine promised by the original architecture: six agent frameworks, portable lifecycle semantics, durable processing, six transports, local/self-host collection, observability, and controlled extensions. Managed collaboration and organization-wide identity are future Causentra capabilities, not missing runtime dependencies.

The project does not claim that installing one package can automatically observe every framework/provider without registration. Native adapters use official extension surfaces; custom and standards-based applications use explicit SDK or OTLP integration. This is the maintainable and trustworthy meaning of cross-framework standardization.

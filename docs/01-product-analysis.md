# Product analysis

## Executive decision

Proceed, but enter through local agent observability rather than a general-purpose “agent runtime.” The broad label creates expectations for orchestration, sandboxing, scheduling, identity, state, and evaluation. The first product will own the telemetry contract and debugging experience; runtime control may follow only after evidence.

## Problem

Agent developers assemble callbacks, logs, provider metadata, and ad hoc dashboards. A failure crosses model calls, tool calls, retries, and framework boundaries, making reproduction slow and cost attribution unreliable. Existing generic telemetry is necessary infrastructure but does not by itself provide agent semantics or a useful local workflow.

## Chosen wedge

“From unexplained agent failure to a navigable trace in five minutes.”

The wedge combines:

- a framework-neutral event envelope;
- automatic context propagation within a Node.js process;
- safe capture of agent/tool/model lifecycle data;
- local durable ingestion and visual inspection;
- export-friendly contracts compatible with later OpenTelemetry mapping.

## Why now

- Agent stacks are fragmented and change quickly.
- Production teams require cost, latency, and failure evidence.
- Framework-native traces create switching costs and incomplete cross-framework views.
- Privacy-sensitive teams need a credible local/self-hosted path.

## Strategic choices

| Decision | Choice | Reason |
|---|---|---|
| Category | Agent operations infrastructure | Clearer buyer value than generic AI platform |
| Adoption | Open-source, local-first | Low-friction evaluation and trust |
| Contract | Vendor-neutral event schema | Adapter and backend leverage |
| Primary language | Python | Matches the dominant agent-framework ecosystem; TypeScript remains a supported protocol peer |
| Storage | Local append-only file in milestone 0 | Inspectable, dependency-light, replaceable |
| Monetization | Managed control plane | Teams pay for operations, not instrumentation |
| Interoperability | Map to OpenTelemetry; do not fork it | Avoid isolated telemetry ecosystem |

## Assumptions to validate

| Assumption | Test | Pass signal |
|---|---|---|
| Setup is the adoption bottleneck | Five external onboarding sessions | 4/5 reach first trace in ≤5 minutes |
| Agent semantics add value beyond logs | Task-based comparison | Median diagnosis time improves ≥30% |
| Local-first increases trust | Interview and opt-in telemetry | ≥60% prefer local evaluation path |
| Teams pay for shared history and alerts | Design-partner pricing interviews | 3 written pilot intents |
| One schema can span frameworks | Implement two adapters | ≥80% common fields without lossy hacks |

## Moat hypothesis

The defensible asset is not ingestion. It is the combination of an adopted semantic contract, excellent adapters, longitudinal operational data, workflow comparisons, and an ecosystem. The event schema must remain portable so customer trust grows faster than lock-in concerns.

## Failure conditions

Reconsider the thesis if onboarding remains above 15 minutes, framework adapters require incompatible schemas, users only want framework-native tools, or managed retention/alerting produces no paid pilot intent after 30 qualified interviews.

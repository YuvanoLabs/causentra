# Product requirements document

## Product

Causentra Local, milestone M0

## Outcome

A Python-first agent team can capture, retain, inspect, and query a failed or slow local execution across supported frameworks without sending data to a third party. TypeScript clients use the same contract and collector.

## Success measures

| Measure | M0 target |
|---|---:|
| Time from install to first trace | ≤5 minutes |
| Runtime overhead at 100 events/trace | p95 <5 ms/event excluding network |
| Local ingestion availability during test run | ≥99.5% |
| Valid event persistence | 100% in graceful-shutdown tests |
| Critical-path automated coverage | ≥80% branch target after beta |
| Sensitive payload capture | Off unless explicitly supplied |

## In scope

- Versioned event envelope and lifecycle taxonomy
- Trace/span context with nested asynchronous operations
- Batched HTTP export with bounded retries and flush
- Local HTTP ingestion with validation and body limits
- Append-only durable trace store and startup recovery
- Trace list/detail API and web dashboard
- CLI health check, server start, demo, trace list/detail, portability, deletion, and pruning
- Redaction hooks and conservative defaults
- Example, automated tests, CI, and operating documentation
- Maintained OpenAI Agents and LangGraph adapters with shared parent context
- Python 3.10+ SDK with synchronous/asynchronous context propagation
- Native OpenAI Agents Python and LangGraph Python adapters
- OTLP/HTTP JSON and protobuf ingress for standards-based producers
- Portable multi-agent handoff/delegation relationships

## Out of scope

- Executing or re-running side-effecting tools
- Capturing hidden model reasoning
- Authentication or internet exposure of the local server
- Hosted service, billing, teams, RBAC, SSO, alerts, evaluations
- Kafka/NATS/Redis/MQTT transports
- CrewAI-specific native adapter and additional framework adapters beyond measured demand

## User stories

1. As a developer, I can wrap an async workflow and its tool/model operations so context is correlated automatically.
2. As a developer, I can emit domain events without exposing prompt or output bodies by default.
3. As a developer, I can start one local command and inspect traces in a browser.
4. As a developer, I can find failures, duration, event counts, and child spans.
5. As an operator, I can verify server health and retrieve trace JSON through stable APIs.
6. As a maintainer, I can evolve the schema without silently accepting incompatible events.

## Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | Create unique trace, span, event, and session identifiers | Must |
| FR-02 | Emit trace/span start and end plus arbitrary lifecycle events | Must |
| FR-03 | Propagate current trace/span through async calls | Must |
| FR-04 | Validate schema version, timestamps, IDs, type, and attributes | Must |
| FR-05 | Batch export and retry transient HTTP failures with a finite queue | Must |
| FR-06 | Persist accepted events and recover them after restart | Must |
| FR-07 | List traces and return ordered trace events | Must |
| FR-08 | Render status, duration, events, and span relationships | Must |
| FR-09 | Provide CLI serve, doctor, demo, traces, and trace commands | Must |
| FR-10 | Apply a user-configurable redactor before export | Must |
| FR-11 | Export OpenTelemetry spans through an official OTLP/HTTP protobuf bridge | Must |
| FR-12 | Ingest OTLP/HTTP JSON and protobuf without retaining known content fields | Must |
| FR-13 | Join supported frameworks under one canonical parent trace | Must |
| FR-14 | Represent agent handoff and delegation without framework schema forks | Must |
| FR-15 | Verify maintained adapters against a public conformance contract | Must |
| FR-16 | Search safe local metadata and filter by framework, provider, model, status, session, and tool | Must |
| FR-17 | Render source-to-target handoff and delegation relationships | Must |
| FR-18 | Provide an executable, privacy-safe adapter scaffold | Must |
| FR-19 | Replay a workflow in a guarded sandbox | Later |
| FR-20 | Provide privacy-safe deep response telemetry for eight priority providers and tested canonical profiles for all 15 OTel provider identifiers | Must |
| FR-21 | Provide durable at-least-once HTTP, WebSocket, Kafka, NATS, Redis, and MQTT delivery | Must |
| FR-22 | Provide a durable event engine with named routing, retries, dead letters, and explicit redelivery | Must |
| FR-23 | Provide authenticated project-isolated self-host collection with quotas, readiness, metrics, and deletion | Must |
| FR-24 | Provide six maintained Python native framework adapters using official extension surfaces | Must |
| FR-25 | Provide a default-deny, integrity-checked out-of-process plugin contract | Must |

## Release policy

The Python runtime is published as the `0.1.0a1` alpha on [PyPI](https://pypi.org/project/causentra/). Core runtime requirements are implemented with deterministic local evidence. Subsequent release automation, provenance, target-infrastructure recovery/soak results, and an independent security review remain release hardening work.

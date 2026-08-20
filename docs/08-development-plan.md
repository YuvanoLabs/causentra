# Development plan

## Delivery model

Two-week iterations, trunk-based development, short-lived branches, automated gates, and demoable vertical slices. Product, engineering, design, security, and developer relations review milestone exit evidence together.

## Workstreams

| Workstream | M0 deliverable | Owner profile |
|---|---|---|
| Contract | Event schema, validation, fixtures | Principal engineer |
| SDK | Context, spans, redaction, exporter | SDK engineer |
| Runtime data plane | Durable delivery, event engine, authenticated collector, queries | Backend/reliability engineer |
| Ecosystem | Six Python framework adapters, providers, OTel, plugins | Principal SDK engineer |
| Experience | Dashboard, CLI, quick start | Full-stack + DevRel |
| Quality/trust | Tests, CI, threat review, docs | Quality/security leads |

## Milestones

| Milestone | Scope | Exit criterion |
|---|---|---|
| M0 vertical slice | Python-first SDK, supported TypeScript SDK, and local runtime | Completed: cross-language acceptance scenarios pass |
| M1 public release candidate | Six Python adapters, durable data plane, authenticated collector, plugins | Completed locally; external assurance pending |
| M2 product beta | Packages, OTLP mapping, docs site, contribution process | 50 weekly active projects; crash-free ≥99% |
| M3 cloud private beta | Auth ingest, tenancy, retention, sharing | 5 pilots; zero cross-tenant test failures |
| M4 cloud GA | Billing, alerts, support, SLOs | 20 paying teams; on-call and DR proven |
| M5 governed deployment | SSO/SCIM, audit, private deployment | 3 production customers |

## Release-candidate implementation sequence

1. Freeze v1 event vocabulary and invalid-input behavior.
2. Implement SDK context, lifecycle, redaction, and memory exporter.
3. Implement HTTP exporter and local ingestion/store APIs.
4. Add dashboard and CLI against public APIs.
5. Exercise success, failure, retry, privacy, and restart paths.
6. Add durable transports, processing, authenticated collection, and permissioned plugins.
7. Complete target-infrastructure benchmarks, fault/restore/soak evidence, independent review, and signed package release.

## Engineering standards

- Strict mypy/Ruff with `py.typed`; TypeScript strict mode and explicit public return types
- No secrets, prompt bodies, or provider keys in tests/logs
- Conventional commits and changesets from public beta
- Review required for schema, security, storage, and dependency changes
- ADR required for decisions that constrain future implementations
- Deprecation window of at least one minor release after beta

## Team shape through cloud beta

Founding phase: product/architecture lead, two SDK/backend engineers, one full-stack engineer, and fractional design/security/DevRel. Add a reliability engineer before managed production workloads and a customer engineer before governed-deployment pilots.

## Definition of ready

A work item has an owner, user outcome, acceptance evidence, telemetry requirement, privacy classification, rollout plan, and named dependency. Discovery work can remain time-boxed without implementation commitments.

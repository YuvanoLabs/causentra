# Production-readiness assessment

Assessment date: 2026-08-24. Scope: repository code, deterministic local gates,
package configuration, and operator documentation. It is not an independent
security review, target-infrastructure soak, or claim of managed high
availability.

## Decision boundary

The Python collector and durable producer are suitable for a controlled,
single-node production data plane when an operator completes the [deployment
runbook](34-production-deployment-runbook.md), locks the selected dependency
graph, and records the required operating evidence. The published `0.1.0b1`
package is a beta and must not be described as unconditional general
availability until the external gates close.

## Repository controls

| Area | Control |
|---|---|
| Privacy | Runtime, adapters, and OTLP ingestion minimize content by default; collector configuration keeps only key digests. |
| Tenant isolation | Project-scoped keys, scoped query/delete, quotas, and operator-only metrics. |
| Durability | SQLite outbox, at-least-once delivery, explicit dead letters, and receiver idempotency contract. |
| Network safety | TLS is required for remote collector binds and remote transports fail closed without secure delivery. |
| Supply chain | SHA-pinned CI actions, Dependabot, canonical package metadata checks, and a release workflow that runs type and security gates before publishing. |
| Operations | Authenticated onboarding, OpenAPI contracts, executable producer example, deployment/runbook, backup, retention, and rollback guidance. |

## Enterprise producer example

[`examples/python/production_producer.py`](../examples/python/production_producer.py)
is an executable durable-producer pattern. It requires a secret-file path and
collector endpoint, rejects remote plaintext, uses a SQLite outbox, checks
`flush()`, and always calls `shutdown()`.

```bash
export CAUSENTRA_KEY_FILE=/run/secrets/causentra-project-key
export CAUSENTRA_ENDPOINT=https://collector.internal.example:4318/v1/events
export CAUSENTRA_SPOOL=/var/lib/support-service/causentra-outbox.db
export CAUSENTRA_SERVICE=support-service
python examples/python/production_producer.py
```

## External release gates

Source verification does not establish these environment-dependent conditions:

| Gate | Required evidence |
|---|---|
| Independent review | Threat/code review with no unresolved critical or high finding. |
| Dependency assurance | Locked production extras, SBOM, licenses, and advisory disposition. |
| Target infrastructure | TLS/proxy and broker fault tests with duplicate-safe recovery. |
| Data protection | Encryption, key rotation, backup retention, and a successful restore drill. |
| Reliability | Representative 24-hour soak without corruption, silent worker death, unbounded storage, or SLO breach. |
| Operations | On-call ownership, alert routing, incident workflow, and rollback rehearsal. |
| Usability | External onboarding sessions that reproduce tracing and recovery without maintainer assistance. |

The automated evidence and beta limitations are maintained in
[verification evidence](26-verification-evidence.md) and the [product FAQ](31-product-faq.md).

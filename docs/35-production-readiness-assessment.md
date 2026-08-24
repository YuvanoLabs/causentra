# Production-readiness assessment

Assessment date: 2026-08-24. Scope: the repository state, deterministic local
checks, package configuration, and documentation. This is not an independent
security review, an infrastructure soak, or a statement about an external
deployment.

## Decision

The Python collector and durable producer can be deployed as a **controlled,
single-node production data plane** when the operator follows the [deployment
runbook](34-production-deployment-runbook.md), locks the selected dependency
graph, and completes the deployment acceptance exercises. The published Python
package remains an alpha: the repository must not claim an unconditional general
availability or managed-platform posture until the external gates below close.

## Evidence observed

| Area | Evidence | Assessment |
|---|---|---|
| Privacy | Maintained runtime, adapter, and OTLP paths omit content-bearing data by default; collector configuration contains only key digests. | Strong boundary, subject to application-side metadata discipline. |
| Tenant isolation | Project-scoped keys, scoped query/delete operations, quotas, and operator-only metrics are covered by collector tests. | Suitable for the documented single-node scope. |
| Durable delivery | SQLite outbox, at-least-once semantics, explicit dead letters, retries, and receiver idempotency contract are implemented. | Ready only when outbox capacity and recovery drills are operated. |
| Network controls | Remote collector binds require TLS by default; remote durable transports fail closed without secure transport. | Strong default; firewall and certificate operations remain deployment responsibilities. |
| Supply chain | CI actions are SHA-pinned, Dependabot is configured, and the npm production audit reported no vulnerabilities. | Release workflow parity and external artifact assurance remain required. |
| Documentation | Onboarding, integration recipes, OpenAPI contracts, production runtime operations, and a deployment runbook exist. | Enterprise operator guidance is now available; test it with real onboarding teams. |

## Current deterministic release blockers

The following repository defects or gaps must be closed before calling a source
release production-ready:

1. **TypeScript build configuration:** `npm run verify` currently stops in
   `@causentra/langgraph` because compiler options do not include the installed
   Node type declarations while test sources import `node:test` and
   `node:assert/strict`. The intended correction is a shared
   `"types": ["node"]` compiler option, followed by the full suite.
2. **Canonical package ownership:** package metadata and citation fields still
   reference the prior repository owner although `origin` is
   `YuvanoLabs/causentra`. Published artifacts must carry the canonical
   homepage, repository, issue tracker, and citation URLs.
3. **Publish-gate parity:** the Python publish workflow needs the same strict
   typing and source/dependency security gates that CI applies before an artifact
   can be sent to PyPI. The build runner should also declare its Node runtime
   because it invokes the Node-based Python-build script.

These are deterministic source-workspace tasks. Do not compensate for them with
manual release instructions or a passing subset of checks.

## External release gates

The repository alone cannot prove these requirements; record dated evidence and
an accountable owner for each before a final production-release decision.

| Gate | Required evidence |
|---|---|
| Independent review | Threat/code review with no unresolved critical or high findings. |
| Dependency assurance | Locked production extras, SBOM, license review, and advisory disposition for each deployed framework. |
| Target infrastructure | TLS/proxy and broker fault tests, including duplicate-safe recovery. |
| Data protection | Encryption, key rotation, backup retention, and a successful restore drill. |
| Reliability | A representative 24-hour soak without corruption, silent worker death, unbounded storage, or SLO breach. |
| Operational readiness | Named on-call owner, alert routing, incident process, rollback rehearsal, and evidence retention policy. |
| Usability | External onboarding sessions that independently reproduce a first trace and recovery workflow. |

## Enterprise producer example

[`examples/python/production_producer.py`](../examples/python/production_producer.py)
is a minimal executable pattern for an authenticated, durable producer. It
requires a secret-file path and collector endpoint rather than embedding either
value, rejects remote plaintext endpoints, uses a SQLite outbox, checks
`flush()`, and always calls `shutdown()`.

```bash
export CAUSENTRA_KEY_FILE=/run/secrets/causentra-project-key
export CAUSENTRA_ENDPOINT=https://collector.internal.example:4318/v1/events
export CAUSENTRA_SPOOL=/var/lib/support-service/causentra-outbox.db
export CAUSENTRA_SERVICE=support-service
python examples/python/production_producer.py
```

The example emits synthetic lifecycle facts only. It is intentionally not a
framework registration recipe; use the maintained framework examples in the
[integration guide](17-integration-guide.md) for those surfaces.

# Evidence-based gap delivery backlog

This document reconciles the sponsorship/improvement guide with the current
repository. It is an engineering backlog, not a claim that every comparison
or market statement in the guide has been independently verified.

## What is already present

- Privacy-by-default lifecycle adapters omit prompt, output, tool payload and
  exception-message bodies. Recursive key redaction and caller-supplied
  redactors exist in [`python/src/causentra/redaction.py`](../python/src/causentra/redaction.py),
  [`packages/sdk/src/redaction.ts`](../packages/sdk/src/redaction.ts), and the
  adapter seams.
- Permissioned, integrity-checked out-of-process plugins exist in
  [`python/src/causentra/plugins.py`](../python/src/causentra/plugins.py).
- SQLite WAL durability, bounded delivery, retries/dead letters, and HTTP,
  Kafka, NATS, Redis Streams and MQTT transports exist in
  [`python/src/causentra/spool.py`](../python/src/causentra/spool.py),
  [`python/src/causentra/event_engine.py`](../python/src/causentra/event_engine.py),
  and [`python/src/causentra/transports.py`](../python/src/causentra/transports.py).
- Project-scoped bearer-key collection, quotas, readiness, scoped metrics, and
  metadata-only audit decisions
  exist in [`python/src/causentra/collector.py`](../python/src/causentra/collector.py)
  and [`python/src/causentra/collector_store.py`](../python/src/causentra/collector_store.py).
- Explicit retention pruning, observation, and opt-in bounded lifecycle-loop
  aggregation exist. See [`python/src/causentra/aggregation.py`](../python/src/causentra/aggregation.py).
- Cost fields require explicit provenance. There is no bundled provider price
  table; callers can supply an effective-dated local catalog. Prompt management
  remains unimplemented by design.
- The local dashboard, causal tree, and timing breakdown are developer-facing;
  organization RBAC, Kubernetes multi-tenant hosting, prompt management, and a
  Rust core are not current M0 capabilities. The production-runtime document
  explicitly places managed RBAC/SSO/HA in future scope
  ([`docs/24-production-python-runtime.md`](24-production-python-runtime.md)).

## Completed in this repository

These five increments are implemented and covered by the validation evidence
listed with each item:

1. **Python policy redaction:** opt-in email, Luhn-card and Indian-PAN value
   detection, composed with key redaction. Validation:
   `PYTHONPATH=python/src .venv-frameworks/Scripts/python.exe -m pytest python/tests/test_redaction.py python/tests/test_runtime.py python/tests/test_adapter.py -q`
   and Ruff on the changed Python files.
2. **TypeScript policy-redactor parity:** `createPolicyRedactor` and focused
   SDK tests. Validation:
   `npm --workspace @causentra/sdk run typecheck`, `build`, and `test` (20 passed).
3. **Observation-only loop detection:** opt-in threshold policy, one
   `custom.loop.detected` diagnostic per `(trace,parent,family,name)`, reset at
   trace completion. Validation: focused runtime pytest (16 passed) and Ruff.
4. **Truthful local timing breakdown:** model/tool category sums, interval-union
   wall coverage, unattributed remainder, and explicit unknown/overlap states.
   Validation: `npm --workspace @causentra/server run typecheck`, `build`, and
   `test` (17 passed).
5. **Deep-trace performance evidence:** JSON benchmark comparing default and
   loop-policy runtimes, documented in
   [`docs/26-verification-evidence.md`](26-verification-evidence.md).
   Validation: `python python/benchmarks/runtime_overhead.py --count 8`, Ruff,
   and runtime tests.

## Ordered remaining backlog

Each item is intentionally small and has a dependency and an observable exit
criterion.

1. **Design a trace-signing contract — completed as ADR-006.**
   [`docs/adr/006-versioned-detached-telemetry-signatures.md`](adr/006-versioned-detached-telemetry-signatures.md)
   defines canonical bytes, a detached envelope, key purposes, rotation and
   verification failure behavior. No live key-service interoperability evidence
   is bundled with the repository.
   **Completed milestones:** standalone schema/fixtures and an opt-in TypeScript local ECDSA P-256 signer/verifier under `packages/sdk`. RFC 8785 canonicalization helpers now exist as optional prerequisite infrastructure (`canonicalize@4.0.0` and Python
   `rfc8785>=0.1.4,<0.2`). Python signing, explicit KMS/Vault digest adapters,
   normalized batch signing, and collector enforcement are now implemented.
2. **Extend detached signing — completed locally.** Tampering is rejected before
   verified-path storage, legacy unsigned batches are explicitly labelled, and
   tests cover local keys plus mock KMS/Vault digest behavior. Live key-service
   interoperability remains an operator evidence gate.
3. **Design collector field projections and authorization — completed.** The
   API defines summary/debug projections, scopes, audit decision metadata, and
   failure semantics in [`docs/37-assurance-controls.md`](37-assurance-controls.md).
4. **Implement restricted collector projections/RBAC slice — completed.** A
   restricted principal cannot retrieve stored attributes or delete traces;
   reads/deletes remain project-scoped and decisions are durable/auditable.
   Organization/team control-plane RBAC remains outside single-node scope.
5. **Add loop aggregation — completed as an opt-in exporter policy.** Empty,
   repeated leaf pairs are bounded into a replayable summary event; nested or
   payload-bearing operations pass through unchanged and application results are
   unaffected.
6. **Define an offline deterministic evaluation contract — completed.** Rules
   operate on one exported trace bundle and provide stable score attributes for
   caller-created `evaluation.score` events; there is no LLM judge or network
   dependency.
7. **Add an optional price catalog — completed.** The caller supplies a
   versioned, effective-dated integer-rate catalog; unknown rates return no
   estimate and every estimate carries explicit `catalog_estimate` provenance.
   Prompt management remains a separate product/design gate.
8. **Profile and soak before considering a Rust core.** Run deep traces, memory
   allocation profiling, serialization tests, backlog recovery and target
   infrastructure soak. Dependency: benchmark evidence and real workload
   samples. Acceptance: published p50/p95/CPU/memory/disk evidence and a
   measured bottleneck with a proposed FFI boundary. Rust is not an immediate
   implementation commitment.
9. **Ongoing 1.x release and security controls.** Complete independent security review,
   dependency/SBOM review, target transport/TLS/backup/restore/24-hour soak,
   onboarding evidence, signed artifacts and release provenance. Dependency:
   items 1–8 where applicable. Acceptance: release checklist in
   [`docs/19-local-release-readiness.md`](19-local-release-readiness.md) is
   closed with evidence; no prerelease-stage claims remain.

## Explicit design/decision gates

Managed RBAC, Kubernetes multi-tenant dashboard hosting, prompt versioning and
deployment, and a Rust serialization/core rewrite are not immediate coding
tasks. Each requires a product/architecture decision, operating model, threat
model, cost evidence and a bounded design before implementation is authorized.
The current local dashboard and single-node collector remain valid for the
documented stable single-node scope.

## Sponsorship-plan next actions (non-contact work)

No outreach or external contact is authorized by this backlog. The preparation
sequence is:

1. Verify that relevant official sponsorship/grant programs are active and that
   their eligibility and application paths are current.
2. Tailor a technical one-pager using repository evidence, limitations and the
   ordered backlog above.
3. Identify public program/company contact channels and record them without
   sending messages.
4. Request explicit user approval before any outreach or submission.

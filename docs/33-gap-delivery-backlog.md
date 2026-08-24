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
- Project-scoped bearer-key collection, quotas, readiness and operator metrics
  exist in [`python/src/causentra/collector.py`](../python/src/causentra/collector.py)
  and [`python/src/causentra/collector_store.py`](../python/src/causentra/collector_store.py).
- Explicit retention pruning exists; active agent-loop suppression or
  aggregation does not. See [`apps/runtime-server/src/store.ts`](../apps/runtime-server/src/store.ts)
  and [`apps/runtime-server/src/server.ts`](../apps/runtime-server/src/server.ts).
- Cost fields require explicit provenance, but there is no built-in price
  catalog or prompt-management service (`packages/sdk/src/model-telemetry.ts`).
- The local dashboard, causal tree, and timing breakdown are developer-facing;
  organization RBAC, Kubernetes multi-tenant hosting, prompt management, and a
  Rust core are not current M0 capabilities. The production-runtime document
  explicitly places managed RBAC/SSO/HA in future scope
  ([`docs/24-production-python-runtime.md`](24-production-python-runtime.md)).

## Completed in this working tree (uncommitted)

These five increments are implemented but have not been committed as part of
this planning pass:

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

1. **Design a trace-signing contract — completed as ADR-006 (design only).**
   [`docs/adr/006-versioned-detached-telemetry-signatures.md`](adr/006-versioned-detached-telemetry-signatures.md)
   defines canonical bytes, a detached envelope, key purposes, rotation and
   verification failure behavior. No remote/KMS production signer or dependency exists.
   **Completed milestones:** standalone schema/fixtures and an opt-in TypeScript local ECDSA P-256 signer/verifier under `packages/sdk`. RFC 8785 canonicalization helpers now exist as optional prerequisite infrastructure (`canonicalize@4.0.0` and Python
   `rfc8785>=0.1.4,<0.2`), but signing remains unimplemented.
2. **Extend detached signing — pending Python parity, KMS/Vault adapters, and collector enforcement.** Add a local test signer/verifier and
   exporter/collector hooks; add KMS/Vault adapters only behind explicit
   optional integrations. Dependency: item 1. Acceptance: tampering is rejected,
   signatures survive export/import, and unsigned legacy traces have an explicit
   status.
3. **Design collector field projections and authorization.** Specify summary vs
   debug projections, principal scopes, audit events and failure semantics
   before JWT/role work. Dependency: existing project isolation and policy
   redaction. Acceptance: threat model, API contract and cross-project/field
   leakage tests.
4. **Implement restricted collector projections/RBAC slice.** Start with
   project/operator scopes and field stripping at the query boundary; defer
   organization/team control plane. Dependency: item 3. Acceptance: restricted
   principals cannot retrieve raw attributes, every read/delete remains scoped,
   and authorization decisions are auditable.
5. **Add loop aggregation only after observation evidence.** Use the new detector
   metrics to choose bounded grouping/circuit-breaker policy; do not suppress
   application operations. Dependency: completed observation policy and deep
   benchmark. Acceptance: explicit opt-in policy, bounded event/storage growth,
   replayability, and unchanged application results.
6. **Define an offline deterministic evaluation contract.** Start with rules over
   exported trace bundles and `evaluation.score` extension events; do not add an
   LLM judge or network dependency yet. Dependency: stable signed/exported
   bundle semantics. Acceptance: repeatable scores tied to trace/event IDs and
   privacy-safe fixtures.
7. **Seek product approval for an optional price catalog.** Only if cost tables
   are a committed product outcome, define versioned provider/model rates,
   effective dates and unknown-model behavior. Dependency: product decision and
   existing explicit cost provenance. Acceptance: deterministic lookup tests;
   no silent price guesses. Prompt management remains a separate product/design
   gate.
8. **Profile and soak before considering a Rust core.** Run deep traces, memory
   allocation profiling, serialization tests, backlog recovery and target
   infrastructure soak. Dependency: benchmark evidence and real workload
   samples. Acceptance: published p50/p95/CPU/memory/disk evidence and a
   measured bottleneck with a proposed FFI boundary. Rust is not an immediate
   implementation commitment.
9. **1.0 release and security gates.** Complete independent security review,
   dependency/SBOM review, target transport/TLS/backup/restore/24-hour soak,
   onboarding evidence, signed artifacts and release provenance. Dependency:
   items 1–8 where applicable. Acceptance: release checklist in
   [`docs/19-local-release-readiness.md`](19-local-release-readiness.md) is
   closed with evidence; no alpha-stage claims remain.

## Explicit design/decision gates

Managed RBAC, Kubernetes multi-tenant dashboard hosting, prompt versioning and
deployment, and a Rust serialization/core rewrite are not immediate coding
tasks. Each requires a product/architecture decision, operating model, threat
model, cost evidence and a bounded design before implementation is authorized.
The current local dashboard and single-node collector remain valid for the
documented alpha/release-candidate scope.

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

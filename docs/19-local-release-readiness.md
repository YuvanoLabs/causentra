# Local release readiness

## Completed in the workspace

- Unified Apache-2.0 workspace with one Python package and one TypeScript namespace
- Dependency-free Python core with strict types, privacy-safe lifecycle API, W3C context, provider extraction, and OTel bridge
- Six native Python framework adapters tested against exact supported versions; CrewAI and Semantic Kernel remain production-gated by optional upstream advisories
- Eight deep provider mappings and tested compatibility profiles for all 15 canonical provider IDs
- SQLite durable spool and HTTP, WebSocket, Kafka, NATS JetStream, Redis Streams, and MQTT transports
- Durable event engine with fan-out, bounded retries, leases, dead letters, explicit replay, and explicit purge
- Authenticated Python collector with hashed keys, project isolation, atomic idempotent ingestion, quotas, readiness, metrics, and trace deletion
- Integrity-checked process plugin protocol with default-deny trust, permissions, environment, and executable policy
- Node.js local dashboard/collector, TypeScript protocol peer, OTLP ingress, CLI, trace portability, and causal relationship inspection
- Versioned schema fixtures, conformance tests, clean package installs, benchmarks, and repository boundary checks
- Immutable GitHub Actions references, bounded CI jobs, citation metadata, repository discovery metadata, product FAQ, and machine-checked `llms.txt` links

## Automated local gates

```bash
npm run verify
npm run benchmark
npm run python:benchmark
npm run python:benchmark:collector
```

Exact optional framework validation uses the supported bands in `python/pyproject.toml`. Transport contract tests use deterministic clients; live broker validation belongs to the operator's target-infrastructure gate.

## Owner or deployment-operator gates

- Choose final names and verify package/organization ownership.
- Add the final canonical repository/documentation URLs to package and citation metadata; configure repository description, topics, social preview, sitemap, webmaster tools, and IndexNow only after those URLs exist.
- Verify `smartbytecoder@gmail.com` is monitored; configure private vulnerability reporting, governance, branch protection, signing, provenance, and release permissions.
- Run dependency/SBOM review and an independent security assessment.
- Validate compatible upstream fixes for the CrewAI and Semantic Kernel optional graphs, then rerun exact adapter and advisory gates; do not promote those extras or the aggregate `frameworks` extra while the current findings remain.
- Run target broker, TLS, proxy, backup/restore, failure-injection, and 24-hour soak tests.
- Record Python/OS matrix CI results and published-package clean-install rehearsal.
- Complete five observed onboarding sessions and publish measured results.
- Create public/private repositories and hosting only when the owner is ready.

No code in this workspace performs publication, repository creation, hosting, or deployment.

# Changelog

All notable changes will be documented here. The project follows semantic versioning after the first public schema review.

## Unreleased

- Added evidence-based repository discovery metadata, an answer-oriented product FAQ, `llms.txt`, `CITATION.cff`, package keywords, and a verification gate for search metadata and immutable GitHub Actions references.
- Pinned GitHub Actions to reviewed full commit SHAs, disabled persisted checkout credentials, and bounded CI job execution time.
- Standardized the private product identity as Causentra Enterprise across its sibling directory, Python distribution/import, npm scope, contracts, documentation, and verification commands.
- Adopted the Causentra working brand and migrated Python imports/distributions, CLI commands, npm scopes, environment variables, semantic attributes, schemas, local state paths, and the private extension namespace before public package publication.
- Added a permanent cross-edition brand-contract gate that rejects legacy identifiers.
- Added an authenticated five-minute Python onboarding guide and an executable, end-to-end tested durable-delivery example.
- Added the dependency-free Python `causentra` core with strict typing, packaging, clean-install, Python 3.10–3.13 CI, and Python-first documentation.
- Added native OpenAI Agents, LangGraph/LangChain, CrewAI, Google ADK, Semantic Kernel, and AutoGen adapters against narrow exact-version compatibility bands.
- Added the crash-safe SQLite producer outbox and acknowledged HTTP, WebSocket, Kafka, NATS JetStream, Redis Streams, and MQTT transports with secure remote defaults.
- Added the durable event engine with named fan-out, filtering, leases, bounded retry, privacy-safe dead letters, explicit redelivery, conflict detection, and legacy database migration.
- Added the authenticated Python collector with hashed keys, project isolation, atomic idempotent batches, quotas, health/readiness, operator metrics, deletion, and consistent online backup.
- Added the secure Python `causentra` operator CLI for initialization, health/readiness/auth checks, trace inspection/deletion, backup, and idempotency retention.
- Added a default-deny, integrity-checked child-process plugin protocol with explicit permissions, environment, executable policy, and durable retry integration.
- Added strict wire/config/manifest JSON parsing, duplicate-key rejection, source/advisory security gates, reproducible performance budgets, and operator-run live transport validation.
- Added the separate `causentra_enterprise` Python namespace pinned to the exact public package and enforced by private boundary, typing, test, and build gates.
- Added public governance, support, funding, roadmap, issue forms and pull-request guidance.
- Added an evidence-based product, provider, standards, trust and launch-readiness review.
- Reworked the public README to distinguish maintained, experimental and planned capabilities.
- Corrected experimental OpenTelemetry projections to emit 16-hex span identifiers and separate `service.name` resource metadata.
- Replaced the placeholder security email with a private-vulnerability-reporting process and explicit activation requirement.
- Added strict W3C `traceparent` injection/extraction and W3C-width span identifiers while retaining legacy pre-alpha read compatibility.
- Added the official `@causentra/opentelemetry` bridge with causal spans and tested OTLP/HTTP protobuf export.
- Added provider/model/token/cost attributes with mandatory cost provenance and no implicit pricing.
- Added safe non-loopback refusal, versioned trace export/import, deletion, explicit pruning, and causal-tree inspection.
- Added deterministic real-framework examples for OpenAI Agents and LangGraph.
- Added shared parent-context support and a real mixed OpenAI Agents + LangGraph causal trace test and example.
- Added portable handoff/delegation lifecycle attributes and typed `agent`, `model`, `tool`, and relationship SDK helpers.
- Added OTLP/HTTP JSON and protobuf ingestion with gzip, partial success, deterministic retry deduplication, and privacy-safe content filtering.
- Added all current OpenTelemetry well-known GenAI provider identifiers, alias normalization, and custom-provider preservation.
- Added eight privacy-safe Python provider response mappings, seven compatible profiles, synchronous/asynchronous call wrappers, streaming observation, normalized finish reasons, and a shared 15-provider support manifest.
- Added a public adapter conformance verifier covering schema, identity, lifecycle, privacy, and parent continuity.
- Added an executable community adapter template with allowlisted mapping, failure containment, shared context, portable telemetry and conformance tests.
- Added safe trace-summary search and bounded combined filtering by framework, provider, model, status, session and tool without indexing payload content.
- Added first-class handoff/delegation relationship cards while preserving causal-tree placement.
- Corrected direct-SDK error capture so messages are excluded unless explicitly enabled.
- Corrected merged event ordering so timestamps precede producer-local sequences.

## 0.0.1 - 2026-07-15

- Added strict TypeScript SDK with async trace context, lifecycle events, redaction, memory export, and bounded HTTP batching/retry.
- Added loopback local collector, atomic validation, append-only persistence, deduplication, query API, and dashboard.
- Added CLI commands for serving, diagnostics, demo traces, initialization, and trace queries.
- Added lifecycle documentation, architecture decisions, tests, CI, and release policies.
- Enforced the Apache-2.0 `@causentra/*` and private `@causentra-enterprise/*` workspace boundary.
- Added validated file/environment configuration with documented precedence.
- Hardened concurrent and intra-batch deduplication, corrupt-record visibility, body-limit responses, and event-type validation.
- Added public API TSDoc and npm archive verification that excludes tests and private paths.
- Added the public adapter-authoring bridge, JSON Schema fixtures and OpenTelemetry projection.
- Added privacy-first OpenAI Agents SDK and LangGraph adapters.
- Added a real compiled-LangGraph compatibility test and defensive handling for its current callback argument ordering.
- Added clean archive installation, cross-platform CI configuration and performance benchmarking.
- Split the local workspace into independently controlled `opensource/` and `enterprise/` editions.

# Causentra — multi-agent observability runtime

> **One runtime. Every agent.**

Pronounced `kaw-SEN-truh`. Causentra is a privacy-first AI agent observability and tracing runtime for Python-first multi-agent systems.

It standardizes agent, model, tool, workflow, handoff, and delegation telemetry across OpenAI Agents, LangGraph/LangChain, CrewAI, Google ADK, Semantic Kernel, AutoGen, custom agents, and OpenTelemetry producers. Causentra runs locally, requires no account, and does not capture prompts, outputs, tool arguments, arbitrary framework state, or error messages by default.

> **Status: stable PyPI release.** Causentra `1.0.0` is available on [PyPI](https://pypi.org/project/causentra/). Production deployments must still complete the security, target-infrastructure, and operational controls in the [deployment runbook](docs/34-production-deployment-runbook.md).

## Workspace shape

This repository is the unified Causentra product workspace. All maintained packages, applications, documentation, examples, templates, and verification live at the repository root.

From root:

- `npm install` and `python -m pip install -e "python[dev]"` to bootstrap the workspace.
- `npm run verify` to run the full repository verification flow.

Install the Python runtime in an application with:

```bash
python -m pip install causentra
```

| Start | Understand | Verify |
|---|---|---|
| [Five-minute Python onboarding](docs/28-developer-onboarding.md) | [Framework and provider support](docs/23-provider-support.md) | [Production readiness](docs/21-public-product-readiness-review.md) |
| [Integration recipes](docs/17-integration-guide.md) | [Architecture](docs/06-solution-architecture.md) | [Verification evidence](docs/26-verification-evidence.md) |
| [Product FAQ](docs/31-product-faq.md) | [Package catalog](docs/38-package-catalog.md) | [Deployment requirements](docs/34-production-deployment-runbook.md) |

## Why this project exists

Agent failures cross framework callbacks, model calls, tool calls, and application code. Reconstructing them from logs is slow, and framework-native traces do not create a portable operating contract. Causentra is testing a focused proposition:

> Go from an unexplained local agent failure to a navigable, privacy-safe trace in under five minutes.

The project is not an agent orchestrator and does not execute tools. It is the open instrumentation and local debugging layer beneath agent applications.

## Where Causentra fits

| If you need | Causentra provides |
|---|---|
| One trace across multiple agent frameworks | Portable lifecycle semantics and W3C parent continuity |
| Local-first LLM and agent debugging | Self-hosted collection, inspection, export, and deletion |
| Agent-specific OpenTelemetry interoperability | OTel projection/export plus OTLP JSON/protobuf ingestion |
| Broker-ready agent events | Durable HTTP, WebSocket, Kafka, NATS, Redis Streams, and MQTT delivery |
| A safe extension boundary | Adapter conformance and permissioned process plugins |

Framework-native tracing remains useful for framework-specific depth. OpenTelemetry remains the general telemetry standard. Causentra connects those worlds with a framework-neutral agent lifecycle and local operational experience; it does not replace either one.

## What works today

| Capability | Status |
|---|---|
| Framework-neutral Python SDK | Maintained from source; Python 3.10+ |
| OpenAI Agents adapters | Maintained; Python `0.18.x` and JavaScript `0.13.x` |
| LangGraph/LangChain adapters | Maintained; Python `1.2.x`/`1.4.x` and supported JS bands |
| CrewAI, Google ADK, Semantic Kernel and AutoGen adapters | Maintained Python adapters against narrow tested bands; CrewAI and Semantic Kernel production use is currently dependency-audit gated |
| Framework-neutral TypeScript SDK | Verified `@causentra/sdk` 1.0.0 workspace protocol peer; see the [package catalog](docs/38-package-catalog.md) for registry status |
| Custom Python and TypeScript agents | Supported through explicit SDK spans |
| Authenticated Python collector | Durable SQLite WAL, project isolation, quotas, readiness and operator metrics |
| Local dashboard collector | Maintained Node.js loopback service and durable NDJSON store |
| Durable delivery | SQLite spool plus HTTP, WebSocket, Kafka, NATS JetStream, Redis Streams and MQTT |
| Event and plugin processing | Named durable subscriptions, retry/dead letter/replay and permissioned process plugins |
| Causal trace tree, timeline, CLI and query API | Maintained |
| Safe metadata search plus framework/provider/model/status/session/tool filters | Maintained in local API and dashboard |
| First-class handoff/delegation view | Maintained source-to-target relationship cards plus causal nesting |
| Portable trace export/import, deletion and explicit pruning | Maintained |
| Schema fixtures, adapter-authoring bridge and adapter template | Maintained and executable |
| Adapter conformance contract | Maintained; validates schema, lifecycle, privacy, identity and parent continuity |
| OTLP/HTTP trace ingestion | Maintained for JSON and protobuf, including gzip and partial success |
| OpenTelemetry semantic projection and OTLP/HTTP protobuf exporter | Maintained public bridge; GenAI conventions remain evolving |
| W3C Trace Context carrier | Maintained in the TypeScript SDK |
| Cross-framework trace continuity | Tested with real OpenAI Agents + compiled LangGraph execution |
| Provider/model/token/cost support | 8 deep Python response mappings plus 7 compatible profiles across all 15 canonical provider IDs; custom IDs remain supported |
| AutoGen and other OTel-native Python frameworks | AutoGen native OTel exporter maintained; generic OTLP remains the open path |

Support is deliberately tiered: six Python framework families have maintained native adapters; eight providers have deep response mappings; seven more have compatible profiles, covering all 15 canonical provider IDs; and standards-compliant producers can use OTLP. Provider SDK monkey-patching is not used. Applications wrap calls with `call_model`, `call_model_async`, or `provider_model`, preserving SDK ownership and credentials.

Adapter compatibility is not a security waiver. The current CrewAI and Semantic Kernel dependency graphs contain unresolved upstream advisories and are not approved for production promotion; use named extras and review the [dated verification evidence](docs/26-verification-evidence.md).

## Try Causentra locally

For the authenticated Python-first path, start with the [five-minute developer onboarding](docs/28-developer-onboarding.md). The shorter flow below starts the local Node.js dashboard for repository development.

Requirements: Python 3.10+ for producers; Node.js 22 or 24 and npm for the local collector/dashboard.

```bash
npm install
npm run build
npm run dev
```

Install the published Python SDK with the maintained adapters you use, then emit a trace:

```bash
python -m pip install "causentra[openai-agents,langgraph,transports]"
npm run example:python
```

Open `http://127.0.0.1:4318`, then create a synthetic trace:

```bash
npm run demo
```

Run the real-framework examples against the local collector:

```bash
npm run example:openai
npm run example:langgraph
npm run example:mixed
```

Validate the complete workspace:

```bash
npm run verify
npm run benchmark
npm run python:verify
npm run python:benchmark
npm run python:benchmark:collector
```

The Python runtime is published as the stable [`causentra 1.0.0`](https://pypi.org/project/causentra/) release:

```bash
python -m pip install causentra
```

See the [PyPI release runbook](docs/32-pypi-release.md) for installation variants and future release operations.

## Integrate an application

- [Five-minute authenticated Python onboarding](docs/28-developer-onboarding.md)
- [Direct SDK, six native framework adapters, collector and transport recipes](docs/17-integration-guide.md)
- [Production Python runtime](docs/24-production-python-runtime.md)
- [Single-node production deployment runbook](docs/34-production-deployment-runbook.md)
- [Transport and plugin operations](docs/25-transport-plugin-operations.md)
- [Adapter template](templates/community-adapter/README.md)
- [Event schema compatibility policy](docs/18-schema-compatibility.md)
- [Data, API, and security model](docs/07-data-api-security.md)
- [Current limitations and release evidence](docs/19-local-release-readiness.md)

The common contract standardizes trace correlation, W3C context handoff, and the `workflow`, `agent`, `model`, `tool`, error, timing, status, provider/model/usage, and cost-provenance vocabulary. It ships no provider price table and never infers costs silently; callers may opt into a versioned local catalog with explicit `catalog_estimate` provenance. It does not capture hidden reasoning or re-execute tools. Event replay means redelivery to an idempotent handler, never agent side-effect replay. See the [local assurance controls](docs/37-assurance-controls.md) and [product readiness review](docs/21-public-product-readiness-review.md).

## One product, evolving capabilities

Causentra has one codebase, one event contract, and one package namespace. It includes local instrumentation, maintained adapters, collection, inspection, privacy controls, portability, and security fixes without trace-count limits, forced telemetry, account requirements, or cloud dependency. Future managed capabilities—such as shared retention, collaboration, alerts, analytics, identity, audit, governance, and support—will extend this same product rather than form a separate product version.

## Participation

- Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing code or schema changes.
- Use the issue forms for reproducible bugs, adapter requests, and feature proposals.
- Read [SUPPORT.md](SUPPORT.md) for support boundaries and [SECURITY.md](SECURITY.md) for private vulnerability reporting.
- Project roles and decision rights are defined in [GOVERNANCE.md](GOVERNANCE.md).
- The evidence-driven public roadmap is in [ROADMAP.md](ROADMAP.md).

## Support this project

Causentra is an Apache-2.0 project with one maintained product line.

If this project helps your team, there are three ways to contribute meaningfully:

- Contribute validation evidence: help move validation gates, reduce debt, and improve production readiness.
- Contribute code or docs: implement adapters, improve tests, tighten edge-case coverage, or reduce ambiguity in docs.
- Improve ecosystem quality: report reproducible issues, benchmark missing cases, and review architecture claims.

### Why support helps

This project is at a critical stage where runtime reliability, security evidence, and production-grade documentation need sustained review. Community support helps with:
- Continuous maintenance and triage
- Security and compatibility test expansion
- Better compatibility and release hardening
- Real-world integration evidence and benchmarks

Read [FUNDING.md](FUNDING.md) for current support details.

### Contributor guide

New contributors are welcome. Start with:
- [CONTRIBUTING.md](CONTRIBUTING.md) for workflow, review expectations, and coding checks
- [SUPPORT.md](SUPPORT.md) for response and escalation policy
- [GOVERNANCE.md](GOVERNANCE.md) for decision rights
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for project standards

You can also help by reviewing the repo for:
- docs vs implementation consistency
- broken links and stale references
- boundary regressions
- missing edge-case tests in adapters, transports, and runtime flows

## Documentation

Start with the [developer onboarding](docs/28-developer-onboarding.md), [product FAQ](docs/31-product-faq.md), [PRD](docs/02-prd.md), and [solution architecture](docs/06-solution-architecture.md). The [documentation index](docs/README.md) covers the complete lifecycle, the [brand architecture](docs/29-brand-architecture.md) defines product naming, and the [discoverability plan](docs/30-discoverability-and-search.md) defines truthful repository and search metadata.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

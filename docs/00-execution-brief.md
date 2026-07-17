# Enhanced execution prompt

## Role

Act as the founding enterprise product architect, principal engineer, security lead, delivery lead, and go-to-market strategist for Causentra.

## Objective

Transform the supplied idea into a high-quality, commercially viable developer-infrastructure product. First establish evidence-based product and engineering decisions; then deliver a tested vertical slice that validates the riskiest assumptions.

## Product thesis

Causentra is a framework-neutral observability and operations layer for AI agents. Its open-source local runtime gives developers one event contract, trace capture, execution inspection, and replay context. A later managed control plane monetizes retention, collaboration, analytics, alerting, governance, and enterprise deployment.

## Execution rules

1. Treat claims in the idea as hypotheses until validated.
2. Select one narrow adoption wedge before expanding adapters or transports.
3. Separate open data-plane capabilities from paid control-plane capabilities.
4. Design stable contracts before framework integrations.
5. Make security, privacy, operability, and cost explicit requirements.
6. Use measurable phase exit criteria instead of feature-count milestones.
7. Keep documents decision-oriented, traceable, and non-repetitive.
8. Build a working vertical slice after documentation; test critical behavior.

## Required outputs

- Product analysis, PRD, personas, journeys, positioning, and acceptance criteria
- Solution, data, API, security, deployment, hosting, quality, and operations plans
- Delivery roadmap, risk register, pricing, metrics, launch, community, and sales plans
- Architecture decision records
- A runnable SDK, local ingestion service, trace store, dashboard, CLI, example, tests, and CI

## Current product constraints

- Primary user: Python developer building or operating a multi-agent workflow
- Supported client: TypeScript/Node.js remains maintained against the same wire contract
- First use case: diagnose slow or failed local agent executions in under five minutes
- First transport: HTTP
- First deployment: local single-user process
- Data default: local-only with explicit capture and redaction controls
- Compatibility: Python 3.10–3.13 and active Node.js LTS releases; no framework lock-in
- Deferred: hosted multi-tenancy, billing, SSO/SCIM, Kubernetes operator, policy engine, marketplace, and production replay execution

This supersedes the TypeScript-first constraint from the initial execution pass. The reason and compatibility consequences are recorded in [ADR-005](adr/005-python-first-multilanguage-runtime.md).

## Definition of done

The increment is complete when a Python or TypeScript user can install dependencies, start the runtime, emit a demo workflow, inspect its trace and spans in a browser, query it through the CLI/API, and pass automated build/test checks using documented commands.

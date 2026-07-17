# Market and positioning

## Ideal customer profile

Start with software teams of 5–50 engineers shipping agent workflows, using more than one model/tool provider, and lacking a dedicated observability platform team. The initial champion is a senior AI/application engineer; the later buyer is the engineering or platform leader.

## Jobs to be done

- When an agent fails, show where and why without reconstructing logs.
- Before release, compare latency, cost, and reliability across workflows.
- During incidents, share durable execution evidence across a team.
- Under governance, prove what the agent attempted and what policy allowed.

## Alternatives

| Alternative | Strength | Gap Causentra targets |
|---|---|---|
| Console logs | Universal and free | No semantic graph, correlation, or replay context |
| Framework-native tracing | Deep integration | Framework lock-in and fragmented views |
| Generic APM/OpenTelemetry | Mature telemetry ecosystem | Setup and agent-specific experience |
| LLM observability suites | Rich analytics | Often cloud-first or model-call-centric |
| Internal platform | Exact fit | High maintenance and slow ecosystem coverage |

## Positioning

For teams shipping AI agents that need fast, trustworthy debugging across changing frameworks, Causentra is the local-first agent operations layer that turns every execution into a portable trace. Unlike framework-specific debuggers or cloud-only analytics, it begins with an open semantic contract and keeps data local by default.

## Messaging hierarchy

1. Diagnose an agent execution in minutes.
2. One trace across models, tools, and frameworks.
3. Local by default; export when ready.
4. Open instrumentation, managed operations.

Avoid claims that Causentra replaces OpenTelemetry, guarantees deterministic replay, or captures private chain-of-thought. “Replay” means recorded execution inspection until guarded re-execution is separately released.

## Competitive validation

Before public beta, refresh the competitor matrix using current primary product documentation, test onboarding for the five most-used alternatives, and record feature parity by evidence. Do not base roadmap priority on static market claims.

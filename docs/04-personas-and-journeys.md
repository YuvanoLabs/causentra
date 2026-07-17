# Personas and journeys

## Personas

| Persona | Goal | Pain | Product promise |
|---|---|---|---|
| Maya, agent developer | Ship reliable workflows | Callback plumbing and opaque failures | First useful trace in five minutes |
| Omar, platform engineer | Standardize telemetry | Framework and team fragmentation | Portable schema and controlled exporters |
| Lin, engineering lead | Control quality and spend | No shared operational evidence | Team analytics and alerts in cloud phase |
| Priya, security lead | Limit agent risk | Sensitive prompts and tool access | Local defaults, redaction, policy/audit roadmap |

## Critical M0 journey

1. Maya installs the repository dependencies and runs `npm run dev`.
2. She instruments a workflow with `runtime.trace()` and nested `runtime.span()` calls.
3. The SDK emits redacted events to localhost and flushes at workflow completion.
4. The dashboard shows the trace, failed span, latency, and ordered events.
5. Maya uses the trace identifier in the CLI/API to share structured evidence.

Acceptance: a new Python or TypeScript user completes the journey from the README without maintainer assistance in five minutes.

## Cloud journey

Omar creates an organization and project, receives a scoped ingest key, configures retention and redaction policy, invites Maya, and sets a latency alert. Priya verifies audit logs and data residency. This flow is a future control-plane requirement, not an M0 capability.

## Experience principles

- Useful before configurable
- Trace IDs visible everywhere
- Fail open for application execution, fail visibly for telemetry
- Explain missing data instead of presenting false certainty
- Separate recorded facts from inferred insights
- Require explicit confirmation before any side-effecting replay

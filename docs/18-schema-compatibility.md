# Schema and adapter compatibility

## Stable boundary

`RuntimeEvent` schema `1.0` is the interchange boundary across SDKs, adapters, local storage, collectors, and future enterprise services. Package versions and schema versions evolve independently.

The canonical artifact is `@causentra/sdk/schema/v1`, backed by fixtures in `packages/sdk/fixtures/v1` and the runtime validator.

## Change policy

| Change | Schema effect | Requirement |
|---|---|---|
| Add optional attribute | Compatible | Minor package release and fixture |
| Add namespaced event type | Compatible | Document producer/consumer behavior |
| Add optional envelope field | Schema minor review | Old readers must preserve/ignore safely |
| Change meaning or required field | Breaking | New schema major and migration tool |
| Remove event/field | Breaking | Deprecation window then new schema major |

Unknown dot-namespaced event types remain valid. Core lifecycle types retain their current semantics throughout schema v1.

Schema v1 writes W3C-compatible 16-hex span identifiers. Readers also accept the 32-hex span identifiers emitted by early `0.0.x` builds so pre-alpha local data remains readable. Trace and event identifiers remain 32-hex.

## Adapter policy

- Adapters depend only on the public SDK package.
- Framework peer ranges are narrow until compatibility CI proves otherwise.
- Inputs, outputs, prompts, state, tool arguments, and error messages are excluded by default.
- A framework minor upgrade requires compilation and lifecycle-fixture verification.
- LangGraph additionally runs a real compiled in-process graph through `RunnableConfig.callbacks`; direct callback mocks alone are insufficient.
- Framework-specific details use namespaced attributes, not new core fields.
- Maintained adapters run `assertAdapterConformance` against completed lifecycle and privacy fixtures.

## Multi-agent relationships

Handoffs and delegations are namespaced lifecycle events: `agent.handoff.start/end` and `agent.delegation.start/end`. Their portable attributes are:

| Attribute | Meaning |
|---|---|
| `causentra.agent.relationship.kind` | `handoff` or `delegation` |
| `causentra.agent.from.name` | Source agent name |
| `causentra.agent.to.name` | Target agent name |
| `causentra.agent.relationship.id` | Optional producer relationship ID |

The relationship span participates in the normal parent chain, so nested target work remains causally queryable without a framework-specific schema fork.

## Ordering across producers

`sequence` is process-local and monotonic within a producer trace. Readers merging framework, process, or OTLP streams order by timestamp, lifecycle phase (start before point events before end), sequence, then event ID. Clock skew is not silently corrected.

## OpenTelemetry mapping

`OpenTelemetryProjector` remains the dependency-free mapping surface. `@causentra/opentelemetry` uses the official OpenTelemetry JavaScript SDK to create causal spans and can export OTLP/HTTP protobuf. The local collector also accepts OTLP/HTTP JSON and protobuf and converts spans into schema-v1 lifecycle pairs. Resource attributes stay separate from span attributes, and content-bearing attributes are omitted at the OTLP ingress boundary because they may contain personal or confidential data.

OpenTelemetry GenAI conventions are still evolving. Mapping changes require fixtures, an ADR when meaning changes, and a changelog entry. See the [OpenTelemetry GenAI attribute registry](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/).

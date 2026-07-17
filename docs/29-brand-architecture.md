# Causentra brand architecture

## Brand decision

**Causentra** is the product and company-facing master brand. Pronunciation: `kaw-SEN-truh`.

The name combines causal execution with central infrastructure. It represents the portable causal contract connecting agents, frameworks, providers, tools, events, and transports.

Brand promise:

> One runtime. Every agent.

Category description:

> Causal runtime infrastructure for multi-agent systems.

## Product family

| Name | Purpose |
|---|---|
| Causentra SDK | Python-first instrumentation and shared event contract |
| Causentra Runtime | Local runtime, event processing, delivery, and collection |
| Causentra Console | Trace inspection and operational interface |
| Causentra Replay | Safe event redelivery and future sandboxed evaluation workflows |
| Causentra Relay | Durable HTTP, WebSocket and broker transport layer |
| Causentra Connectors | Maintained framework and provider adapters |
| Causentra Community | Apache-2.0 public edition |
| Causentra Enterprise | Private extensions built only on released public contracts |
| Causentra Cloud | Reserved future managed service; not currently offered |

“Replay” never means automatic re-execution of side-effecting tools. Current public replay is durable event redelivery to an idempotent handler.

## Technical names

| Surface | Approved identifier |
|---|---|
| Python distribution/import | `causentra` |
| Python primary class | `CausentraRuntime` |
| Python CLI | `causentra` |
| Python collector CLI | `causentra-collector` |
| Enterprise Python import | `causentra_enterprise` |
| Public npm scope | `@causentra/*` |
| Private npm scope | `@causentra-enterprise/*` |
| Environment prefix | `CAUSENTRA_*` |
| Semantic attributes | `causentra.*` |
| Local state directory | `.causentra/` |

## Edition language

Use **Causentra Community** for the public edition and **Causentra Enterprise** for private extensions. Do not call the public edition “basic,” “lite,” or “free-only.” The public runtime is a complete local product and remains the adoption and trust foundation.

## Voice

- Precise, evidence-based, and operational
- Developer-first without assuming one framework or provider
- Explicit about privacy defaults and failure behavior
- Clear about implemented, validated, planned, and externally gated capabilities
- No claims of hosted availability, certification, customer adoption, or unlimited scale without evidence

## Clearance and launch gate

The repository adopts the Causentra working brand, but no domain, package registry, social handle, or trademark ownership is claimed by source code. The owner must complete clearance and reserve the required identities before public publication. If clearance fails, rename before the first public package release; do not introduce compatibility aliases for an unpublished name.

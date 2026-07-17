# Risk and compliance plan

## Risk register

| Risk | Likelihood/impact | Mitigation | Trigger |
|---|---|---|---|
| Crowded observability market | High/High | Narrow local-first wedge and interoperability | Low retained use after alpha |
| Framework churn | High/Medium | Stable core, thin tested adapters | Adapter breaks twice/quarter |
| Sensitive data capture | Medium/Critical | Data minimization, redaction, local default | Secret/personal data incident |
| “Replay” causes side effects | Medium/Critical | Inspection-only now; future sandbox/approval | Any unintended tool call |
| Cloud cost exceeds revenue | Medium/High | Quotas, compression, tiered retention | COGS >30% revenue |
| Schema fragmentation | Medium/High | RFCs, fixtures, OTel mapping | Adapter-specific core fields grow |
| Event loss undermines trust | Medium/High | Explicit semantics, spool, loss metrics | Undetected accepted-event loss |
| Open-source/cloud conflict | Medium/Medium | Published feature boundary | Community fork/complaints repeat |
| Enterprise work derails core | Medium/High | Design-partner qualification | >40% roadmap one-off work |
| Vendor dependency | Medium/Medium | Portable data and infrastructure interfaces | Exit cost exceeds two quarters |
| Optional framework supply chain | High/High | Named extras, exact compatibility tests, SBOM/advisory review, explicit dispositions | New critical/high advisory or blocked fix |
| Search or AI answer misrepresentation | Medium/Medium | Canonical FAQ, dated evidence, `llms.txt`, corrections and claim review | Incorrect capability/availability claim recurs |

## Open supply-chain dispositions

The 2026-07-17 aggregate compatibility audit reports eight advisories across four optional transitive packages. The latest CrewAI release, `1.15.3`, constrains `chromadb`, `json-repair`, and `mcp` below their fixed or acceptable versions; the latest Semantic Kernel release, `1.44.0`, resolves through `openapi-core` to a Werkzeug band below the available fixes. The core Causentra runtime does not depend on these packages.

Until compatible upstream releases are validated:

- keep CrewAI and Semantic Kernel out of production-approved installation profiles;
- install only required named extras, never the aggregate `frameworks` extra in production;
- fail release review on any undispositioned high or critical advisory;
- rerun exact adapter, dependency, and advisory gates before changing this disposition.

## Compliance sequence

1. M0: data inventory, secure defaults, dependency/secret scanning, disclosure contact.
2. Public beta: privacy policy, terms, DPA template, subprocessors, deletion workflow, SBOM/provenance.
3. Cloud GA: formal access reviews, change management, incident/BCP evidence, vendor risk, retention controls.
4. Enterprise: SOC 2 Type I then Type II based on demand; GDPR/UK GDPR operating evidence; regional and sector requirements only with qualified opportunities.

Certification is an outcome of operating controls, not a substitute for them. Legal counsel must validate jurisdiction-specific commitments.

## AI-specific governance

The platform records execution evidence but does not infer that an agent is safe or compliant. Analytics must label inferred scores, preserve source events, expose uncertainty, and allow human review. Never store hidden chain-of-thought; retain only application-supplied prompts/outputs under policy.

## Review cadence

Review critical risks monthly, the full register quarterly, and immediately after a material incident or architecture change. Each mitigation requires an owner and measurable evidence before risk is reduced.

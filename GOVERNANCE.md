# Governance

Causentra uses maintainer-led, evidence-driven governance during its release-candidate phase. The objective is to grow into a multi-maintainer project without allowing commercial priorities to weaken product quality or user control.

## Roles

| Role | Responsibility |
|---|---|
| Contributor | Issues, documentation, code, tests, reviews |
| Reviewer | Technical review in an explicitly assigned area |
| Maintainer | Merge, release, triage, security, roadmap and compatibility decisions |
| Security responder | Private vulnerability assessment and coordinated disclosure |

Role assignment requires sustained, constructive contributions and demonstrated judgment. It is recorded publicly when the repository exists; no role is implied by employment, funding, or contribution volume alone.

## Decision process

- Small fixes use pull-request consensus from the responsible maintainer.
- API, schema, package, privacy, storage, or security changes require a linked issue and written decision evidence.
- Durable architecture decisions use an ADR.
- Breaking contract changes require migration analysis, compatibility fixtures, deprecation policy, and maintainer approval.
- Unresolved decisions are decided by the lead maintainer, with rationale recorded publicly.

## Product safeguards

Security fixes, local data portability, maintained core instrumentation, and user-owned local operation are product commitments. Funding does not purchase schema control or undisclosed roadmap priority.

## Changes to governance

Governance changes use a public pull request with a minimum seven-day comment period after the project has external contributors. Emergency security response is exempt from the waiting period but must be documented after coordinated disclosure.

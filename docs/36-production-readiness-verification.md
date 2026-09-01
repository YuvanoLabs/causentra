# Production-readiness verification update

Verification date: 2026-08-31. This is local, deterministic release evidence;
it does not substitute for the external gates in the
[production-readiness assessment](35-production-readiness-assessment.md).

## Closed repository-controlled findings

| Finding | Correction | Evidence |
|---|---|---|
| Funding copy claimed that a removed Sponsor configuration was active. | Made the no-active-funding status explicit and made sponsorship configuration optional in the owner checklist. | `npm run verify:community` validates 192 local documentation links. |
| Generated runtime/cache directories could be scanned as source and trigger false brand violations. | Excluded `.causentra`, `.venv`, `.venv-publish`, and test caches from the source-only brand check. | `npm run verify:brand` passes with the existing runtime directory present. |
| A checkout without an editable Python install could not reproduce the documented test flow. | Documented the editable development install and configured pytest's `src` path. | The root suite passes from a clean, isolated Python environment. |
| Base development checks required optional framework packages solely for mypy imports. | Declared missing optional framework imports to mypy while keeping the exact-framework compatibility jobs separate. | Strict mypy passes against the dependency-free development environment. |
| The Python build bypassed its declared `setuptools>=77` requirement. | Changed the build helper to use PEP 517 isolation. | An isolated sdist and universal wheel build, Twine metadata check, and clean-wheel install pass. |
| The publish workflow did not execute the full repository gate and did not validate artifact metadata. | It now installs the local package correctly, runs `npm run verify`, and checks distribution metadata before upload. | Workflow definition is covered by the immutable-action discovery check. |
| Detached-signature documentation claimed that Python parity and collector enforcement were missing. | Added normalized batch signing, local Python ECDSA, explicit KMS/Vault digest adapters, and fail-closed collector verification with unsigned compatibility labelling. | Focused tamper, unknown/revoked-key, KMS/Vault contract, and signed-collector tests pass. |
| Collector keys could read raw attributes or delete traces without a least-privilege option. | Added scoped roles, summary/debug projections, durable metadata-only audit records, and scope checks on every collector operation. | Restricted-key, cross-project, field-stripping, delete-denial, and audit-decision tests pass. |
| Loop control, evaluation, and pricing backlog items had no bounded implementation. | Added an opt-in lifecycle aggregator, deterministic offline rules, and a caller-supplied effective-dated integer-rate catalog. | Aggregation boundary, repeatable score, unknown-price, and effective-date tests pass. |

## Current local evidence

The following passed on Windows with Python 3.11.9 and Node 26.5.0:

- `npm run verify`: all TypeScript builds/tests, 124 Python tests (13
  environment-gated skips), package contents, clean wheel, and clean npm
  consumer-install gates.
- `npm run verify:install:adapters`: clean installation of all six npm archives
  plus their exact maintained framework peers.
- `npm audit --audit-level=high`: no vulnerabilities.
- `pip check`, Bandit medium/high source scan, and `pip-audit` of the core
  package: passed with no known vulnerabilities.
- Benchmarks: TypeScript SDK 0.0253 ms/event; Python runtime p95 0.1727
  ms/event; Python collector 8,030 events/second.

The resulting `1.0.0` sdist and universal wheel are validated stable-release
artifacts. PyPI files are immutable, so a correction requires a new version.

## Ongoing deployment-assurance controls outside this workspace

Record the following evidence for each production deployment and future release
promotion:

- PyPI Trusted Publisher registration for the protected `pypi` GitHub
  environment, verified package ownership/recovery access, and reviewed tag
  protection/branch controls.
- An independent security review with no unresolved critical or high finding,
  plus an SBOM, license, and advisory disposition for each selected production
  extra. The CrewAI and Semantic Kernel extras remain separately blocked by
  upstream advisories documented in
  [verification evidence](26-verification-evidence.md).
- Remote Windows, macOS, and Linux Python/Node matrix results; target TLS,
  proxy, and broker fault/recovery tests; and a verified backup/restore drill.
- A representative 24-hour soak with bounded storage and operational alerts,
  a rollback rehearsal, and named on-call/incident ownership.
- Five observed external onboarding sessions with at least four successful
  first traces inside five minutes.

These are evidence and owner-control requirements, not code changes that can
be truthfully completed from a local workspace. They remain required even
though the package uses a stable release version.

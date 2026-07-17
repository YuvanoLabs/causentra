# Verification evidence

## Automated gates

| Gate | Coverage |
|---|---|
| Ruff | all public Python source, tests, scripts and benchmarks |
| mypy strict | complete `causentra` public source |
| pytest | schema, runtime, providers, adapters, transports, spool, event engine, replay, collector, plugins, OTel and packaging behavior |
| Exact framework suite | six native adapters against pinned supported releases |
| TypeScript workspace | strict builds, tests, integration, package contents and clean installs |
| Brand contract | public/enterprise namespaces, CLI, environment variables and legacy-name exclusion |
| Discovery contract | README positioning, FAQ, `llms.txt` links, citation/package metadata, and immutable GitHub Actions references |
| Packaging | wheel/sdist build and isolated dependency-free wheel smoke test |
| Security audit | npm advisory audit, dependency-free Python artifact audit, Bandit medium/high source gate, and a separate optional-framework environment audit |
| Performance | runtime p95 per event and durable collector throughput gates |

Run locally without publishing or deployment:

```bash
npm run verify
npm run benchmark
npm run python:benchmark
npm run python:benchmark:collector
```

## Release evidence levels

| Level | Meaning |
|---|---|
| Implemented | Code and deterministic unit/contract tests exist |
| Compatibility validated | Exact optional dependency is installed and its public registration surface passes |
| Integration validated | Producer-to-collector or real framework execution passes |
| Operationally validated | Load, soak, failure injection and recovery evidence is recorded on target infrastructure |
| Independently assured | External security review and owner sign-off are complete |

The workspace establishes the first three levels locally. CI definitions cover the declared OS/Python matrix and optional dependency bands. Operational and independent assurance require the repository owner or deployment operator because they depend on target infrastructure, accounts and reviewed release credentials.

## Latest local evidence

Evidence date: 2026-07-17. Environment: Windows, Python 3.11.9, Node 26.5.0.

| Gate | Result |
|---|---|
| Public Python | 92 passed, including authenticated onboarding; 10 environment-gated skips; strict Ruff and mypy passed |
| Exact Python frameworks | 12 passed across the six supported framework families |
| Public packaging | wheel/sdist built; dependency-free clean-wheel install passed |
| TypeScript workspace | strict build plus 45 package/integration/template tests passed |
| Public boundary/docs/packages | Causentra brand gate, OSS boundary, repository discovery gate, 119 local documentation links, archive contents, and clean consumer installs for all six npm archives plus exact framework peers passed |
| Enterprise boundary | Python/TypeScript dependency boundary, strict checks, one contract test under pytest 9.1.1, and private wheel/sdist build passed |
| Runtime benchmark | Python p95 0.1366 ms/event and TypeScript 0.0272 ms/event; budget below 5 ms/event |
| Collector benchmark | 4,801 events/second; budget at least 1,000 events/second |
| Security tooling | npm audit: 0 vulnerabilities; the dependency-free public core and internal Enterprise package report no known advisories (unpublished internal distributions are skipped by the index); Bandit medium/high gate passed |
| Optional framework environment | Exact six-adapter tests: 12 passed with pytest 9.1.1 and `pip check` clean; audit: 8 advisories across `chromadb`, `json-repair`, `mcp`, and `werkzeug` |

The six live transport tests are present but intentionally not counted as passed locally because no broker or hosted receiver was started. The manual workflow fails when any required target endpoint is absent.

The optional-framework findings are not mandatory Causentra runtime dependencies. The latest CrewAI release, `1.15.3`, constrains `chromadb`, `json-repair`, and `mcp` below the fixed or acceptable versions; the latest Semantic Kernel release, `1.44.0`, resolves through `openapi-core` to Werkzeug below available fixes. CrewAI and Semantic Kernel extras therefore remain production-gated, and the aggregate `frameworks` extra must not be promoted for production. Compatibility tests passing does not override this security disposition.

## Non-negotiable release failures

- Any content payload captured by a maintained adapter.
- Event loss after a successful local durable commit.
- Cross-project reads or identifier collisions.
- Remote plaintext binding without explicit override.
- Silent worker death, retry exhaustion or storage corruption.
- Public code importing `causentra_enterprise` or sibling enterprise source.
- Enterprise code importing OSS internals instead of the exact public package.

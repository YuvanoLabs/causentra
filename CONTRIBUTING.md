# Contributing

Thank you for helping make agent infrastructure more portable, trustworthy, and useful. Causentra is a public source release candidate: focused bug reports, integration evidence, documentation corrections, and small tested changes are especially valuable.

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Before opening work

1. Search existing issues and the [roadmap](ROADMAP.md).
2. Use the appropriate issue form. Reproduction questions belong in bug reports; broad designs belong in feature or adapter proposals.
3. Open an issue before large changes, new packages, dependencies, adapters, schema fields, storage formats, security behavior, or public APIs.
4. Never include credentials, real prompts, provider responses, customer data, or private incident records.

Small documentation fixes may go directly to a pull request.

## Development setup

Requirements: Python 3.10–3.13, Node.js 22 or 24, and npm.

```bash
npm install
npm run verify
npm run benchmark
npm run python:benchmark
npm run python:benchmark:collector
```

Useful focused commands:

```bash
npm run typecheck
npm test
npm run verify
npm run verify:packages
```

The extended package-consumer gate resolves real framework peers and requires registry access:

```bash
npm run verify:install:adapters
```

## Change standards

- Keep instrumentation fail-open; telemetry failure must not replace application results or exceptions.
- Default to excluding prompt, output, state, tool-argument, metadata, and error-message content.
- Add or update tests for behavior, failure paths, privacy, and framework compatibility.
- Schema changes require compatibility fixtures and an ADR when meaning or evolution rules change.
- New dependencies require a reason, license review, maintenance assessment, and audit evidence.
- Public types, configuration, error behavior, and non-obvious trust boundaries require TSDoc.
- Public Python APIs require docstrings and strict mypy/Ruff compliance.
- Comments explain contracts and reasoning; they do not narrate syntax.

## Commit and pull-request workflow

1. Create a branch from the current default branch.
2. Make one coherent change; avoid unrelated formatting or generated artifacts.
3. Add tests and documentation in the same change.
4. Run `npm run verify` locally. Run the benchmark for SDK hot-path changes.
5. Open a pull request using the repository template.
6. Link the issue, explain user impact and risks, and include exact verification evidence.
7. Respond to review and keep the branch current. Maintainers may ask for changes to be split.

A pull request is ready to merge only when required checks pass, review concerns are resolved, documentation is accurate, and the change has a clear compatibility decision. Maintainers use squash merge unless release history requires otherwise.

## Adapter contributions

Start from the executable [community adapter template](templates/community-adapter/README.md). It is compiled and run by the root test suite and demonstrates the required privacy, lifecycle, relationship, parent-context, and conformance behavior.

An adapter must:

- depend only on the public SDK and a narrow peer range;
- use public framework extension points rather than monkey-patching internals;
- map lifecycle without payload capture by default;
- include a real-framework integration test, not only callback mocks;
- document supported versions, limitations, shutdown/flush behavior, and privacy controls;
- identify a maintainer or explicitly remain experimental.

Submit an adapter request before implementation so naming and semantic mapping can be agreed.

## Review and ownership

Maintainers review for correctness, compatibility, privacy, operability, and long-term maintenance cost. Acceptance is not guaranteed merely because checks pass. Decision rights and escalation are described in [GOVERNANCE.md](GOVERNANCE.md).

## Security

Do not report vulnerabilities in public issues or pull requests. Follow [SECURITY.md](SECURITY.md).

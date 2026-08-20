## Outcome

Describe the user or maintainer problem solved. Link the issue with `Closes #...` when applicable.

## Change

Summarize the implementation and any alternatives rejected.

## Trust and compatibility

- [ ] Changes introduce no undeclared package or source coupling.
- [ ] Sensitive content remains excluded by default.
- [ ] Public API, schema, configuration and failure behavior are documented.
- [ ] Compatibility/migration impact is stated; fixtures or ADR are included when required.
- [ ] No unrelated generated files, credentials, private traces or customer data are included.

## Verification

- [ ] `npm run verify`
- [ ] Relevant real-framework integration test
- [ ] `npm run benchmark` for SDK hot-path changes, or not applicable
- [ ] Documentation reviewed against actual behavior

Paste concise test evidence and describe any check that is not applicable.

## Operational risk

State failure modes, rollback/revert path, dependency impact, and remaining limitations.

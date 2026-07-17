# Editions and publication boundary

## Decision

Causentra uses an open-core business model with a complete, production-worthy OSS local data plane and a separately built private control plane. “Open” is not a trial tier: local instrumentation, storage, inspection, core adapters, schema, CLI, and portability must remain useful without enterprise code or a cloud account.

| Open source — `@causentra/*` | Enterprise — `@causentra-enterprise/*` |
|---|---|
| Event schema and validation | Organizations, projects, entitlements |
| SDK context, redaction, exporters | Managed regional ingestion and retention |
| Local collector, storage, dashboard | Team collaboration and advanced alerts |
| Core framework adapters and OpenTelemetry interoperability | Cross-project analytics and AI insights |
| CLI and local diagnostics | SSO/SCIM, audit, policy, private deployment |
| Export and migration tools | Contracted SLA and enterprise support tooling |

## Repository controls

- The `opensource/` workspace contains only Apache-2.0 packages and is independently buildable.
- `enterprise/` is a private sibling workspace, never a child of the public edition.
- Enterprise packages are private, UNLICENSED, and use a distinct namespace.
- OSS packages cannot import enterprise packages; `npm run verify:oss` enforces this in CI.
- Enterprise code depends on published OSS contracts, never relative source paths.
- Every public package has an explicit `files` allowlist and public provenance configuration.
- `npm run verify:packages` inspects archives and rejects tests, dependencies, or enterprise paths.

Create the public repository from `opensource/` and the private repository from `enterprise/`. Public npm releases must be generated and inspected package-by-package with `npm pack --dry-run`; never publish the parent orchestration directory.

## Trust commitments

- No artificial limits in local tracing, storage, or inspection.
- No forced telemetry or cloud sign-in.
- Data formats remain documented and exportable.
- Security fixes do not become enterprise-only.
- Enterprise packaging is based on team operations, governance, managed scale, and support.
- Feature ownership changes require an RFC, product approval, and changelog entry.

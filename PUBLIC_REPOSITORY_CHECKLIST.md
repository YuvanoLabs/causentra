# Public repository launch checklist

This checklist is for the repository owner. It does not create a repository, publish packages, or deploy services.

## Identity and ownership

- [ ] Confirm the final product, organization, npm scope, schema domain and trademark position.
- [ ] Publish at least one accountable maintainer identity and an ownership-continuity plan.
- [ ] Confirm `smartbytecoder@gmail.com` is monitored and protected with account recovery controls.
- [ ] Complete GitHub Sponsors enrollment for `YuvanoLabs`; the repository Sponsor button is configured in `.github/FUNDING.yml`.

## Repository creation

- [ ] Create the public repository from this workspace root only.
- [ ] Confirm local caches, runtime test artifacts, credentials, and generated files are excluded from the repository and its history.
- [ ] Copy the exact description and 20-topic set from [repository discoverability and search readiness](docs/30-discoverability-and-search.md); remove any topic that stops being accurate.
- [ ] Add a truthful social preview showing the actual dashboard; do not use future-product mockups without labeling them.
- [ ] Add the final repository URL to Python/npm package metadata and `CITATION.cff`; do not commit guessed organization or domain URLs.
- [ ] Enable Issues, Discussions, private vulnerability reporting, and Sponsorships after their policies/channels exist.

## Repository controls

- [ ] Protect the default branch; require pull requests, reviews, status checks and resolution of conversations.
- [ ] Restrict force pushes/deletion and minimize administrator bypass.
- [ ] Keep GitHub Actions token permissions read-only by default and approve write permissions per workflow.
- [ ] Pin third-party actions to reviewed immutable commit SHAs and schedule dependency review.
- [ ] Configure secret scanning, push protection, Dependabot alerts and dependency updates.
- [ ] Create labels referenced by issue forms: `bug`, `enhancement`, `adapter`, `triage`, `security`, `good first issue`, and `help wanted`.

## Release readiness

- [ ] Run `npm ci`, `npm run verify`, `npm run verify:install:adapters`, both benchmarks, and dependency audits from a clean checkout.
- [ ] Run live Kafka, NATS, Redis, MQTT, WebSocket, TLS/proxy, failure-recovery, backup/restore, and 24-hour soak gates on target infrastructure.
- [ ] Verify the Python 3.10–3.13 and Node 22/24 Windows, Linux and macOS matrices pass remotely.
- [ ] Verify Python/npm package ownership, trusted publishing/provenance, signing and recovery access.
- [ ] Review every wheel, sdist, and npm archive; publish no package from the orchestration parent.
- [ ] Complete an independent security review and resolve critical/high findings.
- [ ] Record a release rollback/deprecation procedure and security advisory workflow.

## Launch evidence

- [ ] Observe five external onboarding sessions and publish anonymized time-to-first-trace results.
- [ ] Provide runnable OpenAI Agents and LangGraph examples with synthetic failures.
- [ ] Record the real 60–90 second product flow and add one screenshot to the README.
- [ ] Publish known limitations, supported versions, benchmark method and data-capture defaults.
- [ ] Confirm `llms.txt`, the product FAQ, package descriptions, citation metadata, and all README links reflect the released version.
- [ ] Staff issue triage for the initial launch window and publish response expectations.

## Search and documentation website

- [ ] Configure one owner-controlled canonical HTTPS URL and use it consistently across GitHub, packages, citation metadata, and documentation.
- [ ] Publish a canonical-only XML sitemap, crawlable navigation, accurate page titles/descriptions, and permissive public-docs crawling rules.
- [ ] Verify Google Search Console and Bing Webmaster Tools; submit the sitemap and enable IndexNow for changed documentation URLs where appropriate.
- [ ] Add and validate truthful software structured data on the hosted product page; do not add ratings, customers, pricing, or availability that do not exist.
- [ ] Monitor indexing, query impressions, qualified onboarding clicks, broken links, and incorrect AI-generated descriptions.

The source may launch only with explicit evidence and limitations. Package preview, product beta, and managed deployment require the phase exit evidence in `ROADMAP.md`.

# Quality strategy

## Quality goals

Correct correlation, loss visibility, privacy safety, compatibility, and debuggability rank above UI breadth. Telemetry failures must not change application business results.

## Test layers

| Layer | Focus | Run |
|---|---|---|
| Static | Strict types, formatting, package boundaries | Every change |
| Unit | Validation, context, redaction, retry, projection | Every change |
| Contract | Event fixtures, adapter conformance, OTLP media types and API errors | Every change |
| Integration | SDK → durable transport → collector; six exact Python frameworks; mixed frameworks; official OTLP exporter | Every change |
| UI smoke | Load, filter, select, relationship view, empty/error states | Before release |
| Performance | throughput, overhead, memory, large traces | Nightly/before release |
| Security | audit, secrets, fuzzed ingestion, dependency/SBOM | CI + scheduled |
| Resilience | restart/lease recovery, bounds, conflict, dead letter, backup, collector outage | Every change plus target soak |

## Critical invariants

- Event IDs are unique and trace IDs remain stable across nested async spans.
- Each started wrapped span ends exactly once.
- Application exceptions are rethrown after sanitized telemetry.
- Invalid batches cause no writes.
- Event order is deterministic.
- Export queues and request bodies are bounded.
- Redaction occurs before an exporter receives data.
- Maintained framework roots preserve a supplied canonical parent trace.
- OTLP conversion never persists known prompt, message, output, tool-argument or exception content.
- Producer-local sequence never overrides cross-producer timestamp ordering.
- Safe metadata search and combined trace filters return only matching facets, exclude private content, and reject malformed identifiers.
- The community template is compiled and its privacy/conformance fixtures run in every root test.
- Reusing an event or batch identifier for different bytes fails closed.
- Collector uniqueness and every read/delete operation include project scope.
- Successful producer acceptance precedes network delivery and survives restart.
- Plugin activation requires explicit trust and integrity for entrypoint artifacts.

## Performance budgets

For an application emitting 100 small events, SDK-only p95 overhead is under 5 ms per event. The durable Python collector gate is 1,000 small events/second in 100-event batches with `synchronous=FULL`. Target deployments additionally record ingest latency, CPU, memory, disk/fsync behavior, backlog recovery, and a 24-hour soak.

## Release gates

No failing required checks, critical/high exploitable dependency finding, unresolved data-loss regression, or unreviewed schema change. A rollback path and known limitations accompany every release. Flaky tests are defects; quarantine requires an owner and expiry date.

## External quality evidence

Public CI must record the declared Python/Node and OS matrix. Target infrastructure must run the manual six-transport gate, failure injection, backup restore, and soak tests. Independent security review and five-user onboarding evidence remain release gates.

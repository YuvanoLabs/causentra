# Roadmap and metrics

## North-star metric

Weekly active instrumented projects that produce at least one trace on three distinct days. This measures recurring operational use while resisting demo/event-volume inflation.

## Metric tree

| Outcome | Measures |
|---|---|
| Acquire | Qualified installs, docs-to-install conversion |
| Activate | First valid trace, time to first trace, dashboard opened |
| Retain | Weekly active projects, 4/8-week project retention |
| Value | Debug sessions, failed traces inspected, diagnosis task time |
| Quality | SDK overhead, dropped events, ingest/query SLOs |
| Monetize | Pilot conversion, MRR/ARR, gross margin, NRR, churn |
| Ecosystem | Maintained adapters/plugins, contributors, schema consumers |

GitHub stars and raw events are supporting reach/scale signals, not the north star.

## Phase roadmap

| Phase | Product outcome | Exit evidence |
|---|---|---|
| 0: vertical slice | End-to-end local trace inspection | Repository acceptance tests pass |
| 1: design-partner alpha | Setup and semantics solve real debugging | 5 active teams; time-to-trace target met |
| 2: product beta | Repeatable adoption | 50 weekly projects; 30% 4-week retention |
| 3: cloud beta | Shared history/alerts create paid intent | 5 pilots; 3 conversions committed |
| 4: cloud GA | Reliable self-serve team product | 20 paid teams; SLOs and support proven |
| 5: governed deployment | Repeatable controls for larger organizations | 3 production customers; repeatable controls |
| 6: ecosystem | Third parties extend distribution | 20 maintained extensions; >25% usage external |

## Instrumentation policy

Local usage telemetry is opt-in, documented, and contains no trace contents. Cloud product analytics use tenant-safe identifiers and defined retention. Metric definitions live in a versioned catalog with owner, query, exclusions, and change history.

## Decision cadence

Weekly product health, monthly unit economics and risk, quarterly strategy. A phase is extended or stopped when its exit evidence is absent; dates do not override evidence.

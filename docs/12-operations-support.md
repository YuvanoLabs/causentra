# Operations and support plan

## Ownership

Each production service has a directly responsible team, runbook, SLO, dashboards, alert thresholds, dependency map, capacity owner, and escalation path. The incident commander is separate from the primary investigator when staffing allows.

## Severity

| Severity | Example | Initial response target |
|---|---|---:|
| SEV-1 | Cross-tenant exposure, widespread ingest loss | 15 min |
| SEV-2 | Region/service materially degraded | 30 min |
| SEV-3 | Limited feature failure or delayed processing | 4 business hours |
| SEV-4 | Question, cosmetic defect, feature request | 1 business day |

Targets become contractual only in paid plans with staffed coverage.

## Incident flow

Detect, declare, assign command, contain, communicate, recover, verify data integrity, and review. Security incidents follow the dedicated breach workflow and legal notification assessment. Customer updates state impact and facts without speculation. Blameless reviews produce owned actions with due dates.

## Core runbooks

- Ingest errors or latency spike
- Event-log backlog growth
- Projection delay or corruption
- Trace query degradation
- Tenant authorization anomaly
- Storage capacity/disk exhaustion
- Credential compromise
- Regional failover and restore

The executable public runtime procedures for spool backlog/dead letters, secure transport acknowledgements, event redelivery, plugin failure, and collector backup/restore are in [transport and plugin operations](25-transport-plugin-operations.md).

## Customer support

Support uses documentation, Discussions, and issues with no guaranteed response. Paid support may add ticketing, defined coverage, named contacts, shared channels, and architecture reviews. Support never requests raw prompts or secrets by default; diagnostic bundles are reviewable before upload.

## Release lifecycle

Publish semantic versions, supported Node/runtime matrix, deprecation notices, migration steps, and checksums/provenance. Critical security fixes receive coordinated releases. Support at most two current minor SDK lines after GA unless a documented support agreement states otherwise.

## Operational readiness review

Before cloud GA verify on-call staffing, alerts linked to user impact, quota enforcement, backup restore, regional recovery, status page, support intake, incident templates, privacy requests, billing reconciliation, and rollback evidence.

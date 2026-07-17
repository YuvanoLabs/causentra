# DevOps and hosting plan

## Local inspection

The runtime is one Node.js process bound to `127.0.0.1:4318`. It serves ingestion, query APIs, and static dashboard assets. Data is appended to a configurable local NDJSON file. No container or cloud account is required.

Operational commands:

```bash
npm run dev
npm run demo
npm test
```

## Public self-hosted Python data plane

The authenticated Python collector is a separate single-node service. It uses project bearer keys, TLS-required remote binding, bounded requests/quotas, readiness, operator metrics, and SQLite WAL on durable block storage. Producers use a durable local outbox and one acknowledged transport.

```bash
causentra-key-hash
causentra-collector --config examples/collector.config.example.json
```

The operator owns TLS certificates, secret distribution/rotation, filesystem encryption, disk alerts, `SqliteCollectorStore.backup`, restore drills, capacity tests, and process supervision. No deployment or hosting is performed by this workspace.

## Environment progression

| Environment | Purpose | Data |
|---|---|---|
| Local | Development and evaluation | Synthetic or user-local |
| CI | Deterministic verification | Synthetic, ephemeral |
| Dev cloud | Integrated managed services | Synthetic |
| Staging | Production topology and load | Sanitized/synthetic |
| Production | Regional customer workloads | Contract-controlled |

No production customer data is copied to lower environments.

## Cloud hosting recommendation

Begin with one cloud and one region, managed Kubernetes only if service count/traffic justifies it; otherwise use managed containers. Use managed relational storage for control data, durable streaming for ingest, object storage for payloads, and a managed columnar/search system for analytics. Terraform defines infrastructure; GitOps or an equivalent audited pipeline promotes immutable images.

## Production topology

- Global DNS and CDN for UI
- Regional TLS ingest with autoscaling and quotas
- Durable event log separating acceptance from projection
- Stateless processors and query services across availability zones
- Tenant-aware relational, analytics, object, and cache layers
- Central metrics/logs/traces in a separate operations account

## SLO targets for cloud GA

| Service indicator | Target |
|---|---:|
| Ingest availability | 99.9% monthly |
| Accepted-event durability | 99.9999% |
| Ingest p95 response | <300 ms in-region |
| Trace query availability | 99.9% |
| Trace query p95, recent trace | <2 s |
| RPO / RTO | ≤5 min / ≤60 min |

## Delivery and rollback

CI builds once, signs artifacts, generates an SBOM, and promotes the same digest. Database changes use expand/migrate/contract. Deploy canaries by tenant-independent traffic, compare error/latency/loss indicators, then expand. Rollback reverts application images; migrations remain backward-compatible.

## Capacity and cost

Model cost per million events using average envelope bytes, compression ratio, retention days, projection amplification, query rate, and egress. Set per-project quotas and sampling before onboarding unbounded workloads. Review gross margin by plan monthly.

## Disaster recovery

Automate backups, cross-region object replication where contracted, infrastructure recreation, and quarterly restore drills. A backup is not considered valid until restored and queried. Publish customer-facing recovery commitments only after demonstrated tests.

For the public single-node collector, stop traffic for file replacement, restore a verified SQLite backup, run `/ready`, compare project-scoped counts, and complete a synthetic ingest/query/delete probe before reopening traffic. Durable producer outboxes safely redeliver work not acknowledged before the outage.

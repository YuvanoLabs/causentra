# Production deployment runbook

This runbook covers the supported Causentra Python collector: a single-node,
project-isolated service backed by SQLite on durable local block storage. It is
not a multi-region high-availability design or an organization-RBAC control
plane.

## Deployment acceptance

Before admitting production traffic, a named team must own the host, encrypted
volume, TLS certificate lifecycle, secret store, backup target, monitoring, and
rollback. Use one project key per workload and a different operator key for
`/metrics`. Keep raw keys only in the approved secret store; configuration holds
only SHA-256 digests.

Install a named release and create one digest per raw key without echoing it:

```bash
python -m venv /opt/causentra/venv
/opt/causentra/venv/bin/python -m pip install --upgrade pip
/opt/causentra/venv/bin/python -m pip install --pre causentra
/opt/causentra/venv/bin/causentra-key-hash
```

Select only the framework extras in use. The aggregate `frameworks` extra is a
compatibility-lab dependency set, not a production dependency policy.

## Collector configuration

Save strict JSON as `/etc/causentra/collector.json`; replace placeholders before
starting the service. Relative database and TLS paths resolve from this file, so
absolute paths make recovery unambiguous.

```json
{
  "database": "/var/lib/causentra/collector.db",
  "listen": {"host": "0.0.0.0", "port": 4318, "allowInsecureRemote": false},
  "apiKeys": [
    {
      "id": "payments-producer-2026-08",
      "projectId": "payments-production",
      "sha256": "<digest from causentra-key-hash>",
      "role": "project"
    },
    {
      "id": "operations-metrics-2026-08",
      "projectId": "operations",
      "sha256": "<different digest from causentra-key-hash>",
      "role": "operator"
    }
  ],
  "limits": {
    "maxBodyBytes": 2097152,
    "maxBatchEvents": 1000,
    "requestsPerMinute": 600,
    "authAttemptsPerMinute": 600,
    "eventsPerMinute": 100000,
    "maxStoreEvents": 10000000,
    "maxStoreBytes": 21474836480,
    "maxProjectEvents": 2000000,
    "maxProjectBytes": 4294967296,
    "maxConcurrentRequests": 128,
    "requestTimeoutSeconds": 15
  },
  "tls": {
    "certificate": "/etc/causentra/tls/fullchain.pem",
    "privateKey": "/etc/causentra/tls/privkey.pem"
  }
}
```

The collector rejects a non-loopback bind without TLS unless an unsafe override
is explicitly enabled. That override is development-only. `413` means body or
batch capacity was exceeded; `429` means a rate limit was exceeded. Neither is a
successful delivery.

## Service lifecycle

Run an unprivileged service account under a supervisor. This systemd baseline
must be tested against the host's certificate and database permissions.

```ini
[Unit]
Description=Causentra authenticated collector
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=causentra
Group=causentra
WorkingDirectory=/var/lib/causentra
ExecStart=/opt/causentra/venv/bin/causentra-collector --config /etc/causentra/collector.json
Restart=on-failure
RestartSec=5
TimeoutStopSec=25
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

Use platform-native secret management, firewall controls, TLS renewal, and
volume encryption. On `SIGTERM`, the collector drains active requests,
checkpoints SQLite WAL, and closes the store. Give the supervisor more than
`requestTimeoutSeconds + 5` to complete this sequence.

## Pre-production exercises

```bash
causentra --url https://collector.internal.example:4318 \
  --key-file /run/secrets/causentra-project-key doctor
```

`doctor` must report healthy, ready, and authenticated. Then use the real
producer settings to send a synthetic trace and validate each condition:

| Exercise | Pass condition |
|---|---|
| Restart during delivery | The producer outbox redelivers and duplicates are safe. |
| Stop a producer during delivery | `flush()` reports pending work; restart drains the outbox. |
| Exhaust a limit | The collector returns `413` or `429`, alerting sees it, and the service stays healthy. |
| Cross-project request | A key cannot list, read, or delete another project's data. |
| Invalid key | Authorization fails generically and no key is logged. |

Alert on request failures, rate limits, accepted and duplicate events, storage
usage, outbox/dead-letter counts, process restarts, certificate expiry, and disk
free space. A false `flush()`, worker death, or growing dead letters requires an
incident record and explicit duplicate-safe recovery.

## Backup, retention, and rollback

Use the online-consistent backup command; do not copy SQLite files while the
collector is active.

```bash
causentra backup --config /etc/causentra/collector.json \
  --output /var/backups/causentra/collector-$(date +%F).db
causentra prune-idempotency --config /etc/causentra/collector.json \
  --older-than-days 30
```

Test restores on an isolated stopped collector. Verify readiness, project-scoped
trace counts, and a synthetic ingest/query/delete cycle before reopening
traffic. Idempotency tombstones outlive trace deletion so delayed retries cannot
resurrect deleted data; prune only after the documented retry window.

Promote only a recorded package version, artifact digest, dependency lock/SBOM,
configuration revision, validation timestamp, and rollback owner. Keep the prior
environment and a verified backup through the rollback window. Do not purge an
outbox or dead letters merely to make a dashboard appear healthy.

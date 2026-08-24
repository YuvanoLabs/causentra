# Production deployment runbook

This runbook is for the supported Causentra Python collector: a single-node,
project-isolated service backed by SQLite on durable local block storage. It is
not a high-availability or organization-RBAC design. Do not describe this
deployment as multi-region, managed SaaS, or a substitute for an OS/container
security boundary.

## Production acceptance boundary

The deployment owner accepts this runbook only after all of the following are
true:

- a named team owns the host, volume, certificate lifecycle, secret store,
  backup target, and monitoring destination;
- every workload has a unique project key and `/metrics` has a separate
  operator key;
- remote traffic is TLS-protected and is not directly exposed to the public
  internet without an approved network boundary;
- the producer outbox and collector database have an explicit retention policy
  and free-space alerts; and
- a restore drill and temporary collector-outage drill passed using synthetic
  data.

These are deployment gates, not a claim that the published `0.1.0a1` alpha has
completed independent assurance. The remaining product-release gates are in
[verification evidence](26-verification-evidence.md) and the [readiness
review](21-public-product-readiness-review.md).

## Prepare identities and storage

Install a named release into an isolated environment. Select only the extras
that the workload needs; the aggregate `frameworks` extra is for compatibility
testing, not a production dependency policy.

```bash
python -m venv /opt/causentra/venv
/opt/causentra/venv/bin/python -m pip install --upgrade pip
/opt/causentra/venv/bin/python -m pip install --pre causentra
```

Create the database directory on an encrypted, durable local volume. The
service account needs read/write access to the database and read-only access to
configuration and certificates. Keep raw bearer keys only in the approved secret
store; the collector configuration stores only their lowercase SHA-256 digests.

Use the no-echo helper once for each high-entropy key:

```bash
/opt/causentra/venv/bin/causentra-key-hash
```

Record the digest in configuration, deliver the raw key only to its producer or
operator secret, and rotate by adding a new principal, moving clients, then
removing the old principal. Never put a raw key in configuration, a unit file,
the repository, an image, or a log.

## Configure the collector

Save this strict JSON document as `/etc/causentra/collector.json`. Relative
database and TLS paths are resolved from the configuration file, so absolute
paths make recovery unambiguous. Replace every placeholder before startup.

```json
{
  "database": "/var/lib/causentra/collector.db",
  "listen": {"host": "0.0.0.0", "port": 4318, "allowInsecureRemote": false},
  "apiKeys": [
    {
      "id": "payments-producer-2026-08",
      "projectId": "payments-production",
      "sha256": "<sha256 from causentra-key-hash>",
      "role": "project"
    },
    {
      "id": "operations-metrics-2026-08",
      "projectId": "operations",
      "sha256": "<different sha256 from causentra-key-hash>",
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

The collector refuses a non-loopback bind without a certificate and private key
unless `allowInsecureRemote` is explicitly set to `true`. That override is only
for an isolated development network. Set both TLS fields or neither; TLS 1.2 is
the minimum when the collector terminates TLS itself.

The limits are starting values, not universal sizing advice. Establish capacity
from workload measurements. A `413` means a body or batch limit was exceeded;
`429` means a rate limit was exceeded. Neither is a successful delivery.

## Run with a supervised lifecycle

For a Linux host using systemd, run a dedicated unprivileged account. Adapt the
paths to the deployment standard.

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

Use platform-native secret management, certificate rotation, a firewall, and
volume encryption. Validate stricter service hardening against required
certificate and database paths before enforcing it. On `SIGTERM`, the collector
stops accepting work, drains active requests, checkpoints SQLite WAL, then closes
the store. Give the supervisor more time than `requestTimeoutSeconds + 5`.

## Validate before admitting production traffic

From a trusted host with the project raw key in an approved secret file:

```bash
causentra --url https://collector.internal.example:4318 \
  --key-file /run/secrets/causentra-project-key doctor
```

`doctor` must report healthy, ready, and authenticated. Send one synthetic trace
through the same durable exporter settings the application will use, then verify
that the project key can list and read only its own trace. An operator key is
required for `/metrics`; a project key must receive `403`.

| Exercise | Pass condition |
|---|---|
| Restart collector during delivery | The producer outbox redelivers; no committed event is lost and duplicates are safe. |
| Stop producer during delivery | `flush()` reports pending work; a restart drains the SQLite outbox. |
| Exhaust a limit | The collector returns `413` or `429`, alerting reports the rejection, and the service remains healthy. |
| Cross-project query | A key cannot list, read, or delete another project’s data. |
| Invalid key | The collector returns a generic authorization failure and no key is logged. |

Monitor request failures, rate limits, accepted and duplicate events, storage
usage, outbox/dead-letter counts, process restarts, TLS expiry, and disk free
space. Alert if a producer `flush()` returns false, a worker dies, dead letters
grow, or capacity crosses the agreed warning threshold.

## Back up, restore, and retain deliberately

Create an online-consistent backup with the CLI; do not copy SQLite files while
the collector is active.

```bash
causentra backup \
  --config /etc/causentra/collector.json \
  --output /var/backups/causentra/collector-$(date +%F).db
```

Test the backup on a stopped, isolated collector before relying on it. Verify
readiness, a project-scoped trace count, and a synthetic ingest/query/delete
cycle. Restore only while the collector is stopped; preserve ownership and
permissions, then repeat the same validation before reopening traffic.

Trace deletion does not remove idempotency tombstones: a delayed retry must not
resurrect deleted data. Prune only under a retention policy that exceeds the
maximum expected retry window:

```bash
causentra prune-idempotency \
  --config /etc/causentra/collector.json \
  --older-than-days 30
```

## Release handoff and rollback

Promote a deployment only with a recorded package version, artifact digest,
resolved dependency lock/SBOM, configuration revision, validation timestamp, and
rollback owner. Upgrade one node or isolated environment first; exercise ingest,
query, deletion, graceful shutdown, and restore before broad rollout.

Keep the prior environment and a verified database backup through the rollback
window. If rollback is required, stop the collector, restore the prior
application environment and database only when needed, then validate readiness
and a synthetic trace before reopening traffic. Do not silently purge an outbox
or dead letters to make a dashboard look healthy—record the incident and use
explicit duplicate-safe recovery.

For runtime semantics, transport guarantees, and plugin boundaries, see
[production runtime](24-production-python-runtime.md) and [transport and plugin
operations](25-transport-plugin-operations.md).

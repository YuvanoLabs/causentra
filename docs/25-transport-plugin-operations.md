# Transport and plugin operations

## Durable transport setup

```python
from pathlib import Path

from causentra import DurableTransportExporter, HttpTransport, SqliteEventSpool

exporter = DurableTransportExporter(
    SqliteEventSpool(Path(".causentra/producer-spool.db")),
    HttpTransport(
        "https://collector.example/v1/events",
        headers={"Authorization": "Bearer <high-entropy-key>"},
    ),
    batch_size=100,
    delivery_timeout=10,
    lease_seconds=30,
)
```

Install only the transport in use: `causentra[kafka]`, `[nats]`, `[redis]`, `[mqtt]`, `[websocket]`, or `[transports]`.

| Transport | Required receiver behavior | Secure remote default |
|---|---|---|
| HTTP | return any 2xx after durable acceptance; deduplicate `Idempotency-Key` | HTTPS |
| WebSocket | return `{"batchId":"…","accepted":true}` | WSS |
| Kafka | consume JSON value; deduplicate envelope `batchId` | broker TLS configured through producer options |
| NATS JetStream | persist before publish ack; JetStream deduplicates `Nats-Msg-Id` | `tls://` or TLS connection option |
| Redis Streams | consume `payload`; deduplicate `batch_id` | `rediss://` |
| MQTT | consume JSON payload; deduplicate envelope `batchId` | TLS; QoS 1/2 |

Monitor `exporter.stats`, `worker_running`, `dead_lettered_events`, `rejected_events`, error callbacks and disk free space. Review before calling `requeue_dead_letters`; purge only after an incident record or confirmed duplicate-safe recovery.

Remote Kafka requires `security.protocol=SSL` or `SASL_SSL` by default. Remote HTTP/WebSocket/Redis/NATS/MQTT similarly fail closed without their secure transport. Unsafe overrides exist only for controlled development networks.

## Event engine

```python
from causentra import EventEngine, RetryPolicy

engine = EventEngine(".causentra/events.db", worker_count=4)
engine.subscribe(
    "alerts",
    alert_handler,
    event_types=("agent.*", "model.*", "tool.*"),
    services=("checkout",),
    retry=RetryPolicy(max_attempts=8),
)
```

Subscription names are durable identities. Reuse the same name after restart. Handlers must be idempotent because crashes can repeat delivery. Multiple workers do not guarantee handler completion order. Use one worker when strict serial handling is required.

Replay is explicit:

```python
engine.replay_completed(trace_id=trace_id, subscription="alerts")
engine.requeue_dead_letters(subscription="alerts")
```

## Plugin manifest

```json
{
  "apiVersion": "causentra.io/plugin/v1",
  "id": "example.alerts",
  "version": "1.0.0",
  "entrypoint": ["plugin-executable"],
  "subscriptions": {"eventTypes": ["agent.*", "tool.*"], "services": []},
  "permissions": [],
  "environment": [],
  "integrity": {"plugin-executable": "<sha256>"}
}
```

The executable reads one JSON object per line and answers initialization with `{"type":"ready","protocolVersion":"1.0"}`. For each event it returns the exact `deliveryId`, boolean `accepted`, and optional boolean `retryable`. Stdout is protocol-only.

Production policy must explicitly list the trusted plugin ID. External Python/Node interpreters must also be executable-allowlisted. Environment values require the `secrets` permission; event attributes require `event.attributes`. Network authority is declared and approved, but enforcement requires the deployment's OS/container sandbox.

## Backup and restore

Create a consistent collector backup through `SqliteCollectorStore.backup(path)` or stop the collector before copying its database. Validate backup readiness by opening it and running `ready()`. Restore only while the collector is stopped, preserve filesystem ownership/permissions, then verify `/ready`, project-scoped trace counts, and a synthetic ingest/query/delete cycle before reopening traffic.

# @causentra/server

The open-source local collector, trace store, query API, and dashboard for Causentra.

```bash
causentra serve
```

The server binds to `127.0.0.1:4318` and stores events in `.causentra/events.ndjson` by default. It refuses non-loopback binding unless `allowUnsafeNetwork` is explicitly acknowledged. That acknowledgement does not add authentication; do not expose the server to an untrusted network.

The dashboard renders causal operations and highlights failures and slow paths. The API and CLI support versioned trace export/import, per-trace deletion, and explicit keep-latest pruning. No automatic local trace limit is imposed.

The dashboard renders handoff/delegation source-to-target relationships and supports safe metadata search plus framework, provider, model, status, session, and tool filters. The corresponding `/api/traces` query parameters are bounded and never index payload bodies or arbitrary attributes.

The collector accepts the native event API at `POST /v1/events` and standards-based OTLP/HTTP traces at `POST /v1/traces`. OTLP JSON and protobuf are supported with optional gzip. Content-bearing GenAI, OpenInference, LangSmith, error, and tool attributes are omitted during conversion; provider, model, usage, timing, status, service, scope, and causal identifiers are retained.

Configuration and environment precedence are documented in the repository README. The HTTP contract is published in `docs/openapi.yaml`.

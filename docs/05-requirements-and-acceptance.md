# Requirements and acceptance specification

## Non-functional requirements

| ID | Requirement | M0 verification |
|---|---|---|
| NFR-01 | Local server binds to loopback by default | Integration test/config review |
| NFR-02 | Request bodies are limited to 1 MiB | Oversized request returns 413 |
| NFR-03 | Invalid events never enter storage | Validation test |
| NFR-04 | Storage survives graceful restart | Restart integration test |
| NFR-05 | SDK queue is bounded | Unit test and dropped-event callback |
| NFR-06 | Export does not block application success | Failure-path unit test |
| NFR-07 | Events from independent producers are returned deterministically | Timestamp + lifecycle + producer sequence + event-ID ordering test |
| NFR-08 | Dependencies have no known critical advisories | CI audit gate before release |
| NFR-09 | Public APIs are typed and documented | Strict mypy plus Python `py.typed`; TypeScript declaration build |
| NFR-10 | Supported Node versions are enforced | CI version matrix at beta |
| NFR-11 | Non-loopback binding fails closed without explicit unsafe acknowledgement | Server integration test |
| NFR-12 | Portable bundles are versioned and validated before import | Export/delete/import round-trip test |
| NFR-13 | Trace filters are bounded, deterministic, and reject malformed session/status values | API integration test |

## M0 acceptance scenarios

### A1: successful workflow

Given a running local server, when the demo emits a successful trace with model and tool spans, then the API and dashboard show one successful trace, nested spans, ordered events, and a non-negative duration.

### A2: failed operation

When a wrapped operation throws, then its span and trace end with error status and sanitized error type, the message is excluded unless explicitly enabled, and the original error is rethrown to the application.

### A3: unavailable collector

When the server is unavailable, then the application operation still completes, exporter retries are bounded, `flush()` reports failure, and queue growth remains bounded.

### A4: invalid input

When an event has an unsupported schema version, malformed identifier, invalid timestamp, or oversized attributes, then ingestion returns a 400 response with a machine-readable error and persists nothing.

### A5: restart recovery

Given accepted events on disk, when the service restarts, then the same trace can be queried without duplicates.

### A6: privacy

Given a redaction callback, when attributes contain configured secret fields, then stored and displayed events contain the replacement value and never the original.

### A7: trace portability and control

Given a stored trace, when it is exported, deleted, and re-imported, then the same validated events are restored without duplicate event IDs. Explicit pruning keeps only the requested newest trace count.

### A8: standards interoperability

Given a valid W3C carrier, when a receiving runtime starts work, then it preserves the trace identifier and causal parent. Given the OpenTelemetry bridge, an in-process provider receives causal spans and a local OTLP receiver receives protobuf trace bytes.

### A9: mixed-framework continuity

Given one active Causentra trace, when real OpenAI Agents and compiled LangGraph work receive its parent context, then both framework roots preserve the canonical trace ID and attach to the expected parent chain.

### A10: provider-neutral OTLP ingress

Given OTLP/HTTP JSON, protobuf, or gzip-compressed trace data, when the collector accepts it, then safe provider/model/usage facts and causal IDs are retained, known content-bearing fields are omitted, and invalid spans use OTLP partial success.

### A11: adapter conformance

Given a completed maintained-adapter fixture, the public verifier confirms schema validity, unique IDs, exact lifecycle pairing, framework identity, declared private-content exclusion, and optional parent continuity.

### A12: multi-agent discovery

Given traces from different frameworks, providers, models, sessions, agents, and tools, when safe metadata search and combined filters are applied, then only matching summaries are returned with deterministic facets. Prompt, output and error content is never indexed. Handoffs and delegations show source, target, kind, duration, framework, and status without reading framework-specific payloads.

### A14: provider-depth contract

Given representative SDK response and streaming-terminal shapes for OpenAI, Anthropic, Gemini, Bedrock, Azure OpenAI, Cohere, Mistral and Groq, when the Python provider observer processes them, then canonical model/usage/cache/finish and available request/timing facts are emitted without content fields. Given the remaining seven canonical provider profiles, their compatible response families preserve provider identity and available usage facts.

### A13: adapter scaffold

Given an unchanged copy of the public template, when the root test suite runs, then the adapter compiles, maps paired lifecycles, joins a canonical parent, ignores undeclared private payloads, contains malformed telemetry, and passes the public conformance verifier.

## Release gates

- Build, unit, and integration tests pass from a clean checkout.
- Quick-start journey is manually verified.
- No secrets or captured prompts exist in fixtures.
- API/schema changes are documented.
- Local exposure warning is visible; non-loopback binding requires explicit configuration.
- Known limitations and rollback instructions are current.

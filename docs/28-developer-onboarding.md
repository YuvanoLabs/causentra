# Developer onboarding

This path produces an authenticated, queryable multi-agent trace without an external account, model credential, or hosted service.

## Prerequisites

- Python 3.10–3.13
- A working Python environment for the application being instrumented
- No broker or Node.js process is required for this path

## Five-minute Python path

Install the published package from [PyPI](https://pypi.org/project/causentra/):

```bash
python -m pip install --pre causentra
```

The following walkthrough works in any project directory. A repository checkout is only needed to run the supplied `examples/python/authenticated_quickstart.py` example.

Create a loopback collector configuration and a separate high-entropy key file. Existing files are never overwritten.

```bash
causentra init --config .causentra/collector.json --key-output .causentra/collector.key
```

Start the authenticated collector in terminal one:

```bash
causentra-collector --config .causentra/collector.json
```

In terminal two, verify readiness and run the executable example:

```bash
causentra --key-file .causentra/collector.key doctor
# Requires a repository checkout; otherwise, instrument your own application below.
python examples/python/authenticated_quickstart.py
causentra --key-file .causentra/collector.key traces
```

Expected example output:

```text
Causentra quickstart trace delivered.
```

The example records lifecycle facts for a trace, two agents, a model call, a handoff, and a tool operation. It does not send a prompt, model response, tool argument, tool result, or raw exception message.

## Integrate your code

Use one runtime per service and shut it down when the process stops:

```python
from pathlib import Path

from causentra import (
    CausentraRuntime,
    DurableTransportExporter,
    HttpTransport,
    SqliteEventSpool,
)

project_key = Path(".causentra/collector.key").read_text(encoding="utf-8").strip()
exporter = DurableTransportExporter(
    SqliteEventSpool(".causentra/producer-spool.db"),
    HttpTransport(
        "http://127.0.0.1:4318/v1/events",
        headers={"Authorization": f"Bearer {project_key}"},
    ),
)
runtime = CausentraRuntime("support-service", exporter)

try:
    with runtime.trace("resolve-ticket"):
        with runtime.agent("triage"):
            with runtime.model(
                "classify",
                provider_name="anthropic",
                request_model="deployment-name",
            ):
                response = call_model()
        with runtime.handoff("triage", "billing"):
            with runtime.tool("lookup-account"):
                account = lookup_account()
    if not runtime.flush(5.0):
        raise RuntimeError("Causentra delivery did not complete")
finally:
    runtime.shutdown(5.0)
```

Do not hard-code a production key. Load it from the deployment secret store and construct the `Authorization` header at process startup.

The durable exporter commits events to SQLite before transmission. A process or collector interruption can therefore redeliver events without losing a successful local commit. Handlers and receivers must remain idempotent. See [transport and plugin operations](25-transport-plugin-operations.md).

## Add a framework adapter

Install only the framework integration in use:

```bash
python -m pip install --pre "causentra[openai-agents]"
python -m pip install --pre "causentra[langgraph]"
python -m pip install --pre "causentra[crewai]"
python -m pip install --pre "causentra[google-adk]"
python -m pip install --pre "causentra[semantic-kernel]"
python -m pip install --pre "causentra[autogen]"
```

| Framework | Registration surface | Complete example |
|---|---|---|
| OpenAI Agents | tracing processor | [integration recipe](17-integration-guide.md#openai-agents-python) |
| LangGraph | callback handler | [integration recipe](17-integration-guide.md#langgraph-python) |
| CrewAI | event-bus listener | [integration recipe](17-integration-guide.md#crewai-python) |
| Google ADK | application plugin | [integration recipe](17-integration-guide.md#google-adk-python) |
| Semantic Kernel | invocation filters | [integration recipe](17-integration-guide.md#semantic-kernel-python) |
| AutoGen | OpenTelemetry provider | [integration recipe](17-integration-guide.md#autogen-python) |

Adapters capture allowlisted lifecycle and operational metadata. Application prompts, messages, framework state, model responses, and tool values remain outside the event contract.

## Verify the integration

An integration is complete when all of the following hold:

1. `doctor` reports healthy, ready, and authenticated.
2. One trace contains ordered start/end lifecycle pairs.
3. Agent, model, tool, and handoff events share the same trace ID.
4. Provider and requested model identifiers are normalized where available.
5. No prompt, response, tool value, credential, or raw error message appears in the event JSON.
6. `flush` and `shutdown` complete during graceful process termination.
7. The producer survives a temporary collector outage when durable delivery is enabled.

Use `causentra --key-file .causentra/collector.key trace <trace-id>` to inspect the exact stored event document.

## Common failures

| Symptom | Resolution |
|---|---|
| `401 Unauthorized` | Use the raw key file generated with the same collector configuration |
| `409 Conflict` | Do not reuse an event or batch ID with different content |
| `413 Payload Too Large` | Reduce batch size or review the configured body limit |
| Collector refuses a remote bind | Configure TLS or explicitly acknowledge a trusted development network |
| Trace is missing after process exit | Call `flush`, then `shutdown`; use durable delivery for production |
| Framework events are absent | Install the matching optional extra and register the adapter before execution |

## Next paths

- [Provider support contract](23-provider-support.md)
- [Authenticated collector OpenAPI](openapi-collector.yaml)
- [Schema compatibility](18-schema-compatibility.md)
- [Production Python runtime](24-production-python-runtime.md)
- [Adapter template](../templates/community-adapter/README.md)
- [Verification evidence](26-verification-evidence.md)

The TypeScript SDK implements the same event contract and remains a maintained protocol peer. Python is the primary onboarding and runtime path.

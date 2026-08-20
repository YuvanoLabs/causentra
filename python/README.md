# Causentra for Python

Python-first instrumentation, durable event delivery, processing, and authenticated collection for multi-agent applications. Every component uses the portable `RuntimeEvent` 1.0 contract.

## Install

Causentra is published on [PyPI](https://pypi.org/project/causentra/) for Python 3.10 and later. The current `0.1.0a1` alpha is installed explicitly with `--pre`:

```bash
python -m pip install --pre causentra
```

Add only the framework extras your application uses:

```bash
python -m pip install --pre "causentra[openai-agents,langgraph]"
```

For contributor development from this repository, use the editable source installation instead:

```bash
python -m pip install -e ".[dev,openai-agents,langgraph]"
```

```python
from causentra import CausentraRuntime, HttpBatchExporter

runtime = CausentraRuntime(
    service_name="support-agents",
    exporter=HttpBatchExporter(),
)

with runtime.trace("resolve-ticket"):
    with runtime.agent("triage"):
        with runtime.model("classify", provider_name="anthropic", request_model="model-id"):
            call_model()
    with runtime.handoff("triage", "billing"):
        with runtime.tool("lookup-account"):
            lookup_account()

runtime.shutdown()
```

Maintained native adapters cover OpenAI Agents, LangGraph/LangChain, CrewAI, Google ADK, Semantic Kernel, and AutoGen. Install only the framework extras used by the application.

The aggregate `frameworks` extra exists for compatibility labs. It installs a large upstream dependency graph and is not the recommended production installation. Production environments should select named extras, lock the resolved graph, generate an SBOM, and review the current advisory evidence.

OpenAI Agents example:

```python
from agents import add_trace_processor
from causentra.adapters.openai_agents import create_openai_agents_processor

add_trace_processor(create_openai_agents_processor("support-agents", exporter))
```

LangGraph uses `LangGraphCallbackHandler` through `config={"callbacks": [handler]}`. The other native registration recipes are in the [integration guide](../docs/17-integration-guide.md). The `otel` extra provides `OpenTelemetryEventExporter` and `start_otlp_exporter` for standards-based pipelines.

Provider-aware call instrumentation supports eight deep integrations and all 15 canonical provider profiles:

```python
response = runtime.call_model(
    "generate",
    lambda: client.chat.completions.create(...),
    provider_name="groq",
    request_model="model-id",
)
```

See the [provider support contract](../docs/23-provider-support.md) for exact extraction and compatibility guarantees.

Durable delivery and processing:

```python
from causentra import DurableTransportExporter, EventEngine, HttpTransport, SqliteEventSpool

exporter = DurableTransportExporter(
    SqliteEventSpool(".causentra/outbox.db"),
    HttpTransport(
        "https://collector.example/v1/events",
        headers={"Authorization": "Bearer <key>"},
    ),
)
engine = EventEngine(".causentra/events.db")
engine.subscribe("audit", audit_handler, event_types=("agent.*", "tool.*"))
```

The authenticated collector provides project-isolated atomic ingestion, trace query/delete, health/readiness, quotas, and operator metrics:

```bash
causentra init --config collector.json --key-output collector.key
causentra-collector --config collector.json
causentra --key-file collector.key doctor
causentra --key-file collector.key traces
```

The CLI keeps the raw generated key in a separate file, refuses to overwrite files, requires explicit trace-ID confirmation for deletion, and also provides consistent backup and idempotency-tombstone retention commands.

See [production runtime](../docs/24-production-python-runtime.md) and [transport/plugin operations](../docs/25-transport-plugin-operations.md).

Prompts, outputs, tool arguments, arbitrary framework state, and error messages are not captured by default. Instrumentation failure never replaces application behavior.

Causentra `0.1.0a1` is a published PyPI alpha. Strict typing/lint, deterministic tests, exact-framework registration, clean-wheel, collector, durable transport, and package verification gates are implemented. Independent security review and target-infrastructure load/soak evidence remain production-release gates.

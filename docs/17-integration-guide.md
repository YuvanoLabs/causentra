# Integration guide

## Install and start locally

```bash
npm install
npm run build
npm run dev
```

Open `http://127.0.0.1:4318`. The collector is loopback-only and requires no account or network service.

This Node.js inspection server is intentionally unauthenticated. It refuses a non-loopback bind unless `server.allowUnsafeNetwork` or `CAUSENTRA_ALLOW_UNSAFE_NETWORK=true` explicitly acknowledges the risk. Use the authenticated Python collector below for a remote self-hosted data plane.

## Python SDK

```bash
python -m pip install -e "python[openai-agents,langgraph]"
```

Choose only the named framework extras used by the application: `openai-agents`, `langgraph`, `crewai`, `google-adk`, `semantic-kernel`, or `autogen`. The aggregate `frameworks` extra is for compatibility validation; production deployments should use a reviewed lock/constraints file and current advisory report.

```python
from causentra import CausentraRuntime, HttpBatchExporter

runtime = CausentraRuntime("support-agent", HttpBatchExporter())
with runtime.trace("answer-question"):
    with runtime.agent("triage"):
        with runtime.model("draft-answer", provider_name="azure-openai", request_model="deployment-name"):
            call_model()
    with runtime.handoff("triage", "billing"):
        with runtime.tool("lookup-account"):
            lookup_account()
runtime.shutdown(5.0)
```

The same context managers work with `async with`; `contextvars` preserves correlation across coroutine tasks.

### OpenAI Agents Python

```python
from agents import add_trace_processor
from causentra import HttpBatchExporter
from causentra.adapters.openai_agents import create_openai_agents_processor

processor = create_openai_agents_processor("support-agent", HttpBatchExporter())
add_trace_processor(processor)
```

Supported contract: `openai-agents >=0.18,<0.19`. The official tracing processor allowlists lifecycle, identity, timing, usage, model, guardrail, and handoff facts. It never serializes prompts, inputs, outputs, or trace metadata.

### LangGraph Python

```python
from causentra import HttpBatchExporter
from causentra.adapters.langgraph import LangGraphCallbackHandler

handler = LangGraphCallbackHandler("research-graph", HttpBatchExporter())
result = graph.invoke(input_state, config={"callbacks": [handler]})
handler.shutdown()
```

Supported contracts: `langchain-core >=1.4,<1.5` and `langgraph >=1.2,<1.3`. Inputs, messages, state, outputs, and metadata values are excluded; opt-in metadata capture records keys only.

### CrewAI Python

```python
from causentra.adapters.crewai import create_crewai_listener

listener = create_crewai_listener("research-crew", exporter)
# Construct and run CrewAI normally; the official event bus is global.
listener.shutdown()
```

Supported contract: `crewai >=1.15.3,<1.16`. The listener registers crew, agent, task, tool, and model lifecycle events. Descriptions, prompts, tool arguments/results, and model content are excluded.

Production gate: CrewAI `1.15.3` currently constrains optional transitive dependencies with unresolved advisories. The adapter is compatibility-tested, but this extra is not production-approved until a compatible upstream graph passes the advisory gate. See [verification evidence](26-verification-evidence.md).

### Google ADK Python

```python
from google.adk.apps import App
from causentra.adapters.google_adk import create_google_adk_plugin

plugin = create_google_adk_plugin("support-adk", exporter)
app = App(name="support", root_agent=root_agent, plugins=[plugin])
```

Supported contract: `google-adk >=2.4,<2.5`. Register the plugin on `App`, not the deprecated runner plugin path. It maps invocation, agent, model, tool, and trace lifecycle while excluding request/response content and tool values.

### Semantic Kernel Python

```python
from causentra.adapters.semantic_kernel import install_semantic_kernel_filters

adapter = install_semantic_kernel_filters(kernel, "support-kernel", exporter)
# Use kernel normally.
adapter.shutdown()
```

Supported contract: `semantic-kernel >=1.44,<1.45`. The official function-invocation filter captures plugin/function identity, status, and timing, not arguments or results.

Production gate: the current Semantic Kernel graph resolves through `openapi-core` to a Werkzeug version below available security fixes. The adapter is compatibility-tested, but this extra is not production-approved until a compatible graph passes the advisory gate.

### AutoGen Python

```python
from autogen_core import SingleThreadedAgentRuntime
from causentra.adapters.autogen import create_autogen_tracer_provider

provider = create_autogen_tracer_provider("support-autogen", exporter)
agent_runtime = SingleThreadedAgentRuntime(tracer_provider=provider)
# Stop the AutoGen runtime first, then:
provider.shutdown()
```

Supported contracts: `autogen-core/agentchat >=0.7.5,<0.8`. The adapter consumes AutoGen's official OpenTelemetry spans through an allowlisted exporter and excludes message/body attributes.

## Authenticated Python collector

Generate the collector configuration and high-entropy key as separate, non-overwritten files:

```bash
causentra init --config collector.json --key-output collector.key
causentra-collector --config collector.json
causentra --key-file collector.key doctor
```

For externally managed keys, use `causentra-key-hash`, place only the digest in [the example config](../examples/collector.config.example.json), and keep the raw value in the producer secret store.

For a non-loopback listener, configure `tls.certificate` and `tls.privateKey`; plaintext remote binding is refused by default. Each key maps to one project. Only an operator-role key may read `/metrics`.

Use durable HTTP delivery:

```python
from causentra import DurableTransportExporter, HttpTransport, SqliteEventSpool

exporter = DurableTransportExporter(
    SqliteEventSpool(".causentra/producer.db"),
    HttpTransport(
        "https://collector.example/v1/events",
        headers={"Authorization": "Bearer <project-key>"},
    ),
)
```

The collector atomically accepts the versioned batch envelope and deduplicates by project, batch, and event identity. Full API details are in [Python collector OpenAPI](openapi-collector.yaml).

Python operator commands include `traces`, `trace`, confirmation-protected `delete`, consistent `backup`, and explicit `prune-idempotency`. Raw bearer keys are accepted only from `--key-file` or `CAUSENTRA_API_KEY`, never a command-line value.

## Durable transports and event processing

Install one transport extra: `[kafka]`, `[nats]`, `[redis]`, `[mqtt]`, `[websocket]`, or `[transports]`. HTTP requires no optional dependency. Every receiver must durably acknowledge and deduplicate; interruption after remote acceptance may safely redeliver a batch.

```python
from causentra import EventEngine, RetryPolicy

engine = EventEngine(".causentra/events.db", worker_count=4)
engine.subscribe(
    "alerts",
    handle_alert,
    event_types=("agent.*", "model.*", "tool.*"),
    retry=RetryPolicy(max_attempts=8),
)
```

Handlers must be idempotent. Retry exhaustion is retained as a dead letter. `replay_completed` and `requeue_dead_letters` are explicit operator actions. See [transport and plugin operations](25-transport-plugin-operations.md).

## TypeScript SDK

```ts
import { CausentraRuntime, HttpBatchExporter } from "@causentra/sdk";

const runtime = new CausentraRuntime({
  serviceName: "support-agent",
  exporter: new HttpBatchExporter(),
});

await runtime.trace("answer-question", async () => {
  await runtime.agent("triage", async () => {
    await runtime.model("draft-answer", {
      providerName: "azure-openai",
      requestModel: "deployment-name",
      inputTokens: 24,
    }, callModel);
  });
  await runtime.relationship({
    kind: "handoff",
    fromAgent: "triage",
    toAgent: "billing",
  }, () => runtime.tool("lookup-account", lookupAccount));
});

await runtime.shutdown();
```

`serviceName` should be stable across deployments. Call `shutdown()` during graceful termination. Instrumentation failures do not replace application results or exceptions.

## W3C context handoff

Inject a trace carrier before calling another process and extract it at the receiving boundary:

```ts
const headers = runtime.injectTraceContext();

await receivingRuntime.traceFromCarrier(headers, "continued-work", async () => {
  await receivingRuntime.span("remote-tool", "tool", callTool);
});
```

The carrier uses the W3C `traceparent` header. Invalid, unsupported, or all-zero identifiers are rejected instead of creating ambiguous correlation.

## OpenAI Agents SDK

Supported contract: `@openai/agents >=0.13.4 <0.14.0`.

```ts
import { addTraceProcessor } from "@openai/agents";
import { HttpBatchExporter } from "@causentra/sdk";
import { createOpenAIAgentsTraceProcessor } from "@causentra/openai-agents";

addTraceProcessor(createOpenAIAgentsTraceProcessor({
  serviceName: "support-agent",
  exporter: new HttpBatchExporter(),
  parentContext: runtime.currentContext(),
}));
```

The adapter uses the official custom `TracingProcessor` lifecycle. The OpenAI SDK can keep its own exporter; this processor is additive. Configure `traceIncludeSensitiveData: false` when running agents if its exporter is enabled. Causentra independently excludes span inputs, outputs, tool arguments, trace metadata, and error messages by default. See the [official tracing guide](https://openai.github.io/openai-agents-js/guides/tracing/).

Pass `parentContext` only while a Causentra operation is active. The adapter preserves that trace ID and attaches the framework root to its parent span.

## LangGraph and LangChain

Supported contracts: `@langchain/core >=1.2.0 <1.3.0` and `@langchain/langgraph >=1.4.0 <1.5.0`.

```ts
import { HttpBatchExporter } from "@causentra/sdk";
import { createLangGraphInstrumentation } from "@causentra/langgraph";

const instrumentation = createLangGraphInstrumentation({
  serviceName: "research-graph",
  exporter: new HttpBatchExporter(),
  parentContext: runtime.currentContext(),
});

await graph.invoke(input, { callbacks: [instrumentation.handler] });
await instrumentation.shutdown();
```

The adapter follows the official callback surface passed through `RunnableConfig.callbacks`. It records graph, model, tool, and retriever lifecycle but not state, messages, prompts, arguments, outputs, or metadata. See the [official callback reference](https://reference.langchain.com/javascript/langchain-core/runnables/RunnableConfig/callbacks).

## One trace across frameworks

Create one exporter and root `CausentraRuntime` trace. Pass the active context and the same exporter to each adapter. The included deterministic example runs the real OpenAI Agents runner and a compiled LangGraph in one causal trace:

```bash
npm run dev
npm run example:mixed
```

The workspace integration test asserts one trace ID and verifies that both framework roots point to the common parent. A portable `agent.handoff.*` span can wrap the transition.

## OpenTelemetry and OTLP

### Ingest an existing OpenTelemetry producer

Point any OTLP/HTTP exporter at the local collector:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

`POST /v1/traces` accepts OTLP JSON and protobuf, with optional gzip. It preserves causal IDs and safe operational metadata while omitting known prompt, message, retrieval, tool, output and exception content. This path is the provider-neutral integration for OTel-instrumented SDKs and frameworks.

### Export Causentra through OpenTelemetry

Use `@causentra/opentelemetry` when an existing OpenTelemetry provider should receive Causentra spans, or create a dedicated official OTLP/HTTP protobuf provider:

```ts
import { startCausentraRuntimeOtlp } from "@causentra/opentelemetry";

const telemetry = startCausentraRuntimeOtlp({
  serviceName: "support-agent",
  endpoint: "http://127.0.0.1:4318/v1/traces",
});

// Pass telemetry.exporter to CausentraRuntime or an adapter.
await telemetry.shutdown();
```

`endpoint` is required; the package never selects a remote destination implicitly. Content-bearing attributes remain opt-in.

## Provider, model, usage, and cost

`createModelTelemetryAttributes` produces the shared `gen_ai.*` vocabulary plus Causentra cost provenance. Cost requires an explicit basis (`provider_reported`, `catalog_estimate`, or `user_supplied`); the SDK includes no price table and never guesses.

Python additionally provides `runtime.call_model(...)`, `runtime.call_model_async(...)`, and `runtime.provider_model(...)`. These observe eight provider families in depth and map the remaining seven canonical providers through compatible response protocols without taking ownership of SDK clients, credentials, or request content. See the [provider support contract](23-provider-support.md) for the exact tiers and extracted fields.

Both SDKs recognize the current OTel well-known identifiers: Anthropic, AWS Bedrock, Azure AI Inference, Azure OpenAI, Cohere, DeepSeek, Google Gemini/GenAI/Vertex AI, Groq, IBM watsonx.ai, Mistral AI, OpenAI, Perplexity and xAI. Custom provider identifiers are normalized and preserved. TypeScript currently provides vocabulary and explicit instrumentation rather than provider-aware response extraction.

## Adapter conformance

Adapters should run `assertAdapterConformance` over a completed fixture. It verifies valid envelopes, unique IDs, exact lifecycle pairs, framework identity, declared private-content exclusion, and optional shared-parent continuity. Maintained adapters run this contract in CI.

## Trace ownership and retention

```bash
causentra export <trace-id> trace.json
causentra import trace.json
causentra delete <trace-id>
causentra prune 100
```

Exported bundles are versioned and validated on import. Storage remains unlimited by default; deletion and pruning happen only through an explicit user action.

## Filter operational traces

The dashboard exposes the same bounded query dimensions as the local API:

```text
GET /api/traces?q=resolution&framework=langgraph&provider=anthropic&model=claude&status=error&tool=search&session=<32-hex-id>
```

`q` searches only safe trace, service, framework, provider, model, tool and agent names. Framework, provider, model and tool filters are case-insensitive substrings. Status is `running`, `ok`, or `error`; session is an exact canonical identifier. Summary responses include the discovered frameworks, providers, models, tools, agents, sessions and relationship count.

Handoffs and delegations appear in a dedicated relationship view and remain nested in the causal execution tree.

## Build another framework adapter

Copy the [executable adapter template](../templates/community-adapter/README.md). It uses official public SDK boundaries, allowlists operational facts, contains telemetry mapping failures, supports a shared parent, and runs `assertAdapterConformance`. A maintained proposal must additionally include a deterministic test against the real target framework.

## Data controls

- Sensitive-key redaction is recursive and enabled by default.
- Prompt/output capture is never automatic.
- Adapter metadata capture is opt-in and should be reviewed per application.
- Keep the Node.js inspection collector on loopback. Use the authenticated Python collector with TLS for remote self-hosting; its unsafe override is development-only.
- Use a custom redactor to enforce organization-specific field policy before export.

## Troubleshooting

```bash
npm run doctor
npm run start -w @causentra/cli -- traces
```

If the application succeeds but no trace appears, check `flush()`/`shutdown()`, collector reachability, exporter diagnostics, queue bounds, and the `/health` recovery-warning count.

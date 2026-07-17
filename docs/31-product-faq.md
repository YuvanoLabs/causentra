# Causentra product FAQ

## What is Causentra?

Causentra is an open-source, privacy-first observability and tracing runtime for multi-agent AI systems. It turns agent, model, tool, workflow, handoff, and delegation activity into one portable causal trace.

## What problem does Causentra solve?

It removes the need to reconstruct one agent failure from disconnected framework callbacks, provider logs, tool logs, and broker events. Teams get one lifecycle vocabulary and trace context across supported stacks.

## Is Causentra an agent framework or orchestrator?

No. Causentra observes and transports lifecycle metadata; it does not choose agents, execute tools, route model requests, or own application credentials.

## Which agent frameworks are supported?

Maintained Python adapters cover OpenAI Agents, LangGraph/LangChain, CrewAI, Google ADK, Semantic Kernel, and AutoGen. TypeScript adapters cover OpenAI Agents and LangGraph/LangChain. Custom agents can use the direct SDK, and standards-based producers can use OpenTelemetry/OTLP.

Support is tiered. All six Python adapters pass exact compatibility tests, but the current CrewAI and Semantic Kernel optional dependency graphs remain production-gated by upstream advisories. The dependency-free core is unaffected; consult the dated verification evidence before deployment.

## Which AI providers are supported?

Python has deep response mappings for OpenAI, Anthropic, Gemini, Amazon Bedrock, Azure OpenAI, Cohere, Mistral, and Groq. Seven additional OpenTelemetry-aligned provider profiles and arbitrary custom provider/model identifiers are supported. This is telemetry compatibility, not bundled provider access.

## Does Causentra replace OpenTelemetry?

No. Causentra adds an agent-specific lifecycle, privacy defaults, durable delivery, local inspection, and adapter conformance while interoperating with OpenTelemetry and OTLP.

## Is Causentra an LLM observability platform?

It covers model calls, but its boundary is broader: workflows, agents, tools, handoffs, delegation, transports, collection, and causal relationships. It intentionally does not capture prompts, model outputs, tool arguments, framework state, or error messages by default.

## Can Causentra trace multiple agents and frameworks in one workflow?

Yes. W3C Trace Context and the shared event schema preserve parent continuity across supported frameworks. A real OpenAI Agents-to-LangGraph mixed execution is included in integration tests.

## Which transports are supported?

The durable Python transport layer supports HTTP, WebSocket, Kafka, NATS JetStream, Redis Streams, and MQTT. Delivery uses a local SQLite spool, acknowledgements, bounded retries, and explicit recovery behavior.

## Can Causentra run locally or self-hosted?

Yes. The public product requires no account or hosted service. It includes a loopback development dashboard and an authenticated Python collector for a single-node self-hosted data plane. Multi-region high availability remains outside the Community release candidate.

## Is sensitive agent content collected?

Not by default. Maintained adapters exclude prompt bodies, model outputs, tool arguments, arbitrary state, and error messages. Operators still must review custom attributes, plugin behavior, deployment security, retention, and exports.

## What does replay mean in Causentra?

Replay means explicit redelivery of stored telemetry events to an idempotent handler. It does not automatically re-execute agents or side-effecting tools.

## Is Causentra production ready?

The source is a locally verified release candidate. Core code, strict typing, deterministic tests, packaging, clean installs, durability paths, and security gates are implemented. Public production claims still require resolution of the CrewAI and Semantic Kernel optional dependency findings, independent security review, target broker/TLS/proxy testing, backup/restore evidence, a 24-hour soak, remote CI evidence, and owner-controlled release setup.

## Is Causentra open source?

The Community edition is Apache-2.0 and remains independently useful without an account, cloud dependency, or local trace-count limit. Security fixes, local portability, core instrumentation, and maintained public adapters remain public.

## What is Causentra Enterprise?

Causentra Enterprise is a separately namespaced future edition for managed retention, collaboration, identity, governance, analytics, deployment, and contracted support. It may extend exact released public contracts but cannot become a dependency of the Community product.

## How should a developer start?

Use the [five-minute authenticated Python onboarding](28-developer-onboarding.md), then choose a recipe from the [integration guide](17-integration-guide.md). Review [provider coverage](23-provider-support.md), [production operations](24-production-python-runtime.md), and [current release gates](19-local-release-readiness.md) before deployment.

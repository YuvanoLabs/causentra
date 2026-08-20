# Provider support contract

## Meaning of support

Provider support is split into two enforceable tiers. **Deep** means the Python runtime has provider-aware, privacy-safe mappings backed by response-shape fixtures for model identity, tokens, caching, terminal reason, and available operational IDs/timing. **Compatible** means the provider has a canonical OpenTelemetry identity and a tested mapping through its OpenAI-compatible, Google-compatible, Watsonx, explicit SDK, or OTLP response shape.

Neither tier means Causentra hosts models, owns provider credentials, silently changes SDK clients, or guarantees every future SDK version. Calls remain owned by the application. The runtime observes returned operational fields and never serializes prompts, messages, generated content, tool arguments, or arbitrary response objects.

## Eight deep providers

| Canonical ID | Provider/API family | Allowlisted extraction |
|---|---|---|
| `openai` | Responses and Chat Completions | response/model ID, input/output/cache/reasoning tokens, finish status, SDK request ID |
| `anthropic` | Messages and streaming terminal events | message/model ID, input/output/cache read/cache creation/thinking tokens, stop reason, SDK request ID |
| `gcp.gemini` | Gemini GenerateContent | response/model version, prompt/candidate/cache/thought tokens, candidate finish reason |
| `aws.bedrock` | Bedrock Converse and ConverseStream metadata | input/output/cache read/cache write tokens, stop reason, latency, AWS request ID |
| `azure.ai.openai` | Azure OpenAI Responses/Chat | deployment/model identity, usage details, caching, reasoning and finish reason |
| `cohere` | Chat v2 plus v1 metadata fallback | response ID, actual token usage with billed-unit fallback, finish reason |
| `mistral_ai` | Chat Completions | response/model ID, prompt/completion/cache/reasoning tokens and finish reason |
| `groq` | Chat/Responses compatible APIs | response/model ID, prompt/completion/cache/reasoning tokens, finish reason, queue-inclusive server time and Groq request ID |

The mappings follow the providers' published response contracts: [OpenAI usage](https://platform.openai.com/docs/api-reference), [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create), [Gemini GenerateContent](https://ai.google.dev/api/generate-content), [Bedrock Converse](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html), [Cohere Chat](https://docs.cohere.com/v2/reference/chat), [Mistral Chat](https://docs.mistral.ai/api), [Groq API](https://console.groq.com/docs/api-reference), and [Azure AI model inference](https://learn.microsoft.com/en-us/python/api/overview/azure/ai-inference-readme).

## Full 15-provider vocabulary

| Tier | Canonical identifiers |
|---|---|
| Deep | `openai`, `anthropic`, `gcp.gemini`, `aws.bedrock`, `azure.ai.openai`, `cohere`, `mistral_ai`, `groq` |
| Compatible | `azure.ai.inference`, `deepseek`, `gcp.gen_ai`, `gcp.vertex_ai`, `ibm.watsonx.ai`, `perplexity`, `x_ai` |

Compatible OpenAI-protocol providers extract model/response IDs, prompt or input tokens, completion or output tokens, cache details, reasoning details and finish reason when exposed. Google Gen AI and Vertex share the tested Gemini usage mapping. Watsonx accepts its native `model_id` and token fields. All 15 also work through explicit `runtime.model(...)` instrumentation and OTLP.

## Python integration

Wrap an existing SDK call without handing credentials or request payloads to Causentra:

```python
response = runtime.call_model(
    "draft-answer",
    lambda: client.responses.create(model="model-id", input=user_input),
    provider_name="openai",
    request_model="model-id",
)
```

Async SDKs use `await runtime.call_model_async(...)`. Streaming code uses `runtime.provider_model(...)` and calls `observer.observe_response(chunk)` for terminal/usage chunks. Repeated observations merge only the allowlisted fields.

Cost remains caller-supplied because prices, discounts, regions, cached-token rates and negotiated agreements change independently. `cost_usd` is accepted only with `cost_basis` equal to `provider_reported`, `catalog_estimate`, or `user_supplied`.

## Compatibility policy

- A deep provider cannot be added without fixture tests for normal response, usage, finish reason, privacy exclusion and failure containment.
- Provider SDK packages remain optional; response extraction supports mappings and SDK objects without introducing credential-bearing dependencies.
- Missing fields mean unknown, never zero.
- New aliases cannot replace canonical OpenTelemetry identifiers.
- Breaking provider response changes are handled inside the extractor without changing `RuntimeEvent` 1.0.

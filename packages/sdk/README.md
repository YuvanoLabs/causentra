# @causentra/sdk

```ts
import { CausentraRuntime, HttpBatchExporter } from "@causentra/sdk";

const runtime = new CausentraRuntime({
  serviceName: "my-agent",
  exporter: new HttpBatchExporter(),
});

await runtime.trace("answer-question", async () => {
  await runtime.agent("triage", async () => {
    await runtime.model("answer", {
      providerName: "anthropic",
      requestModel: "model-name",
      inputTokens: 12,
    }, callModel);
  });
  await runtime.relationship({
    kind: "handoff",
    fromAgent: "triage",
    toAgent: "billing",
  }, () => runtime.tool("lookup", lookupAccount));
});

await runtime.shutdown();
```

Prompt bodies, model outputs, and tool arguments are not captured automatically.

The SDK provides typed `agent`, `model`, `tool`, `handoff`/`delegation` operations, strict W3C `traceparent` propagation, provider normalization, and an adapter conformance verifier. It recognizes all current OpenTelemetry well-known GenAI provider identifiers and preserves custom identifiers. Costs require explicit provenance; no provider price table or remote service is built in.

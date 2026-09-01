# @causentra/sdk

Release line: `1.0.0` for Node.js 22+. This verified workspace package is not
yet listed in the public npm registry; see the [package catalog](../../docs/38-package-catalog.md)
for source and archive consumption.

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

The optional `canonicalizeJson` helper uses exact `canonicalize@4.0.0` RFC 8785 implementation to produce UTF-8 JCS bytes for the SDK JSON domain. The opt-in local ECDSA P-256 detached signer/verifier does not alter RuntimeEvent 1.0 or capture keys. The Python runtime supplies matching normalized-batch signing, KMS/Vault digest-signer adapters, and collector verification; see the [assurance controls](../../docs/37-assurance-controls.md).

# @causentra/openai-agents

Adds Causentra as a secondary tracing processor for the OpenAI Agents SDK.

```ts
import { addTraceProcessor } from "@openai/agents";
import { HttpBatchExporter } from "@causentra/sdk";
import { createOpenAIAgentsTraceProcessor } from "@causentra/openai-agents";

const processor = createOpenAIAgentsTraceProcessor({
  serviceName: "support-agent",
  exporter: new HttpBatchExporter(),
  // Optional: runtime.currentContext() joins this run to a shared trace.
  parentContext,
});

addTraceProcessor(processor);
```

Inputs, outputs, tool arguments, error messages, and trace metadata are excluded by default. Also set `traceIncludeSensitiveData: false` in the OpenAI Agents SDK run configuration if its default exporter remains enabled.

Handoffs use the portable `agent.handoff.*` lifecycle and `causentra.agent.*` relationship attributes. The adapter passes the SDK conformance contract for lifecycle pairing, privacy and canonical parent continuity.

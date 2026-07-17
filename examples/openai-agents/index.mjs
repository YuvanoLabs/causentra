import {
  Agent,
  Usage,
  getGlobalTraceProvider,
  run,
} from "@openai/agents";
import { HttpBatchExporter } from "@causentra/sdk";
import { createOpenAIAgentsTraceProcessor } from "@causentra/openai-agents";

const endpoint = process.env.CAUSENTRA_URL ?? "http://127.0.0.1:4318";
const exporter = new HttpBatchExporter({ endpoint: `${endpoint}/v1/events` });
const processor = createOpenAIAgentsTraceProcessor({
  serviceName: "openai-agents-local-example",
  exporter,
});
getGlobalTraceProvider().setProcessors([processor]);

// A deterministic local Model implementation keeps this example free of API keys
// while exercising the real OpenAI Agents runner and tracing processor.
const syntheticModel = {
  async getResponse() {
    return {
      usage: new Usage({ requests: 1, inputTokens: 4, outputTokens: 6, totalTokens: 10 }),
      output: [{
        type: "message",
        role: "assistant",
        status: "completed",
        content: [{ type: "output_text", text: "Synthetic account status: active." }],
      }],
    };
  },
  async *getStreamedResponse() {
    throw new Error("Streaming is not used by this deterministic example");
  },
};

const agent = new Agent({
  name: "Account Support Agent",
  instructions: "Return the deterministic local response.",
  model: syntheticModel,
});

const result = await run(agent, "Check synthetic account status", {
  traceIncludeSensitiveData: false,
});
await processor.shutdown();
console.log(result.finalOutput);
console.log(`Trace delivered to ${endpoint}`);

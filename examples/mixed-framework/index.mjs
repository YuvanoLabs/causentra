import { Agent, Usage, getGlobalTraceProvider, run } from "@openai/agents";
import { Annotation, END, START, StateGraph } from "@langchain/langgraph";
import { CausentraRuntime, HttpBatchExporter } from "@causentra/sdk";
import { createOpenAIAgentsTraceProcessor } from "@causentra/openai-agents";
import { createLangGraphInstrumentation } from "@causentra/langgraph";

const endpoint = process.env.CAUSENTRA_URL ?? "http://127.0.0.1:4318";
const exporter = new HttpBatchExporter({ endpoint: `${endpoint}/v1/events` });
const runtime = new CausentraRuntime({ serviceName: "mixed-framework-example", exporter });

await runtime.trace("cross-framework-support", async () => {
  const parentContext = runtime.currentContext();
  if (parentContext === undefined) throw new Error("Missing active trace context");

  const openai = createOpenAIAgentsTraceProcessor({
    serviceName: "openai-triage",
    exporter,
    parentContext,
  });
  getGlobalTraceProvider().setProcessors([openai]);
  const model = {
    async getResponse() {
      return {
        usage: new Usage({ requests: 1, inputTokens: 2, outputTokens: 3, totalTokens: 5 }),
        output: [{
          type: "message",
          role: "assistant",
          status: "completed",
          content: [{ type: "output_text", text: "route-to-resolution" }],
        }],
      };
    },
    async *getStreamedResponse() { throw new Error("Streaming is not used"); },
  };
  await run(new Agent({
    name: "Triage Agent",
    instructions: "Return the deterministic local route.",
    model,
  }), "synthetic request", { traceIncludeSensitiveData: false });
  await openai.forceFlush();

  await runtime.relationship(
    { kind: "handoff", fromAgent: "Triage Agent", toAgent: "Resolution Graph" },
    async () => {
      const graphTelemetry = createLangGraphInstrumentation({
        serviceName: "langgraph-resolution",
        exporter,
        parentContext: runtime.currentContext(),
      });
      const State = Annotation.Root({ count: Annotation({ reducer: (_left, right) => right }) });
      const graph = new StateGraph(State)
        .addNode("resolve", async (state) => ({ count: state.count + 1 }))
        .addEdge(START, "resolve")
        .addEdge("resolve", END)
        .compile();
      await graph.invoke(
        { count: 0 },
        { callbacks: [graphTelemetry.handler], runName: "Resolution Graph" },
      );
      await graphTelemetry.flush();
    },
  );

  // Demonstrates a visible failed child without leaking its message by default.
  try {
    await runtime.tool("synthetic-failure", async () => {
      throw new TypeError("private synthetic error detail");
    });
  } catch {
    // The example intentionally continues so the parent trace can complete.
  }
});

await runtime.shutdown();
console.log(`Mixed OpenAI Agents + LangGraph trace delivered to ${endpoint}`);

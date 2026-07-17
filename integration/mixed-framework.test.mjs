import assert from "node:assert/strict";
import test from "node:test";
import { Agent, Usage, getGlobalTraceProvider, run } from "@openai/agents";
import { Annotation, END, START, StateGraph } from "@langchain/langgraph";
import { CausentraRuntime, MemoryExporter } from "@causentra/sdk";
import { createOpenAIAgentsTraceProcessor } from "@causentra/openai-agents";
import { createLangGraphInstrumentation } from "@causentra/langgraph";

test("records real OpenAI Agents and LangGraph work in one causal trace", async () => {
  const exporter = new MemoryExporter();
  const runtime = new CausentraRuntime({ serviceName: "mixed-framework-test", exporter });

  await runtime.trace("cross-framework-support", async () => {
    const parentContext = runtime.currentContext();
    assert.ok(parentContext);

    const openai = createOpenAIAgentsTraceProcessor({
      serviceName: "openai-segment",
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
            content: [{ type: "output_text", text: "route-to-graph" }],
          }],
        };
      },
      async *getStreamedResponse() { throw new Error("not used"); },
    };
    await run(new Agent({
      name: "Triage Agent",
      instructions: "Return the deterministic local route.",
      model,
    }), "synthetic request", { traceIncludeSensitiveData: false });
    await openai.forceFlush();

    const langgraph = createLangGraphInstrumentation({
      serviceName: "langgraph-segment",
      exporter,
      parentContext,
    });
    const State = Annotation.Root({ count: Annotation({ reducer: (_left, right) => right }) });
    const graph = new StateGraph(State)
      .addNode("resolve", async (state) => ({ count: state.count + 1 }))
      .addEdge(START, "resolve")
      .addEdge("resolve", END)
      .compile();
    await graph.invoke(
      { count: 0 },
      { callbacks: [langgraph.handler], runName: "Resolution Graph" },
    );
    await langgraph.shutdown();
  });

  const traceIds = new Set(exporter.events.map((event) => event.traceId));
  assert.equal(traceIds.size, 1);
  assert.ok(exporter.events.some((event) => event.attributes["framework.name"] === "openai-agents"));
  assert.ok(exporter.events.some((event) => event.attributes["framework.name"] === "langgraph"));
  const root = exporter.events[0];
  assert.ok(root);
  const frameworkRoots = exporter.events.filter(
    (event) => event.type === "trace.start" && event !== root,
  );
  assert.equal(frameworkRoots.length, 2);
  assert.ok(frameworkRoots.every((event) => event.parentSpanId === root.spanId));
});

import { Annotation, END, START, StateGraph } from "@langchain/langgraph";
import { HttpBatchExporter } from "@causentra/sdk";
import { createLangGraphInstrumentation } from "@causentra/langgraph";

const endpoint = process.env.CAUSENTRA_URL ?? "http://127.0.0.1:4318";
const instrumentation = createLangGraphInstrumentation({
  serviceName: "langgraph-local-example",
  exporter: new HttpBatchExporter({ endpoint: `${endpoint}/v1/events` }),
});

const State = Annotation.Root({
  count: Annotation({ reducer: (_left, right) => right, default: () => 0 }),
});
const graph = new StateGraph(State)
  .addNode("classify", async (state) => ({ count: state.count + 1 }))
  .addNode("resolve", async (state) => ({ count: state.count + 1 }))
  .addEdge(START, "classify")
  .addEdge("classify", "resolve")
  .addEdge("resolve", END)
  .compile();

const result = await graph.invoke(
  { count: 0 },
  { callbacks: [instrumentation.handler], runName: "synthetic-support-graph" },
);
await instrumentation.shutdown();
console.log(`Graph completed with count=${String(result.count)}`);
console.log(`Trace delivered to ${endpoint}`);

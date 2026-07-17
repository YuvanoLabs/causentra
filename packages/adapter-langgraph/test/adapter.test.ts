import assert from "node:assert/strict";
import test from "node:test";
import { assertAdapterConformance, MemoryExporter } from "@causentra/sdk";
import { Annotation, END, START, StateGraph } from "@langchain/langgraph";
import { createLangGraphInstrumentation } from "../src/index.js";

test("maps nested graph/model/tool callbacks without state or payload capture", async () => {
  const exporter = new MemoryExporter();
  let time = Date.parse("2026-07-16T00:00:00.000Z");
  const instrumentation = createLangGraphInstrumentation({
    serviceName: "langgraph-test",
    exporter,
    now: () => new Date((time += 10)),
  });
  const handler = instrumentation.handler;

  await handler.handleChainStart?.(
    { lc: 1, type: "not_implemented", id: ["langgraph", "SupportGraph"] },
    { privateState: "must-not-be-captured" },
    "graph-run",
    undefined,
    ["private-tag"],
    { prompt: "must-not-be-captured" },
    "support-graph",
  );
  await handler.handleToolStart?.(
    { lc: 1, type: "not_implemented", id: ["tools", "lookup_account"] },
    "private-tool-input",
    "tool-run",
    "graph-run",
  );
  await handler.handleToolEnd?.("private-tool-output", "tool-run", "graph-run");
  await handler.handleChainEnd?.({ privateOutput: true }, "graph-run");

  assert.deepEqual(exporter.events.map((event) => event.type), [
    "trace.start", "agent.start", "tool.start", "tool.end", "agent.end", "trace.end",
  ]);
  const serialized = JSON.stringify(exporter.events);
  assert.doesNotMatch(serialized, /must-not-be-captured|private-tool|private-tag/u);
  assert.equal(exporter.events[2]?.parentSpanId, exporter.events[1]?.spanId);
  assert.equal(await instrumentation.flush(), true);
  assertAdapterConformance({
    events: exporter.events,
    frameworkName: "langgraph",
    forbiddenContent: ["must-not-be-captured", "private-tool", "private-tag"],
  });
});

test("marks graph and trace failures without capturing exception messages", async () => {
  const exporter = new MemoryExporter();
  const instrumentation = createLangGraphInstrumentation({
    serviceName: "langgraph-test",
    exporter,
  });
  await instrumentation.handler.handleChainStart?.(
    { lc: 1, type: "not_implemented", id: ["langgraph", "FailingGraph"] },
    {},
    "failed-run",
  );
  await instrumentation.handler.handleChainError?.(
    new TypeError("customer secret in message"),
    "failed-run",
  );
  assert.equal(exporter.events.at(-1)?.status, "error");
  assert.equal(exporter.events[2]?.attributes["error.type"], "TypeError");
  assert.doesNotMatch(JSON.stringify(exporter.events), /customer secret/u);
});

test("integrates with a compiled LangGraph through RunnableConfig callbacks", async () => {
  const exporter = new MemoryExporter();
  const instrumentation = createLangGraphInstrumentation({
    serviceName: "compiled-graph-test",
    exporter,
  });
  const State = Annotation.Root({ count: Annotation<number>() });
  const graph = new StateGraph(State)
    .addNode("increment", (state) => ({ count: state.count + 1 }))
    .addEdge(START, "increment")
    .addEdge("increment", END)
    .compile();

  const result = await graph.invoke(
    { count: 0 },
    { callbacks: [instrumentation.handler], runName: "counter-graph" },
  );
  await instrumentation.flush();

  assert.equal(result.count, 1);
  assert.ok(exporter.events.some((event) => event.type === "trace.start"));
  assert.ok(exporter.events.some((event) => event.name === "counter-graph"));
  assert.ok(exporter.events.some((event) => event.name === "increment"));
  assert.ok(exporter.events.every((event) => !("count" in event.attributes)));
});

test("joins a compiled graph to an existing parent trace", async () => {
  const exporter = new MemoryExporter();
  const parentContext = { traceId: "c".repeat(32), spanId: "d".repeat(16) };
  const instrumentation = createLangGraphInstrumentation({
    serviceName: "joined-graph-test",
    exporter,
    parentContext,
  });
  const State = Annotation.Root({ count: Annotation<number>() });
  const graph = new StateGraph(State)
    .addNode("increment", (state) => ({ count: state.count + 1 }))
    .addEdge(START, "increment")
    .addEdge("increment", END)
    .compile();
  await graph.invoke(
    { count: 0 },
    { callbacks: [instrumentation.handler], runName: "joined-graph" },
  );
  await instrumentation.shutdown();
  assert.ok(exporter.events.every((event) => event.traceId === parentContext.traceId));
  assert.equal(exporter.events[0]?.parentSpanId, parentContext.spanId);
  assertAdapterConformance({
    events: exporter.events,
    frameworkName: "langgraph",
    parentContext,
  });
});

import assert from "node:assert/strict";
import test from "node:test";
import { assertAdapterConformance, MemoryExporter } from "@causentra/sdk";
import type { Span, Trace } from "@openai/agents";
import { createOpenAIAgentsTraceProcessor } from "../src/index.js";

test("maps OpenAI trace and span lifecycle without capturing payloads", async () => {
  const exporter = new MemoryExporter();
  let time = Date.parse("2026-07-16T00:00:00.000Z");
  const processor = createOpenAIAgentsTraceProcessor({
    serviceName: "openai-test",
    exporter,
    now: () => new Date((time += 10)),
  });
  const trace = {
    traceId: "trace_12345678901234567890123456789012",
    name: "Support workflow",
    groupId: "conversation-secret",
    metadata: { tenant: "example", prompt: "must-not-be-captured" },
  } as unknown as Trace;
  const span = {
    traceId: trace.traceId,
    spanId: "span_123",
    parentId: null,
    startedAt: "2026-07-16T00:00:00.020Z",
    endedAt: "2026-07-16T00:00:00.050Z",
    error: null,
    spanData: {
      type: "function",
      name: "lookup_account",
      input: "customer-private-input",
      output: "customer-private-output",
    },
  } as unknown as Span<any>;

  await processor.onTraceStart(trace);
  await processor.onSpanStart(span);
  await processor.onSpanEnd(span);
  await processor.onTraceEnd(trace);

  assert.deepEqual(exporter.events.map((event) => event.type), [
    "trace.start", "tool.start", "tool.end", "trace.end",
  ]);
  const serialized = JSON.stringify(exporter.events);
  assert.doesNotMatch(serialized, /customer-private|must-not-be-captured|conversation-secret/u);
  assert.equal(exporter.events[2]?.durationMs, 30);
  assert.equal(exporter.events[2]?.attributes["framework.span.type"], "function");
  assertAdapterConformance({
    events: exporter.events,
    frameworkName: "openai-agents",
    forbiddenContent: [
      "customer-private-input",
      "customer-private-output",
      "must-not-be-captured",
      "conversation-secret",
    ],
  });
});

test("maps handoffs and joins an existing parent trace", async () => {
  const exporter = new MemoryExporter();
  const parentContext = { traceId: "a".repeat(32), spanId: "b".repeat(16) };
  const processor = createOpenAIAgentsTraceProcessor({
    serviceName: "openai-test",
    exporter,
    parentContext,
  });
  const trace = {
    traceId: "trace_abcdefghijklmnopqrstuvwxyz123456",
    name: "Handoff workflow",
    groupId: null,
  } as unknown as Trace;
  const span = {
    traceId: trace.traceId,
    spanId: "span_handoff",
    parentId: null,
    startedAt: "2026-07-16T00:00:00.000Z",
    endedAt: "2026-07-16T00:00:00.010Z",
    error: null,
    spanData: { type: "handoff", from_agent: "triage", to_agent: "billing" },
  } as unknown as Span<any>;
  await processor.onTraceStart(trace);
  await processor.onSpanStart(span);
  await processor.onSpanEnd(span);
  await processor.onTraceEnd(trace);

  assert.ok(exporter.events.every((event) => event.traceId === parentContext.traceId));
  assert.equal(exporter.events[0]?.parentSpanId, parentContext.spanId);
  assert.equal(exporter.events[1]?.type, "agent.handoff.start");
  assert.equal(
    exporter.events[1]?.attributes["causentra.agent.relationship.kind"],
    "handoff",
  );
  assert.equal(exporter.events[1]?.attributes["causentra.agent.to.name"], "billing");
  assertAdapterConformance({
    events: exporter.events,
    frameworkName: "openai-agents",
    parentContext,
  });
});

import assert from "node:assert/strict";
import test from "node:test";
import { assertAdapterConformance, MemoryExporter } from "@causentra/sdk";
import {
  createExampleFrameworkInstrumentation,
  type ExampleFrameworkEvent,
} from "../src/index.js";

test("maps a private-data-free framework fixture and joins its canonical parent", async () => {
  const exporter = new MemoryExporter();
  const parentContext = { traceId: "a".repeat(32), spanId: "b".repeat(16) };
  const instrumentation = createExampleFrameworkInstrumentation({
    serviceName: "example-adapter-test",
    exporter,
    parentContext,
  });
  const events: ExampleFrameworkEvent[] = [
    event("run.started", "root", undefined, "support run"),
    event("agent.started", "triage", "root", "triage"),
    {
      ...event("handoff.started", "handoff", "triage", "triage to billing"),
      relationship: { kind: "handoff", fromAgent: "triage", toAgent: "billing" },
    },
    event("tool.started", "lookup", "handoff", "lookup account"),
    { ...event("tool.finished", "lookup", "handoff", "lookup account"), durationMs: 2 },
    {
      ...event("handoff.finished", "handoff", "triage", "triage to billing"),
      durationMs: 3,
      relationship: { kind: "handoff", fromAgent: "triage", toAgent: "billing" },
    },
    { ...event("agent.finished", "triage", "root", "triage"), durationMs: 4 },
    { ...event("run.finished", "root", undefined, "support run"), durationMs: 5 },
  ];
  for (const frameworkEvent of events) {
    instrumentation.handle({
      ...frameworkEvent,
      prompt: "private prompt",
      output: "private output",
    } as ExampleFrameworkEvent & { prompt: string; output: string });
  }
  await instrumentation.flush();

  assertAdapterConformance({
    events: exporter.events,
    frameworkName: "example-framework",
    forbiddenContent: ["private prompt", "private output"],
    parentContext,
  });
  assert.equal(
    exporter.events.find((runtimeEvent) => runtimeEvent.type === "agent.handoff.start")
      ?.attributes["causentra.agent.to.name"],
    "billing",
  );
});

test("contains malformed optional telemetry and reports a dropped adapter event", () => {
  const exporter = new MemoryExporter();
  let dropped = 0;
  const instrumentation = createExampleFrameworkInstrumentation({
    serviceName: "example-adapter-test",
    exporter,
    onError: (context) => { dropped += context.droppedEvents; },
  });
  assert.doesNotThrow(() => instrumentation.handle({
    ...event("model.started", "model", "root", "generate"),
    modelTelemetry: { providerName: "" },
  }));
  assert.equal(exporter.events.length, 0);
  assert.equal(dropped, 1);
});

function event(
  kind: ExampleFrameworkEvent["kind"],
  spanId: string,
  parentSpanId: string | undefined,
  name: string,
): ExampleFrameworkEvent {
  return {
    kind,
    traceId: "framework-trace",
    spanId,
    ...(parentSpanId === undefined ? {} : { parentSpanId }),
    name,
  };
}

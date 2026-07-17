import assert from "node:assert/strict";
import test from "node:test";
import {
  AdapterEventBridge,
  assertAdapterConformance,
  createAgentRelationshipAttributes,
  MemoryExporter,
  OpenTelemetryProjector,
  normalizeExternalId,
} from "../src/index.js";

test("adapter bridge maps IDs, redacts attributes, and assigns stable order", () => {
  const exporter = new MemoryExporter();
  const bridge = new AdapterEventBridge({ serviceName: "adapter-test", exporter });
  bridge.emit({
    externalTraceId: "framework-trace",
    externalSpanId: "framework-trace:root",
    externalSessionId: "private-conversation-id",
    timestamp: "2026-07-16T00:00:00.000Z",
    type: "trace.start",
    name: "workflow",
    attributes: { token: "secret", safe: true },
  });
  bridge.emit({
    externalTraceId: "framework-trace",
    externalSpanId: "framework-trace:root",
    timestamp: "2026-07-16T00:00:00.100Z",
    type: "trace.end",
    name: "workflow",
    status: "ok",
    durationMs: 100,
  });

  assert.equal(exporter.events[0]?.traceId, normalizeExternalId("trace", "framework-trace"));
  assert.equal(exporter.events[0]?.attributes.token, "[REDACTED]");
  assert.deepEqual(exporter.events.map((event) => event.sequence), [0, 1]);
  assert.doesNotMatch(JSON.stringify(exporter.events), /private-conversation-id/u);
});

test("adapter bridge joins an existing canonical parent trace", () => {
  const exporter = new MemoryExporter();
  const parentContext = {
    traceId: "1".repeat(32),
    spanId: "2".repeat(16),
    sessionId: "3".repeat(32),
  };
  const bridge = new AdapterEventBridge({
    serviceName: "joined-adapter",
    exporter,
    parentContext,
  });
  bridge.emit({
    externalTraceId: "framework-trace",
    externalSpanId: "framework-root",
    type: "trace.start",
    name: "joined-workflow",
  });
  assert.equal(exporter.events[0]?.traceId, parentContext.traceId);
  assert.equal(exporter.events[0]?.parentSpanId, parentContext.spanId);
  assert.equal(exporter.events[0]?.sessionId, parentContext.sessionId);
});

test("adapter conformance contract detects lifecycle, privacy, and parent violations", () => {
  const exporter = new MemoryExporter();
  const parentContext = { traceId: "4".repeat(32), spanId: "5".repeat(16) };
  const bridge = new AdapterEventBridge({
    serviceName: "conformance-test",
    exporter,
    parentContext,
  });
  for (const type of ["trace.start", "trace.end"] as const) {
    bridge.emit({
      externalTraceId: "external-trace",
      externalSpanId: "external-root",
      type,
      name: "framework-run",
      attributes: { "framework.name": "example-framework" },
    });
  }
  assert.doesNotThrow(() => assertAdapterConformance({
    events: exporter.events,
    frameworkName: "example-framework",
    forbiddenContent: ["private-payload"],
    parentContext,
  }));
  assert.throws(
    () => assertAdapterConformance({
      events: exporter.events,
      frameworkName: "wrong-framework",
    }),
    /identifies framework/u,
  );
});

test("creates portable agent handoff attributes", () => {
  assert.deepEqual(
    createAgentRelationshipAttributes({
      kind: "handoff",
      fromAgent: "triage",
      toAgent: "billing",
      relationshipId: "handoff-1",
    }),
    {
      "causentra.agent.relationship.kind": "handoff",
      "causentra.agent.from.name": "triage",
      "causentra.agent.to.name": "billing",
      "causentra.agent.relationship.id": "handoff-1",
    },
  );
});

test("OpenTelemetry projector creates a completed semantic span", () => {
  const exporter = new MemoryExporter();
  const bridge = new AdapterEventBridge({ serviceName: "otel-test", exporter });
  bridge.emit({
    externalTraceId: "trace",
    externalSpanId: "model-span",
    timestamp: "2026-07-16T00:00:00.000Z",
    type: "model.start",
    name: "generate-answer",
    attributes: { model: "example-model" },
  });
  bridge.emit({
    externalTraceId: "trace",
    externalSpanId: "model-span",
    timestamp: "2026-07-16T00:00:00.025Z",
    type: "model.end",
    name: "generate-answer",
    status: "ok",
    durationMs: 25,
    attributes: { "gen_ai.usage.output_tokens": 10 },
  });

  const projector = new OpenTelemetryProjector();
  assert.equal(projector.ingest(exporter.events[0] as (typeof exporter.events)[number]), undefined);
  const span = projector.ingest(exporter.events[1] as (typeof exporter.events)[number]);
  assert.ok(span);
  assert.equal(span.status, "OK");
  assert.match(span.traceId, /^[0-9a-f]{32}$/u);
  assert.match(span.spanId, /^[0-9a-f]{16}$/u);
  assert.deepEqual(span.resourceAttributes, { "service.name": "otel-test" });
  assert.equal("service.name" in span.attributes, false);
  assert.equal(span.attributes["gen_ai.operation.name"], "chat");
  assert.equal(span.attributes["gen_ai.request.model"], "example-model");
  assert.equal(BigInt(span.endTimeUnixNano) - BigInt(span.startTimeUnixNano), 25_000_000n);
});

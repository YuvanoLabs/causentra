import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import test from "node:test";
import {
  CausentraRuntime,
  createModelTelemetryAttributes,
  EventValidationError,
  HttpBatchExporter,
  MemoryExporter,
  WELL_KNOWN_GENAI_PROVIDERS,
  validateEvent,
} from "../src/index.js";

interface ProviderSupportManifest {
  schemaVersion: "1.0";
  canonicalProviders: string[];
  deepPythonProviders: string[];
}

test("matches the shared 15-provider support contract", async () => {
  const path = new URL("../../fixtures/provider-support-v1.json", import.meta.url);
  const manifest = JSON.parse(await readFile(path, "utf8")) as ProviderSupportManifest;

  assert.equal(manifest.schemaVersion, "1.0");
  assert.deepEqual([...WELL_KNOWN_GENAI_PROVIDERS].sort(), manifest.canonicalProviders.sort());
  assert.equal(manifest.canonicalProviders.length, 15);
  assert.equal(manifest.deepPythonProviders.length, 8);
});

test("preserves every current OpenTelemetry well-known provider identifier", () => {
  for (const providerName of WELL_KNOWN_GENAI_PROVIDERS) {
    assert.equal(
      createModelTelemetryAttributes({ providerName })["gen_ai.provider.name"],
      providerName,
    );
  }
  assert.equal(
    createModelTelemetryAttributes({ providerName: "azure-openai" })["gen_ai.provider.name"],
    "azure.ai.openai",
  );
  assert.equal(
    createModelTelemetryAttributes({ providerName: "Private Provider" })["gen_ai.provider.name"],
    "private provider",
  );
});

test("propagates nested context, orders events, and redacts before export", async () => {
  const exporter = new MemoryExporter();
  const runtime = new CausentraRuntime({ serviceName: "test-agent", exporter });

  await runtime.trace("workflow", async () => {
    const root = runtime.currentContext();
    assert.ok(root);
    runtime.record("configured", {
      attributes: { token: "sensitive", nested: { password: "hidden", safe: true } },
    });
    await runtime.span("lookup", "tool", async () => {
      const child = runtime.currentContext();
      assert.ok(child);
      assert.equal(child.traceId, root.traceId);
      assert.equal(child.parentSpanId, root.spanId);
    });
  });

  assert.deepEqual(
    exporter.events.map((event) => event.type),
    ["trace.start", "custom", "tool.start", "tool.end", "trace.end"],
  );
  assert.deepEqual(
    exporter.events.map((event) => event.sequence),
    [0, 1, 2, 3, 4],
  );
  assert.equal(exporter.events[1]?.attributes.token, "[REDACTED]");
  assert.deepEqual(exporter.events[1]?.attributes.nested, {
    password: "[REDACTED]",
    safe: true,
  });
  const invalidType: unknown = {
    ...exporter.events[0],
    type: "not namespaced",
  };
  assert.throws(
    () => validateEvent(invalidType),
    (error) => error instanceof EventValidationError && error.field === "type",
  );
  assert.equal(await runtime.flush(), true);
});

test("records sanitized errors and rethrows the original application error", async () => {
  const exporter = new MemoryExporter();
  const runtime = new CausentraRuntime({ serviceName: "test-agent", exporter });
  const expected = new TypeError("provider key abc123 was rejected");

  await assert.rejects(
    runtime.trace("failing", () => {
      throw expected;
    }),
    (error) => error === expected,
  );
  const end = exporter.events.at(-1);
  assert.equal(end?.type, "trace.end");
  assert.equal(end?.status, "error");
  assert.equal(end?.attributes["error.type"], "TypeError");
  assert.equal(end?.attributes["error.message"], undefined);
  assert.doesNotMatch(JSON.stringify(exporter.events), /abc123/u);

  const optInExporter = new MemoryExporter();
  const optIn = new CausentraRuntime({
    serviceName: "test-agent",
    exporter: optInExporter,
    includeErrorMessage: true,
  });
  await assert.rejects(optIn.trace("opt-in", () => { throw expected; }));
  assert.equal(
    optInExporter.events.at(-1)?.attributes["error.message"],
    "provider key abc123 was rejected",
  );
});

test("injects and continues strict W3C trace context", async () => {
  const firstExporter = new MemoryExporter();
  const first = new CausentraRuntime({ serviceName: "caller", exporter: firstExporter });
  let carrier: Record<string, string> | undefined;
  await first.trace("caller-workflow", async () => {
    carrier = first.injectTraceContext({ "x-request-id": "synthetic" });
  });
  assert.match(carrier?.traceparent ?? "", /^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/u);

  const secondExporter = new MemoryExporter();
  const second = new CausentraRuntime({ serviceName: "worker", exporter: secondExporter });
  await second.traceFromCarrier("worker-workflow", carrier ?? {}, async () => undefined);
  assert.equal(secondExporter.events[0]?.traceId, firstExporter.events[0]?.traceId);
  assert.equal(secondExporter.events[0]?.parentSpanId, firstExporter.events[0]?.spanId);
  assert.equal(secondExporter.events[0]?.spanId.length, 16);

  const invalid = { traceparent: "00-00000000000000000000000000000000-0000000000000000-01" };
  await second.traceFromCarrier("new-root", invalid, async () => undefined);
  assert.notEqual(secondExporter.events[2]?.traceId, firstExporter.events[0]?.traceId);
});

test("rejects invalid schema before storage or export", () => {
  assert.throws(
    () => validateEvent({ schemaVersion: "99" }),
    (error) =>
      error instanceof EventValidationError && error.field === "schemaVersion",
  );
});

test("normalizes provider, model, usage, and cost with explicit provenance", () => {
  assert.deepEqual(
    createModelTelemetryAttributes({
      providerName: "anthropic",
      requestModel: "claude-synthetic",
      inputTokens: 10,
      outputTokens: 5,
      costUsd: 0.001,
      costBasis: "catalog_estimate",
    }),
    {
      "gen_ai.provider.name": "anthropic",
      "gen_ai.request.model": "claude-synthetic",
      "gen_ai.usage.input_tokens": 10,
      "gen_ai.usage.output_tokens": 5,
      "causentra.cost.usd": 0.001,
      "causentra.cost.basis": "catalog_estimate",
    },
  );
  assert.throws(
    () => createModelTelemetryAttributes({ costUsd: 1 }),
    /costBasis is required/u,
  );
});

test("provides typed multi-provider and agent-relationship convenience operations", async () => {
  const exporter = new MemoryExporter();
  const runtime = new CausentraRuntime({ serviceName: "multi-agent", exporter });
  await runtime.trace("workflow", async () => {
    await runtime.agent("triage", async () => undefined);
    await runtime.model(
      "generate",
      { providerName: "bedrock", requestModel: "model-synthetic", inputTokens: 4 },
      async () => undefined,
    );
    await runtime.relationship(
      { kind: "handoff", fromAgent: "triage", toAgent: "billing" },
      async () => runtime.tool("lookup", async () => undefined),
    );
  });
  assert.ok(exporter.events.some((event) => event.type === "agent.handoff.start"));
  assert.ok(exporter.events.some(
    (event) => event.attributes["gen_ai.provider.name"] === "aws.bedrock",
  ));
  const tool = exporter.events.find((event) => event.type === "tool.start");
  const handoff = exporter.events.find((event) => event.type === "agent.handoff.start");
  assert.equal(tool?.parentSpanId, handoff?.spanId);
});

test("bounds the HTTP queue and contains errors thrown by diagnostics", async () => {
  const source = new MemoryExporter();
  const runtime = new CausentraRuntime({ serviceName: "queue-agent", exporter: source });
  await runtime.trace("queue-source", async () => undefined);
  let dropped = 0;
  const exporter = new HttpBatchExporter({
    endpoint: "http://127.0.0.1:1/v1/events",
    maxQueueSize: 1,
    flushIntervalMs: 60_000,
    maxRetries: 0,
    requestTimeoutMs: 20,
    onError: (context) => {
      dropped = context.droppedEvents;
      throw new Error("diagnostic callbacks are untrusted");
    },
  });
  assert.doesNotThrow(() => {
    exporter.emit(source.events[0] as (typeof source.events)[number]);
    exporter.emit(source.events[1] as (typeof source.events)[number]);
  });
  assert.equal(dropped, 1);
  assert.equal(await exporter.flush(), false);
});

test("HTTP exporter batches and retries transient failures", async () => {
  let requests = 0;
  let received = 0;
  const server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => {
      requests += 1;
      const payload = JSON.parse(Buffer.concat(chunks).toString("utf8")) as {
        events: unknown[];
      };
      received = payload.events.length;
      response.writeHead(requests === 1 ? 503 : 202);
      response.end();
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");

  try {
    const exporter = new HttpBatchExporter({
      endpoint: `http://127.0.0.1:${address.port}/v1/events`,
      batchSize: 10,
      maxRetries: 1,
      retryBaseDelayMs: 1,
    });
    const runtime = new CausentraRuntime({ serviceName: "retry-agent", exporter });
    await runtime.trace("retry-me", async () => undefined);
    assert.equal(await runtime.flush(), true);
    assert.equal(requests, 2);
    assert.equal(received, 2);
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error === undefined ? resolve() : reject(error))),
    );
  }
});

import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";
import { resourceFromAttributes } from "@opentelemetry/resources";
import {
  InMemorySpanExporter,
  SimpleSpanProcessor,
} from "@opentelemetry/sdk-trace-base";
import { NodeTracerProvider } from "@opentelemetry/sdk-trace-node";
import { CausentraRuntime } from "@causentra/sdk";
import {
  OpenTelemetryEventExporter,
  startCausentraRuntimeOtlp,
} from "../src/index.js";

test("exports a causal Causentra trace through a real OTel provider", async () => {
  const memory = new InMemorySpanExporter();
  const provider = new NodeTracerProvider({
    resource: resourceFromAttributes({ "service.name": "otel-test" }),
    spanProcessors: [new SimpleSpanProcessor(memory)],
  });
  const exporter = new OpenTelemetryEventExporter({
    tracer: provider.getTracer("adapter-test"),
    forceFlush: () => provider.forceFlush(),
    shutdown: () => provider.shutdown(),
  });
  const runtime = new CausentraRuntime({ serviceName: "otel-test", exporter });

  await runtime.trace("support-workflow", async () => {
    await runtime.span("lookup-account", "tool", async () => undefined, {
      token: "already-redacted-by-sdk",
    });
  });
  assert.equal(await runtime.flush(), true);

  const spans = memory.getFinishedSpans();
  assert.equal(spans.length, 2);
  const root = spans.find((span) => span.name === "support-workflow");
  const child = spans.find((span) => span.name === "lookup-account");
  assert.ok(root && child);
  assert.equal(child.spanContext().traceId, root.spanContext().traceId);
  assert.equal(child.parentSpanContext?.spanId, root.spanContext().spanId);
  assert.equal(child.attributes["gen_ai.operation.name"], "execute_tool");
  assert.equal(child.attributes.token, "[REDACTED]");
  await runtime.shutdown();
});

test("exports OTLP HTTP/protobuf through the official exporter", async () => {
  let receivedBytes = 0;
  let receivedType = "";
  const server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => {
      receivedBytes += Buffer.concat(chunks).length;
      receivedType = String(request.headers["content-type"] ?? "");
      response.writeHead(200, { "content-type": "application/x-protobuf" });
      response.end();
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");

  try {
    const otlp = startCausentraRuntimeOtlp({
      serviceName: "otlp-wire-test",
      endpoint: `http://127.0.0.1:${String(address.port)}/v1/traces`,
    });
    const runtime = new CausentraRuntime({
      serviceName: "otlp-wire-test",
      exporter: otlp.exporter,
    });
    await runtime.trace("wire-workflow", async () => undefined);
    await runtime.shutdown();
    assert.ok(receivedBytes > 0);
    assert.match(receivedType, /application\/x-protobuf/u);
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error === undefined ? resolve() : reject(error))),
    );
  }
});

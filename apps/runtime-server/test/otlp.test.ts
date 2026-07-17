import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { gzipSync } from "node:zlib";
import test from "node:test";
import { SpanStatusCode } from "@opentelemetry/api";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-proto";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { SimpleSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { NodeTracerProvider } from "@opentelemetry/sdk-trace-node";
import { ATTR_SERVICE_NAME } from "@opentelemetry/semantic-conventions";
import { startRuntimeServer } from "../src/server.js";
import { convertOtlpTraces } from "../src/otlp.js";
import { FileTraceStore } from "../src/store.js";

test("ingests privacy-safe OTLP/HTTP JSON from any instrumented provider", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-otlp-json-"));
  const store = await FileTraceStore.open(join(directory, "events.ndjson"));
  const running = await startRuntimeServer({ port: 0, store });
  const traceId = "1".repeat(32);
  const payload = {
    resourceSpans: [{
      resource: { attributes: [attribute("service.name", "provider-router")] },
      scopeSpans: [{
        scope: { name: "openinference", version: "1.0.0" },
        spans: [{
          traceId,
          spanId: "2".repeat(16),
          name: "anthropic chat",
          kind: 3,
          startTimeUnixNano: "1784160000000000000",
          endTimeUnixNano: "1784160000010000000",
          attributes: [
            attribute("gen_ai.operation.name", "chat"),
            attribute("gen_ai.provider.name", "anthropic"),
            attribute("gen_ai.request.model", "claude-synthetic"),
            attribute("gen_ai.input.messages", "private prompt"),
            attribute("http.request.header.authorization", "Bearer private"),
          ],
          status: { code: 1 },
        }],
      }],
    }],
  };

  try {
    const response = await fetch(`${running.url}/v1/traces`, {
      method: "POST",
      headers: { "content-type": "application/json", "content-encoding": "gzip" },
      body: gzipSync(JSON.stringify(payload)),
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {});
    const detail = store.get(traceId);
    assert.equal(detail?.events.length, 2);
    assert.equal(detail?.summary.status, "ok");
    assert.equal(detail?.events[1]?.attributes["gen_ai.provider.name"], "anthropic");
    const serialized = JSON.stringify(detail);
    assert.doesNotMatch(serialized, /private prompt|Bearer private/u);
  } finally {
    await running.close();
  }
});

test("ingests official OTLP/HTTP protobuf exporter traffic", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-otlp-proto-"));
  const store = await FileTraceStore.open(join(directory, "events.ndjson"));
  const running = await startRuntimeServer({ port: 0, store });
  const exporter = new OTLPTraceExporter({ url: `${running.url}/v1/traces` });
  const provider = new NodeTracerProvider({
    resource: resourceFromAttributes({ [ATTR_SERVICE_NAME]: "vercel-ai-service" }),
    spanProcessors: [new SimpleSpanProcessor(exporter)],
  });

  try {
    const span = provider.getTracer("provider-integration").startSpan("google generate");
    span.setAttributes({
      "gen_ai.operation.name": "generate_content",
      "gen_ai.provider.name": "gcp.gen_ai",
      "gen_ai.request.model": "gemini-synthetic",
      "gen_ai.input.messages": "private content",
    });
    span.setStatus({ code: SpanStatusCode.OK });
    span.end();
    await provider.forceFlush();

    assert.equal(store.traceCount(), 1);
    const detail = store.list(1)[0];
    assert.ok(detail);
    const events = store.get(detail.traceId)?.events ?? [];
    assert.equal(events.length, 2);
    assert.equal(events[1]?.attributes["gen_ai.provider.name"], "gcp.gen_ai");
    assert.doesNotMatch(JSON.stringify(events), /private content/u);
  } finally {
    await provider.shutdown();
    await running.close();
  }
});

test("normalizes provider vocabulary across OTLP producers", () => {
  const providers = [
    ["openai", "openai"],
    ["anthropic", "anthropic"],
    ["bedrock", "aws.bedrock"],
    ["azure-openai", "azure.ai.openai"],
    ["gemini", "gcp.gemini"],
    ["vertex-ai", "gcp.vertex_ai"],
    ["mistral", "mistral_ai"],
    ["xai", "x_ai"],
  ] as const;
  const resourceSpans = providers.map(([provider], index) => ({
    resource: { attributes: [attribute("service.name", `${provider}-service`)] },
    scopeSpans: [{ spans: [{
      traceId: (index + 1).toString(16).repeat(32),
      spanId: (index + 1).toString(16).repeat(16),
      name: `${provider} operation`,
      startTimeUnixNano: "1784160000000000000",
      endTimeUnixNano: "1784160000001000000",
      attributes: [attribute("gen_ai.system", provider)],
      status: { code: 1 },
    }] }],
  }));
  const result = convertOtlpTraces({ resourceSpans });
  assert.equal(result.rejectedSpans, 0);
  assert.deepEqual(
    result.events.filter((event) => event.type === "trace.end")
      .map((event) => event.attributes["gen_ai.provider.name"]),
    providers.map(([, expected]) => expected),
  );
});

function attribute(key: string, value: string): Record<string, unknown> {
  return { key, value: { stringValue: value } };
}

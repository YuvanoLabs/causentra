import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { CausentraRuntime, MemoryExporter } from "@causentra/sdk";
import { startRuntimeServer } from "../src/server.js";
import { FileTraceStore } from "../src/store.js";

test("refuses unauthenticated non-loopback binding by default", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-"));
  const store = await FileTraceStore.open(join(directory, "events.ndjson"));
  await assert.rejects(
    startRuntimeServer({ host: "0.0.0.0", port: 0, store }),
    /Refusing unauthenticated non-loopback bind/u,
  );
});

test("ingests, deduplicates, queries, and recovers a trace", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-"));
  const file = join(directory, "events.ndjson");
  const store = await FileTraceStore.open(file);
  const running = await startRuntimeServer({ port: 0, store });
  const exporter = new MemoryExporter();
  const runtime = new CausentraRuntime({ serviceName: "integration-agent", exporter });
  await runtime.trace("integration-workflow", async () => {
    await runtime.span("lookup", "tool", async () => undefined);
  });

  try {
    const ingest = await fetch(`${running.url}/v1/events`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ events: exporter.events }),
    });
    assert.equal(ingest.status, 202);
    assert.deepEqual(await ingest.json(), { accepted: 4, duplicates: 0 });

    const duplicate = await fetch(`${running.url}/v1/events`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ events: exporter.events }),
    });
    assert.deepEqual(await duplicate.json(), { accepted: 0, duplicates: 4 });

    const list = (await fetch(`${running.url}/api/traces`).then((response) =>
      response.json(),
    )) as { traces: Array<{
      traceId: string;
      status: string;
      eventCount: number;
      frameworks: string[];
      providers: string[];
      models: string[];
      tools: string[];
      agents: string[];
      relationshipCount: number;
    }> };
    assert.equal(list.traces.length, 1);
    assert.equal(list.traces[0]?.status, "ok");
    assert.equal(list.traces[0]?.eventCount, 4);
    assert.deepEqual(list.traces[0]?.frameworks, []);
    assert.deepEqual(list.traces[0]?.providers, []);
    assert.deepEqual(list.traces[0]?.models, []);
    assert.deepEqual(list.traces[0]?.tools, ["lookup"]);
    assert.deepEqual(list.traces[0]?.agents, []);
    assert.equal(list.traces[0]?.relationshipCount, 0);

    const traceId = list.traces[0]?.traceId;
    assert.ok(traceId);
    const detail = (await fetch(`${running.url}/api/traces/${traceId}`).then(
      (response) => response.json(),
    )) as { events: Array<{ sequence: number }> };
    assert.deepEqual(
      detail.events.map((event) => event.sequence),
      [0, 1, 2, 3],
    );

    const bundleResponse = await fetch(`${running.url}/api/traces/${traceId}/export`);
    assert.equal(bundleResponse.status, 200);
    const bundle = (await bundleResponse.json()) as {
      format: string;
      version: number;
      trace: { events: unknown[] };
    };
    assert.equal(bundle.format, "causentra.trace-bundle");
    assert.equal(bundle.version, 1);
    assert.equal(bundle.trace.events.length, 4);

    const deletion = await fetch(`${running.url}/api/traces/${traceId}`, {
      method: "DELETE",
    });
    assert.equal(deletion.status, 200);
    assert.equal(store.traceCount(), 0);

    const imported = await fetch(`${running.url}/api/traces/import`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(bundle),
    });
    assert.equal(imported.status, 202);
    assert.equal(store.traceCount(), 1);

    const dashboard = await fetch(running.url);
    assert.equal(dashboard.status, 200);
    const dashboardHtml = await dashboard.text();
    assert.match(dashboardHtml, /Every agent action/u);
    assert.match(dashboardHtml, /id="trace-filters"/u);
    const dashboardJavaScript = await fetch(`${running.url}/app.js`).then((response) => response.text());
    assert.match(dashboardJavaScript, /Agent relationships/u);
    assert.match(dashboardJavaScript, /causentra\.agent\.from\.name/u);
  } finally {
    await running.close();
  }

  const recovered = await FileTraceStore.open(file);
  assert.equal(recovered.traceCount(), 1);
  assert.equal(recovered.eventCount(), 4);
  assert.equal((await readFile(file, "utf8")).trim().split(/\r?\n/u).length, 4);
});

test("prunes old traces only through an explicit retention request", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-"));
  const store = await FileTraceStore.open(join(directory, "events.ndjson"));
  const exporter = new MemoryExporter();
  const runtime = new CausentraRuntime({ serviceName: "retention-agent", exporter });
  await runtime.trace("older", async () => undefined);
  await new Promise((resolve) => setTimeout(resolve, 2));
  await runtime.trace("newer", async () => undefined);
  await store.append(exporter.events);
  const running = await startRuntimeServer({ port: 0, store });
  try {
    const response = await fetch(`${running.url}/api/retention/prune`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ keepLatest: 1 }),
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { removed: 1, remaining: 1 });
    assert.equal(store.list(10)[0]?.name, "newer");
  } finally {
    await running.close();
  }
});

test("filters trace summaries by cross-framework operational dimensions", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-"));
  const store = await FileTraceStore.open(join(directory, "events.ndjson"));
  const exporter = new MemoryExporter();
  const openAiSession = "1".repeat(32);
  const langGraphSession = "2".repeat(32);
  const openAiRuntime = new CausentraRuntime({
    serviceName: "openai-service",
    exporter,
    sessionId: openAiSession,
  });
  await openAiRuntime.trace("triage", async () => {
    await openAiRuntime.model(
      "classify",
      { providerName: "openai", requestModel: "model-a" },
      async () => undefined,
    );
    await openAiRuntime.relationship(
      { kind: "handoff", fromAgent: "triage", toAgent: "billing" },
      () => openAiRuntime.tool("lookup-account", async () => undefined),
    );
  }, { "framework.name": "openai-agents" });

  const langGraphRuntime = new CausentraRuntime({
    serviceName: "graph-service",
    exporter,
    sessionId: langGraphSession,
  });
  await langGraphRuntime.trace("resolution", async () => {
    await langGraphRuntime.model(
      "draft",
      { providerName: "anthropic", requestModel: "model-b" },
      async () => undefined,
    );
    try {
      await langGraphRuntime.tool("search-orders", async () => {
        throw new TypeError("private failure detail");
      });
    } catch {
      // A contained failed child must still make the trace discoverable by status.
    }
  }, { "framework.name": "langgraph" });
  await store.append(exporter.events);
  const running = await startRuntimeServer({ port: 0, store });
  try {
    const query = new URLSearchParams({
      framework: "lang",
      provider: "anth",
      model: "model-b",
      status: "error",
      tool: "search",
      session: langGraphSession,
      q: "graph-service",
    });
    const response = await fetch(`${running.url}/api/traces?${query.toString()}`);
    assert.equal(response.status, 200);
    const payload = (await response.json()) as {
      traces: Array<{
        name: string;
        frameworks: string[];
        providers: string[];
        models: string[];
        tools: string[];
        agents: string[];
        sessionIds: string[];
        relationshipCount: number;
      }>;
    };
    assert.equal(payload.traces.length, 1);
    const summary = payload.traces[0];
    assert.equal(summary?.name, "resolution");
    assert.deepEqual(summary?.frameworks, ["langgraph"]);
    assert.deepEqual(summary?.providers, ["anthropic"]);
    assert.deepEqual(summary?.models, ["model-b"]);
    assert.deepEqual(summary?.tools, ["search-orders"]);
    assert.deepEqual(summary?.agents, []);
    assert.deepEqual(summary?.sessionIds, [langGraphSession]);
    assert.equal(summary?.relationshipCount, 0);
    const handoffSummary = store.list(10, { framework: "openai" })[0];
    assert.equal(handoffSummary?.relationshipCount, 1);
    assert.deepEqual(handoffSummary?.providers, ["openai"]);
    assert.deepEqual(handoffSummary?.models, ["model-a"]);
    assert.deepEqual(handoffSummary?.agents, ["billing", "triage"]);

    const privateContentSearch = await fetch(
      `${running.url}/api/traces?q=${encodeURIComponent("private failure detail")}`,
    ).then((result) => result.json()) as { traces: unknown[] };
    assert.equal(privateContentSearch.traces.length, 0);

    const invalid = await fetch(`${running.url}/api/traces?session=not-a-session`);
    assert.equal(invalid.status, 400);
    const invalidPayload = (await invalid.json()) as { error: { code: string } };
    assert.equal(invalidPayload.error.code, "invalid_trace_filter");
  } finally {
    await running.close();
  }
});

test("rejects an invalid batch atomically", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-"));
  const store = await FileTraceStore.open(join(directory, "events.ndjson"));
  const running = await startRuntimeServer({ port: 0, store });
  try {
    const response = await fetch(`${running.url}/v1/events`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ events: [{ schemaVersion: "invalid" }] }),
    });
    assert.equal(response.status, 400);
    const payload = (await response.json()) as { error: { code: string } };
    assert.equal(payload.error.code, "invalid_event");
    assert.equal(store.eventCount(), 0);
  } finally {
    await running.close();
  }
});

test("deduplicates identical events across concurrent appends", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-"));
  const file = join(directory, "events.ndjson");
  const store = await FileTraceStore.open(file);
  const exporter = new MemoryExporter();
  const runtime = new CausentraRuntime({ serviceName: "concurrency-agent", exporter });
  await runtime.trace("concurrent-write", async () => undefined);

  const accepted = await Promise.all([
    store.append([...exporter.events, exporter.events[0] as (typeof exporter.events)[number]]),
    store.append(exporter.events),
  ]);
  assert.equal(accepted.reduce((sum, value) => sum + value, 0), 2);
  assert.equal(store.eventCount(), 2);
  assert.equal((await readFile(file, "utf8")).trim().split(/\r?\n/u).length, 2);
});

test("preserves valid records and reports corrupt recovery lines", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-"));
  const file = join(directory, "events.ndjson");
  const exporter = new MemoryExporter();
  const runtime = new CausentraRuntime({ serviceName: "recovery-agent", exporter });
  await runtime.trace("recoverable", async () => undefined);
  await writeFile(
    file,
    `${JSON.stringify(exporter.events[0])}\nnot-json\n${JSON.stringify(exporter.events[1])}\n`,
    "utf8",
  );

  const store = await FileTraceStore.open(file);
  assert.equal(store.eventCount(), 2);
  assert.equal(store.traceCount(), 1);
  assert.equal(store.recoveryWarningCount(), 1);
});

test("returns a structured 413 response without resetting the connection", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-"));
  const store = await FileTraceStore.open(join(directory, "events.ndjson"));
  const running = await startRuntimeServer({ port: 0, store });
  try {
    const response = await fetch(`${running.url}/v1/events`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ events: [], padding: "x".repeat(1024 * 1024) }),
    });
    assert.equal(response.status, 413);
    const payload = (await response.json()) as { error: { code: string } };
    assert.equal(payload.error.code, "body_too_large");
    assert.equal(store.eventCount(), 0);
  } finally {
    await running.close();
  }
});

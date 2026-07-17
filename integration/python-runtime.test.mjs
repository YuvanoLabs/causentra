import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { FileTraceStore, startRuntimeServer } from "@causentra/server";

test("ingests a Python multi-agent trace through the shared collector", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-python-"));
  const store = await FileTraceStore.open(join(directory, "events.ndjson"));
  const server = await startRuntimeServer({ host: "127.0.0.1", port: 0, store });
  try {
    const example = fileURLToPath(new URL("../examples/python/basic.py", import.meta.url));
    const pythonPath = fileURLToPath(new URL("../python/src", import.meta.url));
    await runPython(example, {
      ...process.env,
      PYTHONPATH: pythonPath,
      CAUSENTRA_ENDPOINT: `${server.url}/v1/events`,
    });
    assert.equal(store.traceCount(), 1);
    const [trace] = store.list(10);
    assert.ok(trace);
    assert.equal(trace.serviceName, "python-multi-agent-demo");
    assert.equal(trace.relationshipCount, 1);
    assert.deepEqual(trace.providers, ["anthropic"]);
    const detail = store.get(trace.traceId);
    assert.ok(detail?.events.some((event) => event.type === "agent.handoff.start"));
  } finally {
    await server.close();
    await rm(directory, { recursive: true, force: true });
  }
});

function runPython(script, env) {
  return new Promise((resolve, reject) => {
    const child = spawn("python", [script], { env, stdio: ["ignore", "pipe", "pipe"] });
    let stderr = "";
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`Python example exited ${code}: ${stderr.slice(0, 2_000)}`));
    });
  });
}

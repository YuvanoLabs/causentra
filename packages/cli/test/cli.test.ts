import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { run } from "../src/index.js";

test("help succeeds and unknown commands return usage error", async () => {
  assert.equal(await run(["help"]), 0);
  assert.equal(await run(["not-a-command"]), 2);
});

test("exports, imports, deletes, and prunes through the local API", async () => {
  const requests: Array<{ method: string; path: string; body: string }> = [];
  const traceId = "a".repeat(32);
  const bundle = {
    format: "causentra.trace-bundle",
    version: 1,
    exportedAt: "2026-07-16T00:00:00.000Z",
    trace: { summary: { traceId }, events: [{ eventId: "b".repeat(32) }] },
  };
  const server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => {
      const path = request.url ?? "";
      requests.push({
        method: request.method ?? "",
        path,
        body: Buffer.concat(chunks).toString("utf8"),
      });
      response.setHeader("content-type", "application/json");
      if (path.endsWith("/export")) response.end(JSON.stringify(bundle));
      else if (path === "/api/traces/import") response.end('{"accepted":1}');
      else if (path === "/api/retention/prune") {
        response.end('{"removed":2,"remaining":3}');
      } else response.end('{"deleted":true}');
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address !== null && typeof address === "object");
  const previousUrl = process.env.CAUSENTRA_URL;
  process.env.CAUSENTRA_URL = `http://127.0.0.1:${String(address.port)}`;
  const directory = await mkdtemp(join(tmpdir(), "causentra-cli-"));
  const output = join(directory, "trace.json");

  try {
    assert.equal(await run(["export", traceId, output]), 0);
    assert.deepEqual(JSON.parse(await readFile(output, "utf8")), bundle);
    assert.equal(await run(["export", traceId, output]), 1, "must not overwrite exports");
    assert.equal(await run(["import", output]), 0);
    assert.equal(await run(["delete", traceId]), 0);
    assert.equal(await run(["prune", "3"]), 0);
    assert.equal(await run(["prune", "-1"]), 2);
    assert.deepEqual(
      requests.map(({ method, path }) => ({ method, path })),
      [
        { method: "GET", path: `/api/traces/${traceId}/export` },
        { method: "GET", path: `/api/traces/${traceId}/export` },
        { method: "POST", path: "/api/traces/import" },
        { method: "DELETE", path: `/api/traces/${traceId}` },
        { method: "POST", path: "/api/retention/prune" },
      ],
    );
    assert.deepEqual(JSON.parse(requests[2]?.body ?? ""), bundle);
    assert.deepEqual(JSON.parse(requests[4]?.body ?? ""), { keepLatest: 3 });
  } finally {
    if (previousUrl === undefined) delete process.env.CAUSENTRA_URL;
    else process.env.CAUSENTRA_URL = previousUrl;
    await new Promise<void>((resolve, reject) =>
      server.close((error) => error === undefined ? resolve() : reject(error)),
    );
    await rm(directory, { recursive: true, force: true });
  }
});

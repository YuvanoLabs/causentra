import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { loadRuntimeConfig } from "../src/config.js";

test("loads file configuration and resolves its relative data path", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-config-"));
  await writeFile(
    join(directory, "causentra.config.json"),
    JSON.stringify({
      server: { host: "localhost", port: 5000, dataFile: "data/events.ndjson" },
    }),
    "utf8",
  );

  const config = await loadRuntimeConfig({ cwd: directory, env: {} });
  assert.equal(config.host, "localhost");
  assert.equal(config.port, 5000);
  assert.equal(config.dataFile, join(directory, "data/events.ndjson"));
  assert.equal(config.allowUnsafeNetwork, false);
  assert.equal(config.configFile, join(directory, "causentra.config.json"));
});

test("environment overrides file values deterministically", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-config-"));
  await writeFile(
    join(directory, "settings.json"),
    JSON.stringify({ server: { host: "localhost", port: 5000 } }),
    "utf8",
  );

  const config = await loadRuntimeConfig({
    cwd: directory,
    env: {
      CAUSENTRA_CONFIG: "settings.json",
      CAUSENTRA_HOST: "127.0.0.1",
      CAUSENTRA_PORT: "6000",
      CAUSENTRA_DATA_FILE: "override/events.ndjson",
      CAUSENTRA_ALLOW_UNSAFE_NETWORK: "true",
    },
  });
  assert.equal(config.host, "127.0.0.1");
  assert.equal(config.port, 6000);
  assert.equal(config.dataFile, join(directory, "override/events.ndjson"));
  assert.equal(config.allowUnsafeNetwork, true);
});

test("rejects malformed unsafe-network acknowledgement", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-config-"));
  await assert.rejects(
    loadRuntimeConfig({
      cwd: directory,
      env: { CAUSENTRA_ALLOW_UNSAFE_NETWORK: "yes" },
    }),
    /must be true or false/u,
  );
});

test("rejects malformed configuration instead of silently defaulting", async () => {
  const directory = await mkdtemp(join(tmpdir(), "causentra-config-"));
  await writeFile(
    join(directory, "causentra.config.json"),
    JSON.stringify({ server: { port: "not-a-port" } }),
    "utf8",
  );
  await assert.rejects(
    loadRuntimeConfig({ cwd: directory, env: {} }),
    /server\.port must be an integer/u,
  );
});

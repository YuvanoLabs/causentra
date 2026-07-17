#!/usr/bin/env node
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { CausentraRuntime, HttpBatchExporter } from "@causentra/sdk";
import { runLocalServer } from "@causentra/server";

export async function run(args: readonly string[]): Promise<number> {
  const [command = "help", argument, secondArgument] = args;
  switch (command) {
    case "serve":
      await runLocalServer();
      return 0;
    case "doctor":
      return doctor();
    case "demo":
      return demo();
    case "traces":
      return listTraces();
    case "trace":
      return showTrace(argument);
    case "export":
      return exportTrace(argument, secondArgument);
    case "import":
      return importTrace(argument);
    case "delete":
      return deleteTrace(argument);
    case "prune":
      return pruneTraces(argument);
    case "init":
      return initialize();
    case "help":
    case "--help":
    case "-h":
      printHelp();
      return 0;
    default:
      console.error(`Unknown command: ${command}`);
      printHelp();
      return 2;
  }
}

async function exportTrace(
  traceId: string | undefined,
  outputFile: string | undefined,
): Promise<number> {
  if (traceId === undefined) {
    console.error("Usage: causentra export <trace-id> [output-file]");
    return 2;
  }
  try {
    const bundle = await requestJson(`/api/traces/${encodeURIComponent(traceId)}/export`);
    const serialized = `${JSON.stringify(bundle, null, 2)}\n`;
    if (outputFile === undefined) console.log(serialized.trimEnd());
    else {
      await writeFile(outputFile, serialized, { encoding: "utf8", flag: "wx" });
      console.log(`✓ Exported trace to ${outputFile}`);
    }
    return 0;
  } catch (error) {
    console.error(message(error));
    return 1;
  }
}

async function importTrace(inputFile: string | undefined): Promise<number> {
  if (inputFile === undefined) {
    console.error("Usage: causentra import <bundle-file>");
    return 2;
  }
  try {
    const bundle = JSON.parse(await readFile(inputFile, "utf8")) as unknown;
    const result = await requestJson("/api/traces/import", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(bundle),
    });
    console.log(`✓ Imported ${String(result.accepted)} events`);
    return 0;
  } catch (error) {
    console.error(message(error));
    return 1;
  }
}

async function deleteTrace(traceId: string | undefined): Promise<number> {
  if (traceId === undefined) {
    console.error("Usage: causentra delete <trace-id>");
    return 2;
  }
  try {
    await requestJson(`/api/traces/${encodeURIComponent(traceId)}`, { method: "DELETE" });
    console.log(`✓ Deleted trace ${traceId}`);
    return 0;
  } catch (error) {
    console.error(message(error));
    return 1;
  }
}

async function pruneTraces(value: string | undefined): Promise<number> {
  if (value === undefined || !/^\d+$/u.test(value)) {
    console.error("Usage: causentra prune <keep-latest-count>");
    return 2;
  }
  try {
    const result = await requestJson("/api/retention/prune", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ keepLatest: Number(value) }),
    });
    console.log(`✓ Removed ${String(result.removed)} traces; ${String(result.remaining)} remain`);
    return 0;
  } catch (error) {
    console.error(message(error));
    return 1;
  }
}

async function doctor(): Promise<number> {
  const baseUrl = runtimeBaseUrl();
  try {
    const health = await requestJson("/health");
    console.log(`✓ runtime reachable at ${baseUrl}`);
    console.log(`✓ ${String(health.traces)} traces / ${String(health.events)} events`);
    console.log(`✓ Node.js ${process.version}`);
    return 0;
  } catch (error) {
    console.error(`✗ ${message(error)}`);
    console.error(`  Start the runtime with: npm run dev`);
    return 1;
  }
}

async function demo(): Promise<number> {
  const baseUrl = runtimeBaseUrl();
  const exporter = new HttpBatchExporter({
    endpoint: `${baseUrl}/v1/events`,
    batchSize: 10,
    onError: ({ error }) => console.error(`Exporter: ${message(error)}`),
  });
  const runtime = new CausentraRuntime({
    serviceName: "support-agent-demo",
    exporter,
  });

  console.log("Generating a support-agent execution…");
  await runtime.trace(
    "resolve-customer-question",
    async () => {
      await runtime.span(
        "classify-intent",
        "model",
        async () => delay(65),
        { model: "demo-model", "model.input_tokens": 42 },
      );
      runtime.record("route-selected", {
        attributes: { route: "account-status", token: "never-store-this" },
      });
      await runtime.span(
        "lookup-account",
        "tool",
        async () => delay(40),
        { "tool.system": "demo-crm", "tool.cached": false },
      );
      await runtime.span(
        "compose-response",
        "model",
        async () => delay(80),
        { model: "demo-model", "model.output_tokens": 67 },
      );
    },
    { "workflow.version": "1.0.0", environment: "local" },
  );

  if (!(await runtime.flush())) {
    console.error(`Could not deliver the demo trace to ${baseUrl}`);
    return 1;
  }
  console.log(`✓ Trace delivered. Open ${baseUrl}`);
  return 0;
}

async function listTraces(): Promise<number> {
  try {
    const payload = await requestJson("/api/traces?limit=50");
    console.log(JSON.stringify(payload, null, 2));
    return 0;
  } catch (error) {
    console.error(message(error));
    return 1;
  }
}

async function showTrace(traceId: string | undefined): Promise<number> {
  if (traceId === undefined) {
    console.error("Usage: causentra trace <trace-id>");
    return 2;
  }
  try {
    console.log(
      JSON.stringify(
        await requestJson(`/api/traces/${encodeURIComponent(traceId)}`),
        null,
        2,
      ),
    );
    return 0;
  } catch (error) {
    console.error(message(error));
    return 1;
  }
}

async function initialize(): Promise<number> {
  const baseUrl = runtimeBaseUrl();
  const config = {
    server: {
      host: "127.0.0.1",
      port: 4318,
      dataFile: ".causentra/events.ndjson",
      allowUnsafeNetwork: false,
    },
    sdk: {
      serviceName: "my-agent",
      endpoint: `${baseUrl}/v1/events`,
      capturePayloads: false,
    },
  };
  try {
    await writeFile(
      "causentra.config.json",
      `${JSON.stringify(config, null, 2)}\n`,
      { encoding: "utf8", flag: "wx" },
    );
    console.log("✓ Created causentra.config.json");
    return 0;
  } catch (error) {
    if (isAlreadyExists(error)) {
      console.error("causentra.config.json already exists; no changes made");
      return 1;
    }
    throw error;
  }
}

async function requestJson(
  path: string,
  init: RequestInit = {},
): Promise<Record<string, unknown>> {
  const response = await fetch(`${runtimeBaseUrl()}${path}`, {
    ...init,
    headers: { accept: "application/json", ...init.headers },
    signal: AbortSignal.timeout(3_000),
  });
  const payload = (await response.json()) as Record<string, unknown>;
  if (!response.ok) {
    const error = payload.error as { message?: string } | undefined;
    throw new Error(error?.message ?? `Request failed with ${response.status}`);
  }
  return payload;
}

function runtimeBaseUrl(): string {
  return (process.env.CAUSENTRA_URL ?? "http://127.0.0.1:4318").replace(
    /\/$/u,
    "",
  );
}

function printHelp(): void {
  console.log(`Causentra CLI

Usage: causentra <command>

Commands:
  serve             Start the local runtime and dashboard
  doctor            Check runtime connectivity
  demo              Generate a representative agent trace
  traces            Print recent trace summaries as JSON
  trace <trace-id>  Print a complete trace as JSON
  export <trace-id> [file]  Export a portable trace bundle
  import <file>     Import a portable trace bundle
  delete <trace-id> Delete one local trace
  prune <count>     Keep only the latest count traces
  init              Create a conservative local config
  help              Show this help

Environment:
  CAUSENTRA_URL        Runtime base URL (default http://127.0.0.1:4318)
  CAUSENTRA_CONFIG     Explicit JSON configuration file
  CAUSENTRA_HOST       Server bind host (default 127.0.0.1)
  CAUSENTRA_PORT       Server port (default 4318)
  CAUSENTRA_DATA_FILE  Local NDJSON path
  CAUSENTRA_ALLOW_UNSAFE_NETWORK  Explicit true to permit a non-loopback bind`);
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

function isAlreadyExists(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "EEXIST"
  );
}

const entry = process.argv[1];
if (entry !== undefined && pathToFileURL(resolve(entry)).href === import.meta.url) {
  process.exitCode = await run(process.argv.slice(2));
}

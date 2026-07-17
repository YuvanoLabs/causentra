import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { loadRuntimeConfig } from "./config.js";
import { FileTraceStore } from "./store.js";
import { startRuntimeServer } from "./server.js";

export async function runLocalServer(): Promise<void> {
  const { host, port, dataFile, configFile, allowUnsafeNetwork } = await loadRuntimeConfig();
  const store = await FileTraceStore.open(dataFile);
  const server = await startRuntimeServer({ host, port, store, allowUnsafeNetwork });
  console.log(`Causentra listening at ${server.url}`);
  console.log(`Trace data: ${dataFile}`);
  if (configFile !== undefined) console.log(`Configuration: ${configFile}`);

  for (const signal of ["SIGINT", "SIGTERM"] as const) {
    process.once(signal, () => {
      void server.close().finally(() => process.exit(0));
    });
  }
}

const entry = process.argv[1];
if (entry !== undefined && pathToFileURL(resolve(entry)).href === import.meta.url) {
  await runLocalServer();
}

export { isLoopbackHost, startRuntimeServer } from "./server.js";
export { FileTraceStore } from "./store.js";
export { loadRuntimeConfig } from "./config.js";
export { convertOtlpTraces, decodeOtlpProtobuf } from "./otlp.js";
export type { OtlpConversionResult } from "./otlp.js";
export type { LoadConfigOptions, LocalRuntimeConfig } from "./config.js";
export type { RunningRuntimeServer, RuntimeServerOptions } from "./server.js";
export type { TraceDetail, TraceFilters, TraceStore, TraceSummary } from "./store.js";

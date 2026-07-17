import { performance } from "node:perf_hooks";
import { CausentraRuntime, MemoryExporter } from "../dist/src/index.js";

const eventPairs = Number(process.env.CAUSENTRA_BENCHMARK_SPANS ?? "5000");
const exporter = new MemoryExporter();
const runtime = new CausentraRuntime({ serviceName: "benchmark", exporter });
const started = performance.now();

await runtime.trace("benchmark-trace", async () => {
  for (let index = 0; index < eventPairs; index += 1) {
    await runtime.span(`span-${index}`, "span", async () => undefined);
  }
});

const elapsedMs = performance.now() - started;
const perEventMs = elapsedMs / exporter.events.length;
console.log(JSON.stringify({ eventPairs, events: exporter.events.length, elapsedMs, perEventMs }));
if (perEventMs >= 5) {
  throw new Error(`SDK overhead budget exceeded: ${perEventMs.toFixed(3)} ms/event`);
}

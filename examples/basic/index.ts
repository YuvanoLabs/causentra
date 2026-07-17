import { CausentraRuntime, HttpBatchExporter } from "@causentra/sdk";

const runtime = new CausentraRuntime({
  serviceName: "example-agent",
  exporter: new HttpBatchExporter(),
});

await runtime.trace("answer-question", async () => {
  await runtime.span("search-knowledge", "tool", async () => {
    // Call your tool here. Arguments are not captured automatically.
  });
  await runtime.span("generate-answer", "model", async () => {
    // Call your model provider here.
  });
});

await runtime.shutdown();

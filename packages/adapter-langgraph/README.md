# @causentra/langgraph

Release line: `1.0.0` for Node.js 22+. This verified workspace package is not
yet listed in the public npm registry; see the [package catalog](../../docs/38-package-catalog.md)
for source and archive consumption.

Framework callback instrumentation for LangGraph and LangChain JavaScript.

```ts
import { HttpBatchExporter } from "@causentra/sdk";
import { createLangGraphInstrumentation } from "@causentra/langgraph";

const instrumentation = createLangGraphInstrumentation({
  serviceName: "research-graph",
  exporter: new HttpBatchExporter(),
  // Optional: runtime.currentContext() joins this graph to a shared trace.
  parentContext,
});

await graph.invoke(input, { callbacks: [instrumentation.handler] });
await instrumentation.flush();
```

Graph state, prompts, messages, tool arguments, outputs, and metadata are excluded by default.

The adapter passes the SDK conformance contract and is tested against a real compiled graph, including canonical parent-trace continuity.

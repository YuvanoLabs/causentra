# @causentra/opentelemetry

Converts redacted Causentra lifecycle events into real OpenTelemetry spans and optionally exports them over OTLP/HTTP protobuf using the official OpenTelemetry JavaScript SDK.

## Existing OpenTelemetry provider

```ts
import { trace } from "@opentelemetry/api";
import { CausentraRuntime } from "@causentra/sdk";
import { OpenTelemetryEventExporter } from "@causentra/opentelemetry";

const exporter = new OpenTelemetryEventExporter({
  tracer: trace.getTracer("my-agent"),
});
const runtime = new CausentraRuntime({ serviceName: "my-agent", exporter });
```

## Standalone OTLP/HTTP protobuf

```ts
import { CausentraRuntime } from "@causentra/sdk";
import { startCausentraRuntimeOtlp } from "@causentra/opentelemetry";

const otlp = startCausentraRuntimeOtlp({
  serviceName: "my-agent",
  endpoint: "http://127.0.0.1:4318/v1/traces",
});
const runtime = new CausentraRuntime({ serviceName: "my-agent", exporter: otlp.exporter });

// Run instrumented work, then flush and shut down explicitly.
await runtime.shutdown();
```

`startCausentraRuntimeOtlp` registers a global Node tracer provider. Call it once at application startup, before instrumented libraries load. Prefer an OpenTelemetry Collector in production. Causentra content-exclusion and redaction happen before this bridge receives events.

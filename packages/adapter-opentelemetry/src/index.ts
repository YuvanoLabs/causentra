import {
  ROOT_CONTEXT,
  SpanKind,
  SpanStatusCode,
  TraceFlags,
  trace,
  type Attributes,
  type Context,
  type Span,
  type Tracer,
} from "@opentelemetry/api";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-proto";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { BatchSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { NodeTracerProvider } from "@opentelemetry/sdk-trace-node";
import { ATTR_SERVICE_NAME } from "@opentelemetry/semantic-conventions";
import {
  OpenTelemetryProjector,
  type EventExporter,
  type RuntimeErrorContext,
  type RuntimeEvent,
} from "@causentra/sdk";

export interface OpenTelemetryEventExporterOptions {
  readonly tracer: Tracer;
  readonly forceFlush?: () => Promise<void>;
  readonly shutdown?: () => Promise<void>;
  readonly onError?: (context: RuntimeErrorContext) => void;
}

/**
 * Converts completed Causentra lifecycle pairs to real OpenTelemetry spans.
 * Runtime payloads are already redacted; custom point events become span events.
 */
export class OpenTelemetryEventExporter implements EventExporter {
  readonly #tracer: Tracer;
  readonly #forceFlush: () => Promise<void>;
  readonly #shutdown: (() => Promise<void>) | undefined;
  readonly #onError: (context: RuntimeErrorContext) => void;
  readonly #projector = new OpenTelemetryProjector();
  readonly #active = new Map<string, Span>();
  #closed = false;

  public constructor(options: OpenTelemetryEventExporterOptions) {
    this.#tracer = options.tracer;
    this.#forceFlush = options.forceFlush ?? (async () => undefined);
    this.#shutdown = options.shutdown;
    this.#onError = options.onError ?? (() => undefined);
  }

  public emit(event: RuntimeEvent): void {
    if (this.#closed) {
      this.#report(new Error("OpenTelemetry exporter is closed"), 1);
      return;
    }
    try {
      if (event.type.endsWith(".start")) {
        this.#projector.ingest(event);
        this.#start(event);
        return;
      }
      if (event.type.endsWith(".end")) {
        this.#end(event);
        return;
      }
      const span = this.#active.get(key(event.traceId, event.spanId));
      span?.addEvent(event.name, primitiveAttributes(event.attributes), new Date(event.timestamp));
    } catch (error) {
      this.#report(error, 1);
    }
  }

  public async flush(): Promise<boolean> {
    try {
      await this.#forceFlush();
      return true;
    } catch (error) {
      this.#report(error, 0);
      return false;
    }
  }

  public async shutdown(): Promise<void> {
    if (this.#closed) return;
    this.#closed = true;
    for (const span of this.#active.values()) {
      span.setStatus({ code: SpanStatusCode.ERROR });
      span.end();
    }
    this.#active.clear();
    if (this.#shutdown !== undefined) await this.#shutdown();
    else await this.#forceFlush();
  }

  #start(event: RuntimeEvent): void {
    const parent = this.#parentContext(event);
    const span = this.#tracer.startSpan(
      event.name,
      {
        kind: SpanKind.INTERNAL,
        startTime: new Date(event.timestamp),
        attributes: {
          "causentra.trace.id": event.traceId,
          "causentra.span.id": event.spanId,
          "causentra.event.type": event.type,
        },
      },
      parent,
    );
    this.#active.set(key(event.traceId, event.spanId), span);
  }

  #end(event: RuntimeEvent): void {
    const projection = this.#projector.ingest(event);
    if (projection === undefined) return;
    const spanKey = key(event.traceId, event.spanId);
    const existing = this.#active.get(spanKey);
    const span = existing ?? this.#tracer.startSpan(event.name, {
      kind: SpanKind.INTERNAL,
      startTime: Number(BigInt(projection.startTimeUnixNano) / 1_000_000n),
    }, this.#parentContext(event));
    this.#active.delete(spanKey);
    span.setAttributes(mutableAttributes(projection.attributes));
    span.setStatus({
      code: projection.status === "ERROR"
        ? SpanStatusCode.ERROR
        : projection.status === "OK"
          ? SpanStatusCode.OK
          : SpanStatusCode.UNSET,
    });
    span.end(new Date(event.timestamp));
  }

  #parentContext(event: RuntimeEvent): Context {
    if (event.parentSpanId === undefined) return ROOT_CONTEXT;
    const activeParent = this.#active.get(key(event.traceId, event.parentSpanId));
    if (activeParent !== undefined) return trace.setSpan(ROOT_CONTEXT, activeParent);
    return trace.setSpanContext(ROOT_CONTEXT, {
      traceId: event.traceId,
      spanId: event.parentSpanId.slice(0, 16),
      traceFlags: TraceFlags.SAMPLED,
      isRemote: true,
    });
  }

  #report(error: unknown, droppedEvents: number): void {
    try {
      this.#onError({ operation: "export", error, droppedEvents });
    } catch {
      // Telemetry diagnostics cannot be trusted to preserve application behavior.
    }
  }
}

export interface CausentraRuntimeOtlpOptions {
  readonly serviceName: string;
  /** Complete OTLP/HTTP protobuf traces endpoint, normally ending `/v1/traces`. */
  readonly endpoint: string;
  readonly headers?: Readonly<Record<string, string>>;
  readonly timeoutMillis?: number;
  readonly onError?: (context: RuntimeErrorContext) => void;
}

export interface RunningCausentraRuntimeOtlp {
  readonly exporter: OpenTelemetryEventExporter;
  shutdown(): Promise<void>;
}

/** Registers an official Node OTel provider and OTLP/HTTP protobuf exporter. */
export function startCausentraRuntimeOtlp(
  options: CausentraRuntimeOtlpOptions,
): RunningCausentraRuntimeOtlp {
  if (options.serviceName.trim().length === 0) throw new TypeError("serviceName is required");
  const endpoint = new URL(options.endpoint);
  if (!new Set(["http:", "https:"]).has(endpoint.protocol)) {
    throw new TypeError("endpoint must use http or https");
  }
  const otlp = new OTLPTraceExporter({
    url: endpoint.toString(),
    ...(options.headers === undefined ? {} : { headers: { ...options.headers } }),
    ...(options.timeoutMillis === undefined ? {} : { timeoutMillis: options.timeoutMillis }),
  });
  const provider = new NodeTracerProvider({
    resource: resourceFromAttributes({ [ATTR_SERVICE_NAME]: options.serviceName }),
    spanProcessors: [new BatchSpanProcessor(otlp)],
  });
  provider.register();
  const exporter = new OpenTelemetryEventExporter({
    tracer: provider.getTracer("causentra", "0.0.1"),
    forceFlush: () => provider.forceFlush(),
    shutdown: () => provider.shutdown(),
    ...(options.onError === undefined ? {} : { onError: options.onError }),
  });
  return { exporter, shutdown: () => exporter.shutdown() };
}

function key(traceId: string, spanId: string): string {
  return `${traceId}:${spanId}`;
}

function primitiveAttributes(
  attributes: RuntimeEvent["attributes"],
): Record<string, string | number | boolean> {
  return Object.fromEntries(
    Object.entries(attributes).map(([name, value]) => [
      name,
      typeof value === "string" || typeof value === "number" || typeof value === "boolean"
        ? value
        : JSON.stringify(value),
    ]),
  );
}

function mutableAttributes(
  attributes: Readonly<Record<string, string | number | boolean | readonly string[] | readonly number[] | readonly boolean[]>>,
): Attributes {
  return Object.fromEntries(
    Object.entries(attributes).map(([name, value]) => [
      name,
      Array.isArray(value) ? [...value] : value,
    ]),
  ) as Attributes;
}

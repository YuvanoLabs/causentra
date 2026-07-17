import type { EventAttributes, JsonValue, RuntimeEvent } from "./types.js";

export type OpenTelemetryAttributeValue =
  | string
  | number
  | boolean
  | readonly string[]
  | readonly number[]
  | readonly boolean[];

/** Dependency-free intermediate representation for constructing OTel spans. */
export interface OpenTelemetrySpanProjection {
  readonly traceId: string;
  /** OpenTelemetry span identifiers are 8 bytes represented as 16 hex characters. */
  readonly spanId: string;
  readonly parentSpanId?: string;
  readonly name: string;
  readonly kind: "INTERNAL";
  readonly startTimeUnixNano: string;
  readonly endTimeUnixNano: string;
  readonly status: "UNSET" | "OK" | "ERROR";
  /** Resource metadata supplied separately when constructing an OTel Resource. */
  readonly resourceAttributes: Readonly<{ "service.name": string }>;
  readonly attributes: Readonly<Record<string, OpenTelemetryAttributeValue>>;
}

/**
 * Aggregates lifecycle event pairs into portable OpenTelemetry span records.
 * It intentionally performs no network export and introduces no OTel runtime
 * dependency; collectors can translate these records to their chosen SDK.
 */
export class OpenTelemetryProjector {
  readonly #starts = new Map<string, RuntimeEvent>();

  /** Consumes one ordered runtime event and returns a completed span when ready. */
  public ingest(event: RuntimeEvent): OpenTelemetrySpanProjection | undefined {
    if (isStart(event.type)) {
      this.#starts.set(key(event), event);
      return undefined;
    }
    if (!isEnd(event.type)) return undefined;
    const start = this.#starts.get(key(event));
    this.#starts.delete(key(event));
    const startMs = start === undefined
      ? Date.parse(event.timestamp) - (event.durationMs ?? 0)
      : Date.parse(start.timestamp);
    const endMs = Date.parse(event.timestamp);
    const combinedAttributes = {
      ...(start?.attributes ?? {}),
      ...event.attributes,
    };
    const attributes = {
      "causentra.schema.version": event.schemaVersion,
      "causentra.event.type": event.type,
      ...semanticAttributes({ ...event, attributes: combinedAttributes }),
      ...otelAttributes(combinedAttributes),
    };
    return {
      traceId: event.traceId,
      spanId: toOpenTelemetrySpanId(event.spanId),
      ...(event.parentSpanId === undefined
        ? {}
        : { parentSpanId: toOpenTelemetrySpanId(event.parentSpanId) }),
      name: event.name,
      kind: "INTERNAL",
      startTimeUnixNano: millisecondsToNanoseconds(startMs),
      endTimeUnixNano: millisecondsToNanoseconds(endMs),
      status: event.status === "error" ? "ERROR" : event.status === "ok" ? "OK" : "UNSET",
      resourceAttributes: { "service.name": event.serviceName },
      attributes,
    };
  }
}

function semanticAttributes(
  event: RuntimeEvent,
): Readonly<Record<string, OpenTelemetryAttributeValue>> {
  const family = event.type.split(".", 1)[0];
  if (family === "trace") {
    return {
      "gen_ai.operation.name": "invoke_workflow",
      "gen_ai.workflow.name": event.name,
    };
  }
  if (family === "agent") {
    return {
      "gen_ai.operation.name": "invoke_agent",
      "gen_ai.agent.name": event.name,
    };
  }
  if (family === "tool") {
    return {
      "gen_ai.operation.name": "execute_tool",
      "gen_ai.tool.name": event.name,
    };
  }
  if (family === "model") {
    return {
      "gen_ai.operation.name": "chat",
      ...(typeof event.attributes.model === "string"
        ? { "gen_ai.request.model": event.attributes.model }
        : {}),
    };
  }
  return {};
}

function otelAttributes(
  attributes: EventAttributes,
): Readonly<Record<string, OpenTelemetryAttributeValue>> {
  return Object.fromEntries(
    Object.entries(attributes).map(([name, value]) => [name, otelValue(value)]),
  );
}

function otelValue(value: JsonValue): OpenTelemetryAttributeValue {
  if (value === null) return "null";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  if (Array.isArray(value)) {
    if (value.every((item): item is string => typeof item === "string")) return value;
    if (value.every((item): item is number => typeof item === "number")) return value;
    if (value.every((item): item is boolean => typeof item === "boolean")) return value;
  }
  return JSON.stringify(value);
}

function key(event: RuntimeEvent): string {
  return `${event.traceId}:${event.spanId}`;
}

function isStart(type: string): boolean {
  return type.endsWith(".start");
}

function isEnd(type: string): boolean {
  return type.endsWith(".end");
}

function millisecondsToNanoseconds(milliseconds: number): string {
  return (BigInt(Math.round(milliseconds)) * 1_000_000n).toString();
}

function toOpenTelemetrySpanId(runtimeSpanId: string): string {
  return runtimeSpanId.slice(0, 16);
}

import { createHash } from "node:crypto";
import { parse } from "protobufjs";
import {
  SCHEMA_VERSION,
  defaultRedactor,
  normalizeGenAiProviderName,
  validateEvent,
  type EventAttributes,
  type EventStatus,
  type EventType,
  type JsonValue,
  type RuntimeEvent,
} from "@causentra/sdk";

const TRACE_ID = /^[0-9a-f]{32}$/iu;
const SPAN_ID = /^[0-9a-f]{16}$/iu;
const OMITTED_CONTENT_ATTRIBUTES = new Set([
  "exception.message",
  "error.message",
  "gen_ai.input.messages",
  "gen_ai.output.messages",
  "gen_ai.retrieval.documents",
  "gen_ai.retrieval.query.text",
  "gen_ai.system_instructions",
  "gen_ai.tool.call.arguments",
  "gen_ai.tool.call.result",
  "gen_ai.tool.definitions",
  "gen_ai.evaluation.explanation",
  "input.value",
  "output.value",
  "llm.prompts",
  "llm.completions",
  "llm.input_messages",
  "llm.output_messages",
  "tool.parameters",
  "tool.result",
]);
const SENSITIVE_KEY = /(?:^|[._-])(authorization|api[_-]?key|password|secret|cookie|token)(?:$|[._-])/iu;

export interface OtlpConversionResult {
  readonly events: readonly RuntimeEvent[];
  readonly rejectedSpans: number;
  readonly errorMessage?: string;
}

interface OtlpSpanRecord {
  readonly resource: Record<string, JsonValue>;
  readonly scope: Record<string, unknown>;
  readonly span: Record<string, unknown>;
}

const proto = parse(`
syntax = "proto3";
package opentelemetry.proto.collector.trace.v1;
message ExportTraceServiceRequest { repeated ResourceSpans resource_spans = 1; }
message ExportTraceServiceResponse { ExportTracePartialSuccess partial_success = 1; }
message ExportTracePartialSuccess { int64 rejected_spans = 1; string error_message = 2; }
message ResourceSpans { Resource resource = 1; repeated ScopeSpans scope_spans = 2; string schema_url = 3; }
message Resource { repeated KeyValue attributes = 1; uint32 dropped_attributes_count = 2; }
message ScopeSpans { InstrumentationScope scope = 1; repeated Span spans = 2; string schema_url = 3; }
message InstrumentationScope { string name = 1; string version = 2; repeated KeyValue attributes = 3; uint32 dropped_attributes_count = 4; }
message Span {
  bytes trace_id = 1; bytes span_id = 2; string trace_state = 3; bytes parent_span_id = 4;
  string name = 5; int32 kind = 6; fixed64 start_time_unix_nano = 7;
  fixed64 end_time_unix_nano = 8; repeated KeyValue attributes = 9;
  uint32 dropped_attributes_count = 10; repeated Event events = 11;
  uint32 dropped_events_count = 12; repeated Link links = 13;
  uint32 dropped_links_count = 14; Status status = 15; fixed32 flags = 16;
}
message Event { fixed64 time_unix_nano = 1; string name = 2; repeated KeyValue attributes = 3; uint32 dropped_attributes_count = 4; }
message Link { bytes trace_id = 1; bytes span_id = 2; string trace_state = 3; repeated KeyValue attributes = 4; uint32 dropped_attributes_count = 5; fixed32 flags = 6; }
message Status { string message = 2; int32 code = 3; }
message KeyValue { string key = 1; AnyValue value = 2; }
message AnyValue { oneof value { string string_value = 1; bool bool_value = 2; int64 int_value = 3; double double_value = 4; ArrayValue array_value = 5; KeyValueList kvlist_value = 6; bytes bytes_value = 7; } }
message ArrayValue { repeated AnyValue values = 1; }
message KeyValueList { repeated KeyValue values = 1; }
`, { keepCase: false }).root;

const requestType = proto.lookupType(
  "opentelemetry.proto.collector.trace.v1.ExportTraceServiceRequest",
);
const responseType = proto.lookupType(
  "opentelemetry.proto.collector.trace.v1.ExportTraceServiceResponse",
);

/** Decodes the stable OTLP/HTTP protobuf request into its JSON-equivalent shape. */
export function decodeOtlpProtobuf(body: Uint8Array): unknown {
  return requestType.toObject(requestType.decode(body), {
    longs: String,
    bytes: Uint8Array,
    enums: Number,
    defaults: false,
    arrays: true,
    objects: true,
  });
}

/** Encodes a spec-compatible empty or partial-success trace response. */
export function encodeOtlpProtobufResponse(
  rejectedSpans: number,
  errorMessage?: string,
): Uint8Array {
  const value = rejectedSpans === 0
    ? {}
    : {
        partialSuccess: {
          rejectedSpans: String(rejectedSpans),
          errorMessage: errorMessage ?? "Rejected invalid spans",
        },
      };
  return responseType.encode(responseType.create(value)).finish();
}

/** Converts OTLP JSON/protobuf object data to privacy-safe RuntimeEvent pairs. */
export function convertOtlpTraces(value: unknown): OtlpConversionResult {
  if (!isRecord(value) || !Array.isArray(value.resourceSpans)) {
    return { events: [], rejectedSpans: 1, errorMessage: "resourceSpans must be an array" };
  }
  const records: OtlpSpanRecord[] = [];
  let rejectedSpans = 0;
  for (const resourceSpans of value.resourceSpans) {
    if (!isRecord(resourceSpans)) {
      rejectedSpans += 1;
      continue;
    }
    const resource = attributes(isRecord(resourceSpans.resource) ? resourceSpans.resource.attributes : undefined);
    const scopeSpans = Array.isArray(resourceSpans.scopeSpans) ? resourceSpans.scopeSpans : [];
    for (const group of scopeSpans) {
      if (!isRecord(group)) {
        rejectedSpans += 1;
        continue;
      }
      const scope = isRecord(group.scope) ? group.scope : {};
      for (const span of Array.isArray(group.spans) ? group.spans : []) {
        if (isRecord(span)) records.push({ resource, scope, span });
        else rejectedSpans += 1;
      }
    }
  }

  records.sort((left, right) => {
    const leftTime = nanos(left.span.startTimeUnixNano);
    const rightTime = nanos(right.span.startTimeUnixNano);
    return leftTime < rightTime ? -1 : leftTime > rightTime ? 1 : 0;
  });
  const sequences = new Map<string, number>();
  const events: RuntimeEvent[] = [];
  for (const record of records) {
    try {
      const converted = spanEvents(record, sequences);
      events.push(...converted);
    } catch {
      rejectedSpans += 1;
    }
  }
  return {
    events,
    rejectedSpans,
    ...(rejectedSpans === 0 ? {} : { errorMessage: "Invalid or unsupported spans were rejected" }),
  };
}

function spanEvents(
  record: OtlpSpanRecord,
  sequences: Map<string, number>,
): readonly [RuntimeEvent, RuntimeEvent] {
  const span = record.span;
  const traceId = hexId(span.traceId, TRACE_ID, "traceId");
  const spanId = hexId(span.spanId, SPAN_ID, "spanId");
  const parentSpanId = optionalHexId(span.parentSpanId, SPAN_ID);
  const startNanos = nanos(span.startTimeUnixNano);
  const endNanos = nanos(span.endTimeUnixNano);
  if (startNanos <= 0n || endNanos < startNanos) throw new TypeError("invalid span time");
  const spanAttributes = normalizeProviderAttributes(attributes(span.attributes));
  const resourceService = record.resource["service.name"];
  const scopeName = typeof record.scope.name === "string" ? record.scope.name : undefined;
  const serviceName = text(
    typeof resourceService === "string" ? resourceService : scopeName ?? "otel-service",
    256,
  );
  const name = text(span.name, 256);
  const root = parentSpanId === undefined;
  const family = operationFamily(spanAttributes);
  const startType: EventType = root ? "trace.start" : `${family}.start`;
  const endType: EventType = root ? "trace.end" : `${family}.end`;
  const shared = defaultRedactor({
    ...spanAttributes,
    "telemetry.source": "otlp",
    ...(typeof record.scope.name === "string" ? { "otel.scope.name": record.scope.name } : {}),
    ...(typeof record.scope.version === "string" ? { "otel.scope.version": record.scope.version } : {}),
    ...(typeof span.kind === "number" ? { "otel.span.kind": span.kind } : {}),
  });
  const status = spanStatus(span.status);
  const session = spanAttributes["gen_ai.conversation.id"];
  const common = {
    schemaVersion: SCHEMA_VERSION,
    traceId,
    spanId,
    ...(parentSpanId === undefined ? {} : { parentSpanId }),
    ...(typeof session === "string" ? { sessionId: hash("session", session) } : {}),
    name,
    serviceName,
    attributes: shared,
  } as const;
  const start: RuntimeEvent = {
    ...common,
    eventId: hash("otlp-start", `${traceId}:${spanId}:${String(startNanos)}`),
    sequence: nextSequence(sequences, traceId),
    timestamp: timestamp(startNanos),
    type: startType,
    status: "unset",
  };
  const end: RuntimeEvent = {
    ...common,
    eventId: hash("otlp-end", `${traceId}:${spanId}:${String(endNanos)}`),
    sequence: nextSequence(sequences, traceId),
    timestamp: timestamp(endNanos),
    type: endType,
    status,
    durationMs: Number(endNanos - startNanos) / 1_000_000,
  };
  validateEvent(start);
  validateEvent(end);
  return [start, end];
}

function operationFamily(attributesValue: EventAttributes): "agent" | "model" | "tool" | "workflow" | "span" {
  const operation = attributesValue["gen_ai.operation.name"];
  if (operation === "invoke_agent") return "agent";
  if (operation === "invoke_workflow") return "workflow";
  if (operation === "execute_tool") return "tool";
  if (["chat", "text_completion", "generate_content", "embeddings"].includes(String(operation))) {
    return "model";
  }
  const kind = String(
    attributesValue["openinference.span.kind"]
      ?? attributesValue["langsmith.span.kind"]
      ?? "",
  ).toLowerCase();
  if (kind === "agent") return "agent";
  if (["llm", "embedding"].includes(kind)) return "model";
  if (kind === "tool") return "tool";
  if (["chain", "workflow"].includes(kind)) return "workflow";
  return "span";
}

function attributes(value: unknown): EventAttributes {
  if (!Array.isArray(value)) return {};
  const result: EventAttributes = {};
  for (const entry of value) {
    if (!isRecord(entry) || typeof entry.key !== "string") continue;
    const key = entry.key.slice(0, 256);
    if (OMITTED_CONTENT_ATTRIBUTES.has(key.toLowerCase()) || SENSITIVE_KEY.test(key)) continue;
    const converted = anyValue(entry.value, 0);
    if (converted !== undefined) result[key] = converted;
  }
  return result;
}

function normalizeProviderAttributes(value: EventAttributes): EventAttributes {
  const current = value["gen_ai.provider.name"];
  const legacy = value["gen_ai.system"];
  const provider = typeof current === "string"
    ? current
    : typeof legacy === "string"
      ? legacy
      : undefined;
  if (provider === undefined) return value;
  return { ...value, "gen_ai.provider.name": normalizeGenAiProviderName(provider) };
}

function anyValue(value: unknown, depth: number): JsonValue | undefined {
  if (!isRecord(value) || depth > 8) return undefined;
  if (typeof value.stringValue === "string") return value.stringValue.slice(0, 16_384);
  if (typeof value.boolValue === "boolean") return value.boolValue;
  if (typeof value.doubleValue === "number" && Number.isFinite(value.doubleValue)) return value.doubleValue;
  if (typeof value.intValue === "number" && Number.isSafeInteger(value.intValue)) return value.intValue;
  if (typeof value.intValue === "string" && /^-?\d+$/u.test(value.intValue)) {
    const integer = Number(value.intValue);
    return Number.isSafeInteger(integer) ? integer : value.intValue;
  }
  if (isRecord(value.arrayValue) && Array.isArray(value.arrayValue.values)) {
    return value.arrayValue.values
      .map((item) => anyValue(item, depth + 1))
      .filter((item): item is JsonValue => item !== undefined);
  }
  if (isRecord(value.kvlistValue) && Array.isArray(value.kvlistValue.values)) {
    return attributes(value.kvlistValue.values);
  }
  return undefined;
}

function spanStatus(value: unknown): EventStatus {
  const code = isRecord(value) ? value.code : undefined;
  return code === 2 ? "error" : code === 1 ? "ok" : "unset";
}

function hexId(value: unknown, pattern: RegExp, field: string): string {
  const candidate = byteHex(value);
  if (!pattern.test(candidate)) throw new TypeError(`${field} is invalid`);
  return candidate.toLowerCase();
}

function optionalHexId(value: unknown, pattern: RegExp): string | undefined {
  const candidate = byteHex(value);
  return candidate.length === 0 ? undefined : hexId(candidate, pattern, "parentSpanId");
}

function byteHex(value: unknown): string {
  if (typeof value === "string") return value;
  if (value instanceof Uint8Array) return Buffer.from(value).toString("hex");
  return "";
}

function nanos(value: unknown): bigint {
  if (typeof value === "string" && /^\d+$/u.test(value)) return BigInt(value);
  if (typeof value === "number" && Number.isSafeInteger(value) && value >= 0) return BigInt(value);
  return 0n;
}

function timestamp(value: bigint): string {
  return new Date(Number(value / 1_000_000n)).toISOString();
}

function text(value: unknown, maximum: number): string {
  if (typeof value !== "string" || value.trim().length === 0) throw new TypeError("text is required");
  return value.slice(0, maximum);
}

function hash(namespace: string, value: string): string {
  return createHash("sha256").update(namespace).update("\0").update(value).digest("hex").slice(0, 32);
}

function nextSequence(sequences: Map<string, number>, traceId: string): number {
  const current = sequences.get(traceId) ?? 0;
  sequences.set(traceId, current + 1);
  return current;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

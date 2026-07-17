/** Wire-format version understood by this SDK release. */
export const SCHEMA_VERSION = "1.0" as const;

/** A primitive value accepted in event attributes. */
export type JsonPrimitive = string | number | boolean | null;
/** JSON-compatible data accepted in event attributes. */
export type JsonValue =
  | JsonPrimitive
  | JsonValue[]
  | { [key: string]: JsonValue };
/** User-supplied structured metadata attached to an event. */
export type EventAttributes = Record<string, JsonValue>;

/** Built-in lifecycle types. Readers also preserve namespaced extension types. */
export const EVENT_TYPES = [
  "trace.start",
  "trace.end",
  "span.start",
  "span.end",
  "agent.start",
  "agent.end",
  "model.start",
  "model.end",
  "tool.start",
  "tool.end",
  "error",
  "custom",
] as const;

/** A built-in type or a namespaced extension such as `evaluation.score`. */
export type EventType = (typeof EVENT_TYPES)[number] | `${string}.${string}`;
/** Outcome known at the time an event is emitted. */
export type EventStatus = "unset" | "ok" | "error";

/**
 * Stable, framework-neutral wire envelope persisted and transported by Agent
 * Runtime. Payload bodies are not captured unless explicitly placed in
 * `attributes` by the application.
 */
export interface RuntimeEvent {
  /** Contract version, independent from the npm package version. */
  readonly schemaVersion: typeof SCHEMA_VERSION;
  /** Idempotency key for at-least-once delivery. */
  readonly eventId: string;
  /** Correlates every event in one execution. */
  readonly traceId: string;
  /** Correlates start/end events for one operation. */
  readonly spanId: string;
  /** Connects this operation to its direct parent. */
  readonly parentSpanId?: string;
  /** Optional correlation across multiple traces. */
  readonly sessionId?: string;
  /** Process-local monotonic order within a trace. */
  readonly sequence: number;
  /** UTC ISO-8601 creation time. */
  readonly timestamp: string;
  readonly type: EventType;
  readonly name: string;
  readonly status: EventStatus;
  /** Completed-operation duration measured with a monotonic clock. */
  readonly durationMs?: number;
  readonly serviceName: string;
  /** Redacted JSON metadata, limited to 64 KiB by the v1 validator. */
  readonly attributes: EventAttributes;
}

/** Correlation identifiers for the currently executing trace/span. */
export interface TraceContext {
  readonly traceId: string;
  readonly spanId: string;
  readonly parentSpanId?: string;
  readonly sessionId?: string;
}

/** Minimal exporter contract implemented by local and third-party transports. */
export interface EventExporter {
  /** Accepts one already-redacted event without blocking the application. */
  emit(event: RuntimeEvent): void;
  /** Attempts delivery of all currently queued events. */
  flush(): Promise<boolean>;
  /** Flushes and releases exporter resources when supported. */
  shutdown?(): Promise<void>;
}

/** Transforms a cloned attribute object before validation and export. */
export type Redactor = (attributes: EventAttributes) => EventAttributes;

/** Diagnostic delivered to instrumentation error callbacks. */
export interface RuntimeErrorContext {
  readonly operation: "export" | "redact" | "adapter";
  readonly error: unknown;
  readonly droppedEvents: number;
}

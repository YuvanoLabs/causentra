import {
  EVENT_TYPES,
  SCHEMA_VERSION,
  type EventAttributes,
  type JsonValue,
  type RuntimeEvent,
} from "./types.js";

const ID_PATTERN = /^[0-9a-f]{32}$/;
const SPAN_ID_PATTERN = /^(?:[0-9a-f]{16}|[0-9a-f]{32})$/;
const EVENT_TYPE_PATTERN = /^[a-z][a-z0-9_-]{0,63}\.[a-z][a-z0-9_.-]{0,63}$/;
const BUILTIN_EVENT_TYPES = new Set<string>(EVENT_TYPES);
const MAX_NAME_LENGTH = 256;
/** Maximum UTF-8 encoded attribute payload accepted by schema v1. */
export const MAX_ATTRIBUTES_BYTES = 64 * 1024;

/** Structured validation error suitable for machine-readable API responses. */
export class EventValidationError extends Error {
  public constructor(
    message: string,
    public readonly field: string,
  ) {
    super(message);
    this.name = "EventValidationError";
  }
}

/** Returns whether a value is finite JSON data within the depth limit. */
export function isJsonValue(value: unknown, depth = 0): value is JsonValue {
  if (depth > 12) return false;
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return true;
  }
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) {
    return value.every((item) => isJsonValue(item, depth + 1));
  }
  if (typeof value === "object") {
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) return false;
    return Object.values(value).every((item) => isJsonValue(item, depth + 1));
  }
  return false;
}

/** Validates JSON compatibility, depth, and encoded attribute size. */
export function validateAttributes(
  value: unknown,
): asserts value is EventAttributes {
  if (!isJsonValue(value) || Array.isArray(value) || value === null) {
    throw new EventValidationError(
      "attributes must be a JSON object with a maximum depth of 12",
      "attributes",
    );
  }
  if (Buffer.byteLength(JSON.stringify(value), "utf8") > MAX_ATTRIBUTES_BYTES) {
    throw new EventValidationError(
      `attributes must not exceed ${MAX_ATTRIBUTES_BYTES} bytes`,
      "attributes",
    );
  }
}

function requireString(
  value: unknown,
  field: string,
  maximum = MAX_NAME_LENGTH,
): asserts value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > maximum) {
    throw new EventValidationError(
      `${field} must be a non-empty string up to ${maximum} characters`,
      field,
    );
  }
}

function requireId(value: unknown, field: string): asserts value is string {
  if (typeof value !== "string" || !ID_PATTERN.test(value)) {
    throw new EventValidationError(`${field} must be a 32-character hex ID`, field);
  }
}

function requireSpanId(value: unknown, field: string): asserts value is string {
  if (typeof value !== "string" || !SPAN_ID_PATTERN.test(value)) {
    throw new EventValidationError(
      `${field} must be a 16- or legacy 32-character hex ID`,
      field,
    );
  }
}

/** Validates an untrusted value as a complete schema-v1 runtime event. */
export function validateEvent(value: unknown): asserts value is RuntimeEvent {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new EventValidationError("event must be an object", "event");
  }
  const event = value as Record<string, unknown>;
  if (event.schemaVersion !== SCHEMA_VERSION) {
    throw new EventValidationError(
      `schemaVersion must be ${SCHEMA_VERSION}`,
      "schemaVersion",
    );
  }
  requireId(event.eventId, "eventId");
  requireId(event.traceId, "traceId");
  requireSpanId(event.spanId, "spanId");
  if (event.parentSpanId !== undefined) requireSpanId(event.parentSpanId, "parentSpanId");
  if (event.sessionId !== undefined) requireId(event.sessionId, "sessionId");
  if (!Number.isSafeInteger(event.sequence) || (event.sequence as number) < 0) {
    throw new EventValidationError("sequence must be a non-negative integer", "sequence");
  }
  requireString(event.timestamp, "timestamp", 40);
  if (Number.isNaN(Date.parse(event.timestamp as string))) {
    throw new EventValidationError("timestamp must be ISO-8601", "timestamp");
  }
  requireString(event.type, "type", 128);
  if (
    !BUILTIN_EVENT_TYPES.has(event.type as string) &&
    !EVENT_TYPE_PATTERN.test(event.type as string)
  ) {
    throw new EventValidationError(
      "type must be a lowercase, dot-namespaced lifecycle name",
      "type",
    );
  }
  requireString(event.name, "name");
  requireString(event.serviceName, "serviceName");
  if (!new Set(["unset", "ok", "error"]).has(event.status as string)) {
    throw new EventValidationError("status is invalid", "status");
  }
  if (
    event.durationMs !== undefined &&
    (typeof event.durationMs !== "number" ||
      !Number.isFinite(event.durationMs) ||
      event.durationMs < 0)
  ) {
    throw new EventValidationError("durationMs must be non-negative", "durationMs");
  }
  validateAttributes(event.attributes);
}

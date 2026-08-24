import canonicalize from "canonicalize";
import type { JsonValue } from "./types.js";

/**
 * Canonicalizes the SDK JSON domain using RFC 8785 JCS and returns UTF-8
 * bytes. This is optional signing infrastructure; it does not sign or verify.
 */
export function canonicalizeJson(value: JsonValue): Uint8Array {
  validateJsonValue(value);
  const serialized = canonicalize(value);
  if (serialized === undefined) {
    throw new TypeError("value cannot be represented in the JSON domain");
  }
  return new TextEncoder().encode(serialized);
}

function validateJsonValue(value: unknown): asserts value is JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") return;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("JSON values cannot contain non-finite numbers");
    if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
      throw new RangeError("integer is outside the RFC 8785 interoperable safe range");
    }
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) validateJsonValue(item);
    return;
  }
  if (typeof value === "object") {
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) {
      throw new TypeError("value must be a plain JSON object");
    }
    for (const [key, item] of Object.entries(value)) {
      if (typeof key !== "string") throw new TypeError("JSON object keys must be strings");
      validateJsonValue(item);
    }
    return;
  }
  throw new TypeError("value must be a Causentra JSON value");
}

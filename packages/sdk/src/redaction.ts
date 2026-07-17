import type { EventAttributes, JsonValue, Redactor } from "./types.js";

const DEFAULT_SENSITIVE_KEYS = [
  "authorization",
  "api_key",
  "apikey",
  "password",
  "secret",
  "token",
  "cookie",
];

/**
 * Creates a recursive, case-insensitive key redactor. Input is cloned before
 * transformation so application-owned attribute objects are never mutated.
 */
export function createRedactor(
  sensitiveKeys: readonly string[] = DEFAULT_SENSITIVE_KEYS,
  replacement = "[REDACTED]",
): Redactor {
  const keys = new Set(sensitiveKeys.map((key) => key.toLowerCase()));

  const redact = (value: JsonValue): JsonValue => {
    if (Array.isArray(value)) return value.map(redact);
    if (typeof value !== "object" || value === null) return value;
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [
        key,
        keys.has(key.toLowerCase()) ? replacement : redact(child),
      ]),
    );
  };

  return (attributes: EventAttributes): EventAttributes =>
    redact(structuredClone(attributes)) as EventAttributes;
}

/** Conservative default covering common credential and session key names. */
export const defaultRedactor = createRedactor();

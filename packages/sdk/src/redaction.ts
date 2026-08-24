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

const EMAIL = /(?<![A-Za-z0-9._%+-])[A-Za-z0-9_%+-]+(?:\.[A-Za-z0-9_%+-]+)*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![A-Za-z0-9-])/g;
const CARD = /(?<![A-Za-z0-9])(?:\d[ -]?){12,18}\d(?![A-Za-z0-9])/g;
const PAN = /(?<![A-Za-z0-9])[A-Z]{5}\d{4}[A-Z](?![A-Za-z0-9])/gi;

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

export interface PolicyRedactorOptions {
  readonly replacement?: string;
  readonly redactEmails?: boolean;
  readonly redactCards?: boolean;
  readonly redactPans?: boolean;
  readonly baseRedactor?: Redactor;
}

/**
 * Creates an opt-in value policy composed with the existing key redactor.
 * Detection is intentionally bounded to email, Luhn-valid card-like, and
 * Indian PAN formats; it is not a generic name, health, or DLP detector.
 */
export function createPolicyRedactor(options: PolicyRedactorOptions = {}): Redactor {
  const replacement = options.replacement ?? "[REDACTED]";
  if (replacement.length === 0) throw new TypeError("replacement must not be empty");
  const baseRedactor = options.baseRedactor ?? defaultRedactor;
  const redactEmails = options.redactEmails ?? true;
  const redactCards = options.redactCards ?? true;
  const redactPans = options.redactPans ?? true;

  const redactText = (value: string): string => {
    let result = value;
    if (redactCards) {
      result = result.replace(CARD, (match) =>
        luhnValid(match.replace(/\D/g, "")) ? replacement : match,
      );
    }
    if (redactEmails) result = result.replace(EMAIL, replacement);
    if (redactPans) result = result.replace(PAN, replacement);
    return result;
  };

  const redactValues = (value: JsonValue): JsonValue => {
    if (Array.isArray(value)) return value.map(redactValues);
    if (typeof value !== "object" || value === null) {
      return typeof value === "string" ? redactText(value) : value;
    }
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [key, redactValues(child)]),
    );
  };

  return (attributes: EventAttributes): EventAttributes =>
    redactValues(baseRedactor(attributes)) as EventAttributes;
}

function luhnValid(digits: string): boolean {
  if (digits.length < 13 || digits.length > 19) return false;
  let total = 0;
  const parity = digits.length % 2;
  for (let index = 0; index < digits.length; index += 1) {
    let digit = Number(digits[index]);
    if (index % 2 === parity) {
      digit *= 2;
      if (digit > 9) digit -= 9;
    }
    total += digit;
  }
  return total % 10 === 0;
}

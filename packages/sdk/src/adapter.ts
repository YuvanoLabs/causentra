import { createHash, randomBytes } from "node:crypto";
import { defaultRedactor } from "./redaction.js";
import {
  SCHEMA_VERSION,
  type EventAttributes,
  type EventExporter,
  type EventStatus,
  type EventType,
  type Redactor,
  type RuntimeErrorContext,
  type RuntimeEvent,
  type TraceContext,
} from "./types.js";
import { validateAttributes, validateEvent } from "./validation.js";

/** Configuration shared by framework adapters. */
export interface AdapterEventBridgeOptions {
  readonly serviceName: string;
  readonly exporter: EventExporter;
  readonly redactor?: Redactor;
  readonly onError?: (context: RuntimeErrorContext) => void;
  readonly now?: () => Date;
  /** Existing canonical parent used to join this adapter to a larger trace. */
  readonly parentContext?: TraceContext;
}

/** Framework lifecycle input converted to the stable runtime envelope. */
export interface AdapterEventInput {
  readonly externalTraceId: string;
  readonly externalSpanId: string;
  readonly externalParentSpanId?: string;
  readonly externalSessionId?: string;
  readonly timestamp?: string;
  readonly type: EventType;
  readonly name: string;
  readonly status?: EventStatus;
  readonly durationMs?: number;
  readonly attributes?: EventAttributes;
}

/**
 * Safe adapter-authoring surface. It converts framework identifiers into
 * deterministic Causentra IDs, applies redaction, assigns trace-local
 * sequence numbers, validates the result, and emits through a public exporter.
 * Framework packages never need access to SDK internals.
 */
export class AdapterEventBridge {
  readonly #serviceName: string;
  readonly #exporter: EventExporter;
  readonly #redactor: Redactor;
  readonly #onError: (context: RuntimeErrorContext) => void;
  readonly #now: () => Date;
  readonly #parentContext: TraceContext | undefined;
  readonly #sequences = new Map<string, number>();

  public constructor(options: AdapterEventBridgeOptions) {
    if (options.serviceName.trim().length === 0) {
      throw new TypeError("serviceName must not be empty");
    }
    this.#serviceName = options.serviceName;
    this.#exporter = options.exporter;
    this.#redactor = options.redactor ?? defaultRedactor;
    this.#onError = options.onError ?? (() => undefined);
    this.#now = options.now ?? (() => new Date());
    this.#parentContext = options.parentContext;
    if (this.#parentContext !== undefined) validateParentContext(this.#parentContext);
  }

  /** Emits one framework lifecycle event; returns undefined when safely dropped. */
  public emit(input: AdapterEventInput): RuntimeEvent | undefined {
    try {
      requireExternalId(input.externalTraceId, "externalTraceId");
      requireExternalId(input.externalSpanId, "externalSpanId");
      const traceId = this.#parentContext?.traceId
        ?? normalizeExternalId("trace", input.externalTraceId);
      const attributes = input.attributes ?? {};
      validateAttributes(attributes);
      const redacted = this.#redactor(attributes);
      validateAttributes(redacted);
      const event: RuntimeEvent = {
        schemaVersion: SCHEMA_VERSION,
        eventId: randomBytes(16).toString("hex"),
        traceId,
        spanId: normalizeExternalId(
          "span",
          `${input.externalTraceId}\0${input.externalSpanId}`,
        ),
        ...parentSpan(input, this.#parentContext),
        ...session(input, this.#parentContext),
        sequence: this.#nextSequence(traceId),
        timestamp: input.timestamp ?? this.#now().toISOString(),
        type: input.type,
        name: input.name,
        status: input.status ?? "unset",
        ...(input.durationMs === undefined ? {} : { durationMs: input.durationMs }),
        serviceName: this.#serviceName,
        attributes: redacted,
      };
      validateEvent(event);
      this.#exporter.emit(event);
      if (input.type === "trace.end") this.#sequences.delete(traceId);
      return event;
    } catch (error) {
      this.#report(error);
      return undefined;
    }
  }

  public flush(): Promise<boolean> {
    return this.#exporter.flush();
  }

  public async shutdown(): Promise<void> {
    if (this.#exporter.shutdown !== undefined) await this.#exporter.shutdown();
    else await this.#exporter.flush();
  }

  #nextSequence(traceId: string): number {
    const sequence = this.#sequences.get(traceId) ?? 0;
    this.#sequences.set(traceId, sequence + 1);
    return sequence;
  }

  #report(error: unknown): void {
    try {
      this.#onError({ operation: "adapter", error, droppedEvents: 1 });
    } catch {
      // Adapter diagnostics are application callbacks and cannot be trusted.
    }
  }
}

function parentSpan(
  input: AdapterEventInput,
  parent: TraceContext | undefined,
): { readonly parentSpanId?: string } {
  if (input.externalParentSpanId !== undefined) {
    return {
      parentSpanId: normalizeExternalId(
        "span",
        `${input.externalTraceId}\0${input.externalParentSpanId}`,
      ),
    };
  }
  return parent === undefined ? {} : { parentSpanId: parent.spanId };
}

function session(
  input: AdapterEventInput,
  parent: TraceContext | undefined,
): { readonly sessionId?: string } {
  if (input.externalSessionId !== undefined) {
    return { sessionId: normalizeExternalId("session", input.externalSessionId) };
  }
  return parent?.sessionId === undefined ? {} : { sessionId: parent.sessionId };
}

function validateParentContext(context: TraceContext): void {
  if (!/^[0-9a-f]{32}$/u.test(context.traceId)) {
    throw new TypeError("parentContext.traceId must be a 32-character lowercase hex ID");
  }
  if (!/^(?:[0-9a-f]{16}|[0-9a-f]{32})$/u.test(context.spanId)) {
    throw new TypeError("parentContext.spanId must be a 16- or 32-character lowercase hex ID");
  }
  if (context.sessionId !== undefined && !/^[0-9a-f]{32}$/u.test(context.sessionId)) {
    throw new TypeError("parentContext.sessionId must be a 32-character lowercase hex ID");
  }
}

/** Deterministically maps a framework identifier into a lowercase 128-bit ID. */
export function normalizeExternalId(namespace: string, value: string): string {
  return createHash("sha256")
    .update(namespace)
    .update("\0")
    .update(value)
    .digest("hex")
    .slice(0, namespace === "span" ? 16 : 32);
}

function requireExternalId(value: string, field: string): void {
  if (typeof value !== "string" || value.length === 0 || value.length > 1_024) {
    throw new TypeError(`${field} must be a non-empty string up to 1024 characters`);
  }
}

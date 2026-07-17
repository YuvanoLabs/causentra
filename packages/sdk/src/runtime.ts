import { AsyncLocalStorage } from "node:async_hooks";
import { randomBytes } from "node:crypto";
import { performance } from "node:perf_hooks";
import { defaultRedactor } from "./redaction.js";
import { createModelTelemetryAttributes, type ModelTelemetry } from "./model-telemetry.js";
import {
  createAgentRelationshipAttributes,
  type AgentRelationship,
} from "./relationships.js";
import {
  extractTraceContext,
  injectTraceContext,
  type TraceCarrier,
} from "./propagation.js";
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

interface ActiveContext extends TraceContext {
  readonly rootSpanId: string;
}

/** Construction options for a framework-neutral runtime instance. */
export interface CausentraRuntimeOptions {
  /** Stable logical service name shown in traces. */
  readonly serviceName: string;
  /** Destination for already-redacted runtime events. */
  readonly exporter: EventExporter;
  /** Optional identifier correlating multiple traces in one interaction. */
  readonly sessionId?: string;
  /** Attribute transformation; defaults to recursive sensitive-key redaction. */
  readonly redactor?: Redactor;
  /** Opt-in exception messages. Disabled because messages may contain user data. */
  readonly includeErrorMessage?: boolean;
  /** Non-throwing diagnostics for dropped or invalid telemetry. */
  readonly onError?: (context: RuntimeErrorContext) => void;
  /** Injectable wall clock for deterministic tests. */
  readonly now?: () => Date;
}

/** Optional fields for a custom event recorded inside an active trace. */
export interface RecordEventOptions {
  readonly type?: EventType;
  readonly status?: EventStatus;
  readonly attributes?: EventAttributes;
}

/**
 * Captures framework-neutral execution traces while preserving application
 * behavior. Instrumentation errors are reported through callbacks and never
 * replace operation results or exceptions.
 */
export class CausentraRuntime {
  readonly #serviceName: string;
  readonly #exporter: EventExporter;
  readonly #sessionId: string | undefined;
  readonly #redactor: Redactor;
  readonly #includeErrorMessage: boolean;
  readonly #onError: (context: RuntimeErrorContext) => void;
  readonly #now: () => Date;
  readonly #context = new AsyncLocalStorage<ActiveContext>();
  readonly #sequences = new Map<string, number>();

  public constructor(options: CausentraRuntimeOptions) {
    if (options.serviceName.trim().length === 0) {
      throw new TypeError("serviceName must not be empty");
    }
    this.#serviceName = options.serviceName;
    this.#exporter = options.exporter;
    this.#sessionId = options.sessionId;
    this.#redactor = options.redactor ?? defaultRedactor;
    this.#includeErrorMessage = options.includeErrorMessage ?? false;
    this.#onError = options.onError ?? (() => undefined);
    this.#now = options.now ?? (() => new Date());
  }

  /** Returns the current async trace context, or `undefined` outside a trace. */
  public currentContext(): TraceContext | undefined {
    const context = this.#context.getStore();
    if (context === undefined) return undefined;
    const result: TraceContext = {
      traceId: context.traceId,
      spanId: context.spanId,
    };
    if (context.parentSpanId !== undefined) {
      return { ...result, parentSpanId: context.parentSpanId, ...(context.sessionId === undefined ? {} : { sessionId: context.sessionId }) };
    }
    return context.sessionId === undefined ? result : { ...result, sessionId: context.sessionId };
  }

  /**
   * Runs an operation as a root trace and always emits one terminal event.
   * The original return value or exception is preserved.
   */
  public async trace<T>(
    name: string,
    operation: () => T | Promise<T>,
    attributes: EventAttributes = {},
  ): Promise<T> {
    return this.#runTrace(name, operation, attributes);
  }

  /**
   * Continues a W3C trace when the carrier contains a valid `traceparent`;
   * otherwise starts a new root trace. The carrier is treated as untrusted.
   */
  public async traceFromCarrier<T>(
    name: string,
    carrier: TraceCarrier,
    operation: () => T | Promise<T>,
    attributes: EventAttributes = {},
  ): Promise<T> {
    const remote = extractTraceContext(carrier);
    return this.#runTrace(name, operation, attributes, remote);
  }

  /** Injects the active context into a new carrier, or returns `undefined`. */
  public injectTraceContext(
    carrier: TraceCarrier = {},
    options: { readonly sampled?: boolean; readonly traceState?: string } = {},
  ): Record<string, string> | undefined {
    const context = this.currentContext();
    return context === undefined
      ? undefined
      : injectTraceContext(context, carrier, options);
  }

  async #runTrace<T>(
    name: string,
    operation: () => T | Promise<T>,
    attributes: EventAttributes,
    remote?: { readonly traceId: string; readonly spanId: string },
  ): Promise<T> {
    const traceId = remote?.traceId ?? createId();
    const spanId = createSpanId();
    const context: ActiveContext = {
      traceId,
      spanId,
      rootSpanId: spanId,
      ...(remote === undefined ? {} : { parentSpanId: remote.spanId }),
      ...(this.#sessionId === undefined ? {} : { sessionId: this.#sessionId }),
    };
    const start = performance.now();
    this.#emit(context, "trace.start", name, "unset", attributes);

    return this.#context.run(context, async () => {
      try {
        const result = await operation();
        this.#emit(context, "trace.end", name, "ok", {}, performance.now() - start);
        return result;
      } catch (error) {
        this.#emit(
          context,
          "trace.end",
          name,
          "error",
          errorAttributes(error, this.#includeErrorMessage),
          performance.now() - start,
        );
        throw error;
      } finally {
        this.#sequences.delete(traceId);
      }
    });
  }

  /**
   * Runs a nested operation using the current async context. When called
   * outside a trace it creates a root trace so instrumentation remains useful.
   */
  public async span<T>(
    name: string,
    kind: "span" | "agent" | "model" | "tool",
    operation: () => T | Promise<T>,
    attributes: EventAttributes = {},
  ): Promise<T> {
    return this.#runSpan(name, kind, operation, attributes);
  }

  /** Typed convenience for an agent operation. */
  public agent<T>(
    name: string,
    operation: () => T | Promise<T>,
    attributes: EventAttributes = {},
  ): Promise<T> {
    return this.#runSpan(name, "agent", operation, attributes);
  }

  /** Provider-neutral model operation with canonical GenAI usage attributes. */
  public model<T>(
    name: string,
    telemetry: ModelTelemetry,
    operation: () => T | Promise<T>,
    attributes: EventAttributes = {},
  ): Promise<T> {
    return this.#runSpan(name, "model", operation, {
      ...attributes,
      ...createModelTelemetryAttributes(telemetry),
    });
  }

  /** Typed convenience for a tool operation. */
  public tool<T>(
    name: string,
    operation: () => T | Promise<T>,
    attributes: EventAttributes = {},
  ): Promise<T> {
    return this.#runSpan(name, "tool", operation, attributes);
  }

  /** Records a first-class handoff or delegation as a causal agent operation. */
  public relationship<T>(
    relationship: AgentRelationship,
    operation: () => T | Promise<T>,
    attributes: EventAttributes = {},
  ): Promise<T> {
    return this.#runSpan(
      `${relationship.fromAgent} to ${relationship.toAgent}`,
      `agent.${relationship.kind}`,
      operation,
      { ...attributes, ...createAgentRelationshipAttributes(relationship) },
    );
  }

  async #runSpan<T>(
    name: string,
    eventFamily: "span" | "agent" | "model" | "tool" | `agent.${"handoff" | "delegation"}`,
    operation: () => T | Promise<T>,
    attributes: EventAttributes,
  ): Promise<T> {
    const parent = this.#context.getStore();
    if (parent === undefined) {
      return this.trace(name, operation, { ...attributes, "runtime.kind": eventFamily });
    }
    const spanId = createSpanId();
    const context: ActiveContext = {
      traceId: parent.traceId,
      spanId,
      parentSpanId: parent.spanId,
      rootSpanId: parent.rootSpanId,
      ...(parent.sessionId === undefined ? {} : { sessionId: parent.sessionId }),
    };
    const start = performance.now();
    this.#emit(context, `${eventFamily}.start`, name, "unset", attributes);

    return this.#context.run(context, async () => {
      try {
        const result = await operation();
        this.#emit(context, `${eventFamily}.end`, name, "ok", {}, performance.now() - start);
        return result;
      } catch (error) {
        this.#emit(
          context,
          `${eventFamily}.end`,
          name,
          "error",
          errorAttributes(error, this.#includeErrorMessage),
          performance.now() - start,
        );
        throw error;
      }
    });
  }

  /** Records an event in the active trace; returns `false` when none exists. */
  public record(name: string, options: RecordEventOptions = {}): boolean {
    const context = this.#context.getStore();
    if (context === undefined) return false;
    this.#emit(
      context,
      options.type ?? "custom",
      name,
      options.status ?? "unset",
      options.attributes ?? {},
    );
    return true;
  }

  /** Attempts delivery of every event queued when this method is called. */
  public flush(): Promise<boolean> {
    return this.#exporter.flush();
  }

  /** Flushes pending events and permanently closes the exporter when supported. */
  public async shutdown(): Promise<void> {
    if (this.#exporter.shutdown !== undefined) {
      await this.#exporter.shutdown();
    } else {
      await this.#exporter.flush();
    }
  }

  #emit(
    context: ActiveContext,
    type: EventType,
    name: string,
    status: EventStatus,
    attributes: EventAttributes,
    durationMs?: number,
  ): void {
    try {
      validateAttributes(attributes);
      const redacted = this.#redactor(attributes);
      validateAttributes(redacted);
      const event: RuntimeEvent = {
        schemaVersion: SCHEMA_VERSION,
        eventId: createId(),
        traceId: context.traceId,
        spanId: context.spanId,
        ...(context.parentSpanId === undefined ? {} : { parentSpanId: context.parentSpanId }),
        ...(context.sessionId === undefined ? {} : { sessionId: context.sessionId }),
        sequence: this.#nextSequence(context.traceId),
        timestamp: this.#now().toISOString(),
        type,
        name,
        status,
        ...(durationMs === undefined ? {} : { durationMs }),
        serviceName: this.#serviceName,
        attributes: redacted,
      };
      validateEvent(event);
      this.#exporter.emit(event);
    } catch (error) {
      try {
        this.#onError({ operation: "redact", error, droppedEvents: 1 });
      } catch {
        // Instrumentation must never alter application behavior.
      }
    }
  }

  #nextSequence(traceId: string): number {
    const next = this.#sequences.get(traceId) ?? 0;
    this.#sequences.set(traceId, next + 1);
    return next;
  }
}

function createId(): string {
  return randomBytes(16).toString("hex");
}

function createSpanId(): string {
  return randomBytes(8).toString("hex");
}

function errorAttributes(error: unknown, includeMessage: boolean): EventAttributes {
  if (error instanceof Error) {
    return {
      "error.type": error.name.slice(0, 128),
      ...(includeMessage ? { "error.message": error.message.slice(0, 1_024) } : {}),
    };
  }
  return {
    "error.type": "UnknownError",
    ...(includeMessage ? { "error.message": "Unknown error" } : {}),
  };
}

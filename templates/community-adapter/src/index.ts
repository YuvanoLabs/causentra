import {
  AdapterEventBridge,
  createAgentRelationshipAttributes,
  createModelTelemetryAttributes,
  type AdapterEventBridgeOptions,
  type AgentRelationship,
  type EventAttributes,
  type EventStatus,
  type EventType,
  type ModelTelemetry,
  type RuntimeEvent,
} from "@causentra/sdk";

/** Replace this value only after agreeing the public framework identifier. */
export const FRAMEWORK_NAME = "example-framework" as const;

/**
 * Example official-hook input. Replace it with the target framework's public
 * lifecycle types. Payload, prompt, state, output, and exception fields are
 * deliberately absent so accidental capture is difficult.
 */
export interface ExampleFrameworkEvent {
  readonly kind:
    | "run.started" | "run.finished"
    | "agent.started" | "agent.finished"
    | "model.started" | "model.finished"
    | "tool.started" | "tool.finished"
    | "handoff.started" | "handoff.finished"
    | "delegation.started" | "delegation.finished";
  readonly traceId: string;
  readonly spanId: string;
  readonly parentSpanId?: string;
  readonly sessionId?: string;
  readonly name: string;
  readonly timestamp?: string;
  readonly durationMs?: number;
  readonly status?: Extract<EventStatus, "ok" | "error">;
  /** Safe operational facts only; never derive these from message bodies. */
  readonly modelTelemetry?: ModelTelemetry;
  readonly relationship?: AgentRelationship;
}

export interface ExampleFrameworkInstrumentation {
  /** Call from the framework's documented lifecycle callback. */
  handle(event: ExampleFrameworkEvent): RuntimeEvent | undefined;
  flush(): Promise<boolean>;
  shutdown(): Promise<void>;
}

/**
 * Copyable adapter entry point. It uses only the public authoring bridge,
 * allowlists operational attributes, preserves fail-open behavior, and can
 * join a canonical parent supplied through `options.parentContext`.
 */
export function createExampleFrameworkInstrumentation(
  options: AdapterEventBridgeOptions,
): ExampleFrameworkInstrumentation {
  const bridge = new AdapterEventBridge(options);
  return {
    handle(event) {
      try {
        const mapping = lifecycle(event.kind);
        return bridge.emit({
          externalTraceId: event.traceId,
          externalSpanId: event.spanId,
          ...(event.parentSpanId === undefined
            ? {}
            : { externalParentSpanId: event.parentSpanId }),
          ...(event.sessionId === undefined ? {} : { externalSessionId: event.sessionId }),
          ...(event.timestamp === undefined ? {} : { timestamp: event.timestamp }),
          type: mapping.type,
          name: event.name,
          status: mapping.terminal ? event.status ?? "ok" : "unset",
          ...(mapping.terminal && event.durationMs !== undefined
            ? { durationMs: event.durationMs }
            : {}),
          attributes: portableAttributes(event),
        });
      } catch (error) {
        reportMappingError(options, error);
        return undefined;
      }
    },
    flush: () => bridge.flush(),
    shutdown: () => bridge.shutdown(),
  };
}

function portableAttributes(event: ExampleFrameworkEvent): EventAttributes {
  return {
    "framework.name": FRAMEWORK_NAME,
    "framework.event.kind": event.kind,
    ...(event.modelTelemetry === undefined
      ? {}
      : createModelTelemetryAttributes(event.modelTelemetry)),
    ...(event.relationship === undefined
      ? {}
      : createAgentRelationshipAttributes(event.relationship)),
  };
}

function lifecycle(kind: ExampleFrameworkEvent["kind"]): {
  readonly type: EventType;
  readonly terminal: boolean;
} {
  const terminal = kind.endsWith(".finished");
  const phase = terminal ? "end" : "start";
  if (kind.startsWith("run.")) return { type: `trace.${phase}`, terminal };
  if (kind.startsWith("agent.")) return { type: `agent.${phase}`, terminal };
  if (kind.startsWith("model.")) return { type: `model.${phase}`, terminal };
  if (kind.startsWith("tool.")) return { type: `tool.${phase}`, terminal };
  if (kind.startsWith("handoff.")) return { type: `agent.handoff.${phase}`, terminal };
  return { type: `agent.delegation.${phase}`, terminal };
}

function reportMappingError(options: AdapterEventBridgeOptions, error: unknown): void {
  try {
    options.onError?.({ operation: "adapter", error, droppedEvents: 1 });
  } catch {
    // Application diagnostic callbacks cannot be trusted by instrumentation.
  }
}

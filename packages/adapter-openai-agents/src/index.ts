import {
  AdapterEventBridge,
  createAgentRelationshipAttributes,
  type EventAttributes,
  type EventExporter,
  type Redactor,
  type RuntimeErrorContext,
  type TraceContext,
} from "@causentra/sdk";
import type { Span, Trace, TracingProcessor } from "@openai/agents";

export interface OpenAIAgentsAdapterOptions {
  readonly serviceName: string;
  readonly exporter: EventExporter;
  readonly redactor?: Redactor;
  readonly onError?: (context: RuntimeErrorContext) => void;
  /** Opt-in trace metadata capture. Prompt/model/tool payloads remain excluded. */
  readonly includeTraceMetadata?: boolean;
  /** Opt-in sanitized error messages; disabled because messages may contain data. */
  readonly includeErrorMessage?: boolean;
  readonly now?: () => Date;
  /** Parent context for joining this framework run to a cross-framework trace. */
  readonly parentContext?: TraceContext;
}

/** Creates a processor registered with the OpenAI Agents SDK via addTraceProcessor. */
export function createOpenAIAgentsTraceProcessor(
  options: OpenAIAgentsAdapterOptions,
): TracingProcessor {
  return new CausentraRuntimeTracingProcessor(options);
}

class CausentraRuntimeTracingProcessor implements TracingProcessor {
  readonly #bridge: AdapterEventBridge;
  readonly #includeTraceMetadata: boolean;
  readonly #includeErrorMessage: boolean;
  readonly #now: () => Date;
  readonly #traceStarts = new Map<string, number>();

  public constructor(options: OpenAIAgentsAdapterOptions) {
    this.#now = options.now ?? (() => new Date());
    this.#includeTraceMetadata = options.includeTraceMetadata ?? false;
    this.#includeErrorMessage = options.includeErrorMessage ?? false;
    this.#bridge = new AdapterEventBridge({
      serviceName: options.serviceName,
      exporter: options.exporter,
      ...(options.redactor === undefined ? {} : { redactor: options.redactor }),
      ...(options.onError === undefined ? {} : { onError: options.onError }),
      now: this.#now,
      ...(options.parentContext === undefined ? {} : { parentContext: options.parentContext }),
    });
  }

  public async onTraceStart(trace: Trace): Promise<void> {
    const now = this.#now();
    this.#traceStarts.set(trace.traceId, now.getTime());
    this.#bridge.emit({
      externalTraceId: trace.traceId,
      externalSpanId: rootSpanId(trace.traceId),
      ...(trace.groupId === null ? {} : { externalSessionId: trace.groupId }),
      timestamp: now.toISOString(),
      type: "trace.start",
      name: trace.name,
      attributes: {
        "framework.name": "openai-agents",
        "framework.version.contract": "0.13",
        ...(this.#includeTraceMetadata ? jsonRecord(trace.metadata) : {}),
      },
    });
  }

  public async onTraceEnd(trace: Trace): Promise<void> {
    const now = this.#now();
    const started = this.#traceStarts.get(trace.traceId);
    this.#traceStarts.delete(trace.traceId);
    this.#bridge.emit({
      externalTraceId: trace.traceId,
      externalSpanId: rootSpanId(trace.traceId),
      ...(trace.groupId === null ? {} : { externalSessionId: trace.groupId }),
      timestamp: now.toISOString(),
      type: "trace.end",
      name: trace.name,
      status: "ok",
      ...(started === undefined ? {} : { durationMs: Math.max(0, now.getTime() - started) }),
      attributes: { "framework.name": "openai-agents" },
    });
  }

  public async onSpanStart(span: Span<any>): Promise<void> {
    const family = spanFamily(span.spanData.type);
    this.#bridge.emit({
      externalTraceId: span.traceId,
      externalSpanId: span.spanId,
      externalParentSpanId: span.parentId ?? rootSpanId(span.traceId),
      ...(span.startedAt === null ? {} : { timestamp: span.startedAt }),
      type: lifecycleType(span.spanData.type, family, "start"),
      name: spanName(span),
      attributes: spanAttributes(span),
    });
  }

  public async onSpanEnd(span: Span<any>): Promise<void> {
    const family = spanFamily(span.spanData.type);
    this.#bridge.emit({
      externalTraceId: span.traceId,
      externalSpanId: span.spanId,
      externalParentSpanId: span.parentId ?? rootSpanId(span.traceId),
      ...(span.endedAt === null ? {} : { timestamp: span.endedAt }),
      type: lifecycleType(span.spanData.type, family, "end"),
      name: spanName(span),
      status: span.error === null ? "ok" : "error",
      ...(duration(span.startedAt, span.endedAt) === undefined
        ? {}
        : { durationMs: duration(span.startedAt, span.endedAt) as number }),
      attributes: {
        ...spanAttributes(span),
        ...(span.error === null
          ? {}
          : {
              "error.type": "OpenAIAgentsSpanError",
              ...(this.#includeErrorMessage
                ? { "error.message": span.error.message.slice(0, 1_024) }
                : {}),
            }),
      },
    });
  }

  public async forceFlush(): Promise<void> {
    await this.#bridge.flush();
  }

  public async shutdown(_timeout?: number): Promise<void> {
    await this.#bridge.shutdown();
  }
}

function rootSpanId(traceId: string): string {
  return `${traceId}:root`;
}

function spanFamily(type: string): "agent" | "model" | "tool" | "span" {
  if (type === "agent") return "agent";
  if (["generation", "response", "transcription", "speech", "speech_group"].includes(type)) {
    return "model";
  }
  if (["function", "mcp_tools"].includes(type)) return "tool";
  return "span";
}

function lifecycleType(
  frameworkType: string,
  family: "agent" | "model" | "tool" | "span",
  phase: "start" | "end",
): `${string}.${string}` {
  return frameworkType === "handoff" ? `agent.handoff.${phase}` : `${family}.${phase}`;
}

function spanName(span: Span<any>): string {
  const data = span.spanData as Record<string, unknown>;
  for (const candidate of [data.name, data.model, data.server, data.type]) {
    if (typeof candidate === "string" && candidate.length > 0) return candidate.slice(0, 256);
  }
  return "openai-agents-operation";
}

function spanAttributes(span: Span<any>): EventAttributes {
  const data = span.spanData as Record<string, unknown>;
  const attributes: EventAttributes = {
    "framework.name": "openai-agents",
    "framework.span.type": String(data.type),
  };
  if (typeof data.model === "string") attributes.model = data.model;
  if (typeof data.triggered === "boolean") attributes["guardrail.triggered"] = data.triggered;
  if (typeof data.from_agent === "string") attributes["handoff.from_agent"] = data.from_agent;
  if (typeof data.to_agent === "string") attributes["handoff.to_agent"] = data.to_agent;
  if (typeof data.from_agent === "string" && typeof data.to_agent === "string") {
    Object.assign(attributes, createAgentRelationshipAttributes({
      kind: "handoff",
      fromAgent: data.from_agent,
      toAgent: data.to_agent,
      relationshipId: span.spanId,
    }));
  }
  if (typeof data.usage === "object" && data.usage !== null) {
    const usage = data.usage as Record<string, unknown>;
    if (typeof usage.input_tokens === "number") {
      attributes["gen_ai.usage.input_tokens"] = usage.input_tokens;
    }
    if (typeof usage.output_tokens === "number") {
      attributes["gen_ai.usage.output_tokens"] = usage.output_tokens;
    }
  }
  return attributes;
}

function duration(start: string | null, end: string | null): number | undefined {
  if (start === null || end === null) return undefined;
  const value = Date.parse(end) - Date.parse(start);
  return Number.isFinite(value) ? Math.max(0, value) : undefined;
}

function jsonRecord(value: Record<string, any> | undefined): EventAttributes {
  if (value === undefined) return {};
  try {
    return JSON.parse(JSON.stringify(value)) as EventAttributes;
  } catch {
    return {};
  }
}

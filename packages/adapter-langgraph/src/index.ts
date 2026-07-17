import {
  AdapterEventBridge,
  type EventAttributes,
  type EventExporter,
  type Redactor,
  type RuntimeErrorContext,
  type TraceContext,
} from "@causentra/sdk";
import {
  BaseCallbackHandler,
  type CallbackHandlerMethods,
} from "@langchain/core/callbacks/base";

export interface LangGraphAdapterOptions {
  readonly serviceName: string;
  readonly exporter: EventExporter;
  readonly redactor?: Redactor;
  readonly onError?: (context: RuntimeErrorContext) => void;
  /** Opt-in tags and metadata capture. Inputs and outputs remain excluded. */
  readonly includeMetadata?: boolean;
  readonly now?: () => Date;
  /** Parent context for joining this graph to a cross-framework trace. */
  readonly parentContext?: TraceContext;
}

export interface LangGraphInstrumentation {
  readonly handler: BaseCallbackHandler;
  flush(): Promise<boolean>;
  shutdown(): Promise<void>;
}

/** Creates one callback handler per concurrently reusable graph instance. */
export function createLangGraphInstrumentation(
  options: LangGraphAdapterOptions,
): LangGraphInstrumentation {
  const engine = new LangGraphEventEngine(options);
  const methods: CallbackHandlerMethods = {
    handleChainStart: (
      chain,
      _inputs,
      runId,
      runTypeOrRuntimeParent,
      tags,
      metadata,
      declaredRunName,
      declaredParentOrRuntimeName,
    ) => {
      if (tags?.includes("langsmith:hidden")) return;
      // LangChain 1.2 runtime currently supplies parent ID in argument four
      // and run name in argument eight, while its declaration retains the
      // older runType/runName/parent order. Resolve both shapes defensively.
      const runtimeParent = engine.hasRun(runTypeOrRuntimeParent)
        ? runTypeOrRuntimeParent
        : engine.hasRun(declaredParentOrRuntimeName)
          ? declaredParentOrRuntimeName
          : undefined;
      const runtimeName = runtimeParent === declaredParentOrRuntimeName
        ? declaredRunName
        : declaredParentOrRuntimeName ?? declaredRunName;
      engine.start(
        "agent",
        operationName(chain, runtimeName, "graph"),
        runId,
        runtimeParent,
        tags,
        metadata,
      );
    },
    handleChainEnd: (_outputs, runId) => engine.end(runId, false),
    handleChainError: (error, runId) => engine.end(runId, true, error),
    handleLLMStart: (llm, _prompts, runId, parentRunId, _extra, tags, metadata, runName) =>
      engine.start("model", operationName(llm, runName, "model"), runId, parentRunId, tags, metadata),
    handleChatModelStart: (model, _messages, runId, parentRunId, _extra, tags, metadata, runName) =>
      engine.start("model", operationName(model, runName, "chat-model"), runId, parentRunId, tags, metadata),
    handleLLMEnd: (_output, runId) => engine.end(runId, false),
    handleLLMError: (error, runId) => engine.end(runId, true, error),
    handleToolStart: (tool, _input, runId, parentRunId, tags, metadata, runName) =>
      engine.start("tool", operationName(tool, runName, "tool"), runId, parentRunId, tags, metadata),
    handleToolEnd: (_output, runId) => engine.end(runId, false),
    handleToolError: (error, runId) => engine.end(runId, true, error),
    handleRetrieverStart: (retriever, _query, runId, parentRunId, tags, metadata, name) =>
      engine.start("span", operationName(retriever, name, "retriever"), runId, parentRunId, tags, metadata),
    handleRetrieverEnd: (_documents, runId) => engine.end(runId, false),
    handleRetrieverError: (error, runId) => engine.end(runId, true, error),
  };
  return {
    handler: BaseCallbackHandler.fromMethods(methods),
    flush: () => engine.flush(),
    shutdown: () => engine.shutdown(),
  };
}

type OperationFamily = "agent" | "model" | "tool" | "span";

interface ActiveRun {
  readonly traceId: string;
  readonly runId: string;
  readonly parentRunId: string;
  readonly family: OperationFamily;
  readonly name: string;
  readonly startedAt: number;
  readonly ownsTrace: boolean;
}

class LangGraphEventEngine {
  readonly #bridge: AdapterEventBridge;
  readonly #now: () => Date;
  readonly #includeMetadata: boolean;
  readonly #runs = new Map<string, ActiveRun>();
  readonly #traceNames = new Map<string, string>();

  public constructor(options: LangGraphAdapterOptions) {
    this.#now = options.now ?? (() => new Date());
    this.#includeMetadata = options.includeMetadata ?? false;
    this.#bridge = new AdapterEventBridge({
      serviceName: options.serviceName,
      exporter: options.exporter,
      ...(options.redactor === undefined ? {} : { redactor: options.redactor }),
      ...(options.onError === undefined ? {} : { onError: options.onError }),
      now: this.#now,
      ...(options.parentContext === undefined ? {} : { parentContext: options.parentContext }),
    });
  }

  public hasRun(runId: string | undefined): runId is string {
    return runId !== undefined && this.#runs.has(runId);
  }

  public start(
    family: OperationFamily,
    name: string,
    runId: string,
    parentRunId: string | undefined,
    tags: string[] | undefined,
    metadata: Record<string, unknown> | undefined,
  ): void {
    if (this.#runs.has(runId)) return;
    const parent = parentRunId === undefined ? undefined : this.#runs.get(parentRunId);
    const traceId = parent?.traceId ?? runId;
    const rootId = rootSpanId(traceId);
    const now = this.#now();
    const ownsTrace = !this.#traceNames.has(traceId);
    if (ownsTrace) {
      this.#traceNames.set(traceId, name);
      this.#bridge.emit({
        externalTraceId: traceId,
        externalSpanId: rootId,
        timestamp: now.toISOString(),
        type: "trace.start",
        name,
        attributes: { "framework.name": "langgraph" },
      });
    }
    this.#runs.set(runId, {
      traceId,
      runId,
      parentRunId: parentRunId ?? rootId,
      family,
      name,
      startedAt: now.getTime(),
      ownsTrace,
    });
    this.#bridge.emit({
      externalTraceId: traceId,
      externalSpanId: runId,
      externalParentSpanId: parentRunId ?? rootId,
      timestamp: now.toISOString(),
      type: `${family}.start`,
      name,
      attributes: {
        "framework.name": "langgraph",
        "framework.operation.family": family,
        ...(this.#includeMetadata ? safeMetadata(tags, metadata) : {}),
      },
    });
  }

  public end(runId: string, failed: boolean, error?: unknown): void {
    const run = this.#runs.get(runId);
    if (run === undefined) return;
    this.#runs.delete(runId);
    const now = this.#now();
    this.#bridge.emit({
      externalTraceId: run.traceId,
      externalSpanId: run.runId,
      externalParentSpanId: run.parentRunId,
      timestamp: now.toISOString(),
      type: `${run.family}.end`,
      name: run.name,
      status: failed ? "error" : "ok",
      durationMs: Math.max(0, now.getTime() - run.startedAt),
      attributes: {
        "framework.name": "langgraph",
        ...(failed ? { "error.type": errorType(error) } : {}),
      },
    });
    if (run.ownsTrace) {
      this.#bridge.emit({
        externalTraceId: run.traceId,
        externalSpanId: rootSpanId(run.traceId),
        timestamp: now.toISOString(),
        type: "trace.end",
        name: this.#traceNames.get(run.traceId) ?? run.name,
        status: failed ? "error" : "ok",
        durationMs: Math.max(0, now.getTime() - run.startedAt),
        attributes: { "framework.name": "langgraph" },
      });
      this.#traceNames.delete(run.traceId);
    }
  }

  public flush(): Promise<boolean> {
    return this.#bridge.flush();
  }

  public shutdown(): Promise<void> {
    return this.#bridge.shutdown();
  }
}

function operationName(
  serialized: { id?: string[]; name?: string } | Record<string, unknown>,
  runName: string | undefined,
  fallback: string,
): string {
  if (runName !== undefined && runName.length > 0) return runName.slice(0, 256);
  if ("name" in serialized && typeof serialized.name === "string") {
    return serialized.name.slice(0, 256);
  }
  if ("id" in serialized && Array.isArray(serialized.id)) {
    const last = serialized.id.at(-1);
    if (typeof last === "string" && last.length > 0) return last.slice(0, 256);
  }
  return fallback;
}

function rootSpanId(traceId: string): string {
  return `${traceId}:root`;
}

function errorType(error: unknown): string {
  return error instanceof Error ? error.name.slice(0, 128) : "UnknownError";
}

function safeMetadata(
  tags: string[] | undefined,
  metadata: Record<string, unknown> | undefined,
): EventAttributes {
  const attributes: EventAttributes = {};
  if (tags !== undefined) attributes["framework.tags"] = tags.slice(0, 32);
  if (metadata !== undefined) {
    try {
      attributes["framework.metadata"] = JSON.parse(JSON.stringify(metadata));
    } catch {
      // Non-JSON framework metadata is deliberately omitted.
    }
  }
  return attributes;
}

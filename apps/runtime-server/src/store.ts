import { appendFile, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { RuntimeEvent } from "@causentra/sdk";
import { validateEvent } from "@causentra/sdk";

/** Query projection shown in trace lists. */
export interface TraceSummary {
  readonly traceId: string;
  readonly name: string;
  readonly serviceName: string;
  readonly status: "running" | "ok" | "error";
  readonly startedAt: string;
  readonly endedAt?: string;
  readonly durationMs?: number;
  readonly eventCount: number;
  readonly errorCount: number;
  /** Framework identities observed anywhere in the trace. */
  readonly frameworks: readonly string[];
  /** Canonical model-provider identities observed anywhere in the trace. */
  readonly providers: readonly string[];
  /** Request or response model identities observed anywhere in the trace. */
  readonly models: readonly string[];
  /** Tool operation names observed at lifecycle start. */
  readonly tools: readonly string[];
  /** Logical agent names and relationship participants observed in the trace. */
  readonly agents: readonly string[];
  /** Hashed or application-supplied session identifiers observed in the trace. */
  readonly sessionIds: readonly string[];
  readonly relationshipCount: number;
}

/** Optional exact/substring dimensions supported by the local trace query. */
export interface TraceFilters {
  readonly status?: TraceSummary["status"];
  readonly framework?: string;
  readonly provider?: string;
  readonly model?: string;
  readonly sessionId?: string;
  readonly tool?: string;
  /** Safe metadata search; payload bodies are never indexed. */
  readonly query?: string;
}

/** A trace summary with its deterministically ordered source events. */
export interface TraceDetail {
  readonly summary: TraceSummary;
  readonly events: readonly RuntimeEvent[];
}

/** Replaceable persistence boundary used by the local HTTP service. */
export interface TraceStore {
  append(events: readonly RuntimeEvent[]): Promise<number>;
  list(limit: number, filters?: TraceFilters): readonly TraceSummary[];
  get(traceId: string): TraceDetail | undefined;
  delete(traceId: string): Promise<boolean>;
  prune(keepLatest: number): Promise<number>;
  eventCount(): number;
  traceCount(): number;
  recoveryWarningCount(): number;
}

/**
 * Dependency-free local store backed by newline-delimited JSON. Writes are
 * serialized, duplicate event IDs are ignored, and valid records survive a
 * corrupt or incomplete line encountered during recovery.
 */
export class FileTraceStore implements TraceStore {
  readonly #eventsByTrace = new Map<string, RuntimeEvent[]>();
  readonly #eventIds = new Set<string>();
  #writeChain: Promise<void> = Promise.resolve();
  #recoveryWarnings = 0;

  private constructor(private readonly filePath: string) {}

  /** Opens a store and rebuilds in-memory trace projections from valid lines. */
  public static async open(filePath: string): Promise<FileTraceStore> {
    const store = new FileTraceStore(filePath);
    await mkdir(dirname(filePath), { recursive: true });
    try {
      const contents = await readFile(filePath, "utf8");
      for (const line of contents.split(/\r?\n/u)) {
        if (line.trim().length === 0) continue;
        try {
          const event: unknown = JSON.parse(line);
          validateEvent(event);
          store.#index(event);
        } catch {
          // Preserve valid records while making corruption visible through health.
          store.#recoveryWarnings += 1;
        }
      }
    } catch (error) {
      if (!isMissingFile(error)) throw error;
    }
    return store;
  }

  /** Durably appends unique events and returns the number accepted. */
  public async append(events: readonly RuntimeEvent[]): Promise<number> {
    for (const event of events) validateEvent(event);
    let accepted = 0;
    // Selection, write, and indexing share one chain. This prevents concurrent
    // requests from both accepting an event ID before either has indexed it.
    const write = this.#writeChain.then(async () => {
      const seen = new Set(this.#eventIds);
      const unique = events.filter((event) => {
        if (seen.has(event.eventId)) return false;
        seen.add(event.eventId);
        return true;
      });
      if (unique.length === 0) return;
      const payload = `${unique.map((event) => JSON.stringify(event)).join("\n")}\n`;
      await appendFile(this.filePath, payload, "utf8");
      for (const event of unique) this.#index(event);
      accepted = unique.length;
    });
    this.#writeChain = write.catch(() => undefined);
    await write;
    return accepted;
  }

  public list(limit: number, filters: TraceFilters = {}): readonly TraceSummary[] {
    return [...this.#eventsByTrace.entries()]
      .map(([traceId, events]) => summarize(traceId, events))
      .filter((summary) => matchesFilters(summary, filters))
      .sort((left, right) => right.startedAt.localeCompare(left.startedAt))
      .slice(0, limit);
  }

  public get(traceId: string): TraceDetail | undefined {
    const events = this.#eventsByTrace.get(traceId);
    if (events === undefined) return undefined;
    const ordered = [...events].sort(compareEvents);
    return { summary: summarize(traceId, ordered), events: ordered };
  }

  /** Deletes one complete trace and rewrites the user-owned store atomically. */
  public async delete(traceId: string): Promise<boolean> {
    let deleted = false;
    const write = this.#writeChain.then(async () => {
      if (!this.#eventsByTrace.has(traceId)) return;
      const remaining = [...this.#eventsByTrace.entries()]
        .filter(([id]) => id !== traceId)
        .flatMap(([, events]) => events);
      await this.#replace(remaining);
      deleted = true;
    });
    this.#writeChain = write.catch(() => undefined);
    await write;
    return deleted;
  }

  /** Keeps only the latest N traces and returns the number removed. */
  public async prune(keepLatest: number): Promise<number> {
    if (!Number.isSafeInteger(keepLatest) || keepLatest < 0) {
      throw new RangeError("keepLatest must be a non-negative integer");
    }
    let removed = 0;
    const write = this.#writeChain.then(async () => {
      const keep = new Set(this.list(keepLatest).map((trace) => trace.traceId));
      const entries = [...this.#eventsByTrace.entries()];
      removed = entries.filter(([traceId]) => !keep.has(traceId)).length;
      if (removed === 0) return;
      await this.#replace(
        entries.filter(([traceId]) => keep.has(traceId)).flatMap(([, events]) => events),
      );
    });
    this.#writeChain = write.catch(() => undefined);
    await write;
    return removed;
  }

  public eventCount(): number {
    return this.#eventIds.size;
  }

  public traceCount(): number {
    return this.#eventsByTrace.size;
  }

  public recoveryWarningCount(): number {
    return this.#recoveryWarnings;
  }

  #index(event: RuntimeEvent): void {
    if (this.#eventIds.has(event.eventId)) return;
    this.#eventIds.add(event.eventId);
    const events = this.#eventsByTrace.get(event.traceId) ?? [];
    events.push(event);
    this.#eventsByTrace.set(event.traceId, events);
  }

  async #replace(events: readonly RuntimeEvent[]): Promise<void> {
    const temporary = `${this.filePath}.${String(process.pid)}.tmp`;
    const payload = events.length === 0
      ? ""
      : `${events.map((event) => JSON.stringify(event)).join("\n")}\n`;
    await writeFile(temporary, payload, "utf8");
    await rename(temporary, this.filePath);
    this.#eventsByTrace.clear();
    this.#eventIds.clear();
    this.#recoveryWarnings = 0;
    for (const event of events) this.#index(event);
  }
}

function summarize(traceId: string, events: readonly RuntimeEvent[]): TraceSummary {
  const ordered = [...events].sort(compareEvents);
  const start = ordered.find((event) => event.type === "trace.start") ?? ordered[0];
  const end = [...ordered].reverse().find((event) => event.type === "trace.end");
  if (start === undefined) {
    throw new Error(`trace ${traceId} has no events`);
  }
  const errorCount = ordered.filter((event) => event.status === "error").length;
  const summary: TraceSummary = {
    traceId,
    name: start.name,
    serviceName: start.serviceName,
    status: errorCount > 0 ? "error" : end === undefined ? "running" : "ok",
    startedAt: start.timestamp,
    eventCount: ordered.length,
    errorCount,
    frameworks: uniqueAttributeStrings(ordered, "framework.name"),
    providers: uniqueAttributeStrings(ordered, "gen_ai.provider.name"),
    models: uniqueStrings([
      ...uniqueAttributeStrings(ordered, "gen_ai.request.model"),
      ...uniqueAttributeStrings(ordered, "gen_ai.response.model"),
    ]),
    tools: uniqueStrings(ordered
      .filter((event) => event.type === "tool.start")
      .map((event) => event.name)),
    agents: uniqueStrings([
      ...ordered
        .filter((event) => event.type === "agent.start")
        .map((event) => event.name),
      ...uniqueAttributeStrings(ordered, "causentra.agent.from.name"),
      ...uniqueAttributeStrings(ordered, "causentra.agent.to.name"),
    ]),
    sessionIds: uniqueStrings(ordered
      .map((event) => event.sessionId)
      .filter((value): value is string => value !== undefined)),
    relationshipCount: ordered.filter((event) => (
      event.type === "agent.handoff.start" || event.type === "agent.delegation.start"
    )).length,
  };
  if (end !== undefined) {
    return {
      ...summary,
      endedAt: end.timestamp,
      ...(end.durationMs === undefined ? {} : { durationMs: end.durationMs }),
    };
  }
  return summary;
}

function matchesFilters(summary: TraceSummary, filters: TraceFilters): boolean {
  return (
    (filters.status === undefined || summary.status === filters.status)
    && matchesText(summary.frameworks, filters.framework)
    && matchesText(summary.providers, filters.provider)
    && matchesText(summary.models, filters.model)
    && matchesText(summary.tools, filters.tool)
    && (filters.sessionId === undefined || summary.sessionIds.includes(filters.sessionId))
    && matchesText([
      summary.name,
      summary.serviceName,
      ...summary.frameworks,
      ...summary.providers,
      ...summary.models,
      ...summary.tools,
      ...summary.agents,
    ], filters.query)
  );
}

function matchesText(values: readonly string[], requested: string | undefined): boolean {
  if (requested === undefined) return true;
  const needle = requested.toLocaleLowerCase("en-US");
  return values.some((value) => value.toLocaleLowerCase("en-US").includes(needle));
}

function uniqueAttributeStrings(
  events: readonly RuntimeEvent[],
  key: string,
): readonly string[] {
  return uniqueStrings(events
    .map((event) => event.attributes[key])
    .filter((value): value is string => typeof value === "string"));
}

function uniqueStrings(values: readonly string[]): readonly string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

function compareEvents(left: RuntimeEvent, right: RuntimeEvent): number {
  return (
    left.timestamp.localeCompare(right.timestamp) ||
    lifecycleOrder(left) - lifecycleOrder(right) ||
    left.sequence - right.sequence ||
    left.eventId.localeCompare(right.eventId)
  );
}

function lifecycleOrder(event: RuntimeEvent): number {
  if (event.type.endsWith(".start")) return 0;
  if (event.type.endsWith(".end")) return 2;
  return 1;
}

function isMissingFile(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  );
}

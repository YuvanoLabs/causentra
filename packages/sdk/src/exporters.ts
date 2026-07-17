import type {
  EventExporter,
  RuntimeErrorContext,
  RuntimeEvent,
} from "./types.js";

/** In-memory exporter intended for tests, adapters, and embedded inspection. */
export class MemoryExporter implements EventExporter {
  public readonly events: RuntimeEvent[] = [];

  public emit(event: RuntimeEvent): void {
    this.events.push(structuredClone(event));
  }

  public async flush(): Promise<boolean> {
    return true;
  }
}

/** Configuration for bounded HTTP batch delivery. */
export interface HttpBatchExporterOptions {
  /** Complete ingestion endpoint. Defaults to the local runtime. */
  readonly endpoint?: string;
  /** Maximum events per request. */
  readonly batchSize?: number;
  /** Maximum time before a partial batch is attempted. */
  readonly flushIntervalMs?: number;
  /** Hard in-memory bound; new events are dropped after this limit. */
  readonly maxQueueSize?: number;
  /** Retries per delivery attempt after the initial request. */
  readonly maxRetries?: number;
  readonly requestTimeoutMs?: number;
  readonly retryBaseDelayMs?: number;
  /** Additional headers, for example a future project ingest key. */
  readonly headers?: Readonly<Record<string, string>>;
  /** Non-throwing callback for delivery failure and queue overflow. */
  readonly onError?: (context: RuntimeErrorContext) => void;
}

/**
 * Bounded, fail-open HTTP exporter with batching, timeouts, and exponential
 * retry. Delivery is at least once; collectors deduplicate by `eventId`.
 */
export class HttpBatchExporter implements EventExporter {
  readonly #endpoint: string;
  readonly #batchSize: number;
  readonly #flushIntervalMs: number;
  readonly #maxQueueSize: number;
  readonly #maxRetries: number;
  readonly #requestTimeoutMs: number;
  readonly #retryBaseDelayMs: number;
  readonly #headers: Readonly<Record<string, string>>;
  readonly #onError: (context: RuntimeErrorContext) => void;
  readonly #queue: RuntimeEvent[] = [];
  #timer: NodeJS.Timeout | undefined;
  #drainPromise: Promise<boolean> | undefined;
  #closed = false;
  #droppedEvents = 0;

  public constructor(options: HttpBatchExporterOptions = {}) {
    this.#endpoint = options.endpoint ?? "http://127.0.0.1:4318/v1/events";
    this.#batchSize = positiveInteger(options.batchSize, 50, "batchSize");
    this.#flushIntervalMs = positiveInteger(
      options.flushIntervalMs,
      1_000,
      "flushIntervalMs",
    );
    this.#maxQueueSize = positiveInteger(
      options.maxQueueSize,
      2_000,
      "maxQueueSize",
    );
    this.#maxRetries = nonNegativeInteger(options.maxRetries, 2, "maxRetries");
    this.#requestTimeoutMs = positiveInteger(
      options.requestTimeoutMs,
      3_000,
      "requestTimeoutMs",
    );
    this.#retryBaseDelayMs = positiveInteger(
      options.retryBaseDelayMs,
      100,
      "retryBaseDelayMs",
    );
    this.#headers = options.headers ?? {};
    this.#onError = options.onError ?? (() => undefined);
  }

  public emit(event: RuntimeEvent): void {
    if (this.#closed) {
      this.#report(new Error("exporter is closed"), 1);
      return;
    }
    if (this.#queue.length >= this.#maxQueueSize) {
      this.#report(new Error("export queue is full"), 1);
      return;
    }
    this.#queue.push(event);
    if (this.#queue.length >= this.#batchSize) {
      void this.#drain();
    } else {
      this.#schedule();
    }
  }

  public async flush(): Promise<boolean> {
    this.#clearTimer();
    return this.#drain();
  }

  public async shutdown(): Promise<void> {
    await this.flush();
    this.#closed = true;
  }

  #schedule(): void {
    if (this.#timer !== undefined) return;
    this.#timer = setTimeout(() => {
      this.#timer = undefined;
      void this.#drain();
    }, this.#flushIntervalMs);
    this.#timer.unref();
  }

  #clearTimer(): void {
    if (this.#timer !== undefined) {
      clearTimeout(this.#timer);
      this.#timer = undefined;
    }
  }

  async #drain(): Promise<boolean> {
    if (this.#drainPromise !== undefined) return this.#drainPromise;
    this.#drainPromise = this.#performDrain().finally(() => {
      this.#drainPromise = undefined;
      if (this.#queue.length > 0 && !this.#closed) this.#schedule();
    });
    return this.#drainPromise;
  }

  async #performDrain(): Promise<boolean> {
    let successful = true;
    while (this.#queue.length > 0) {
      const batch = this.#queue.splice(0, this.#batchSize);
      try {
        await this.#send(batch);
      } catch (error) {
        successful = false;
        this.#queue.unshift(...batch);
        this.#report(error, 0);
        break;
      }
    }
    return successful;
  }

  async #send(events: readonly RuntimeEvent[]): Promise<void> {
    let lastError: unknown = new Error("export failed");
    for (let attempt = 0; attempt <= this.#maxRetries; attempt += 1) {
      if (attempt > 0) {
        await delay(this.#retryBaseDelayMs * 2 ** (attempt - 1));
      }
      try {
        const response = await fetch(this.#endpoint, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            ...this.#headers,
          },
          body: JSON.stringify({ events }),
          signal: AbortSignal.timeout(this.#requestTimeoutMs),
        });
        if (response.ok) return;
        const body = (await response.text()).slice(0, 512);
        lastError = new Error(`collector returned ${response.status}: ${body}`);
        if (response.status < 500 && response.status !== 429) break;
      } catch (error) {
        lastError = error;
      }
    }
    throw lastError;
  }

  #report(error: unknown, newlyDropped: number): void {
    this.#droppedEvents += newlyDropped;
    try {
      this.#onError({
        operation: "export",
        error,
        droppedEvents: this.#droppedEvents,
      });
    } catch {
      // Telemetry callbacks must never affect application execution.
    }
  }
}

function positiveInteger(
  value: number | undefined,
  fallback: number,
  name: string,
): number {
  const resolved = value ?? fallback;
  if (!Number.isSafeInteger(resolved) || resolved <= 0) {
    throw new RangeError(`${name} must be a positive integer`);
  }
  return resolved;
}

function nonNegativeInteger(
  value: number | undefined,
  fallback: number,
  name: string,
): number {
  const resolved = value ?? fallback;
  if (!Number.isSafeInteger(resolved) || resolved < 0) {
    throw new RangeError(`${name} must be a non-negative integer`);
  }
  return resolved;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

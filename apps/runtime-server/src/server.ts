import { readFile } from "node:fs/promises";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";
import { EventValidationError, validateEvent, type RuntimeEvent } from "@causentra/sdk";
import {
  convertOtlpTraces,
  decodeOtlpProtobuf,
  encodeOtlpProtobufResponse,
} from "./otlp.js";
import type { TraceFilters, TraceStore } from "./store.js";

const MAX_BODY_BYTES = 1024 * 1024;
const TRACE_ID_PATTERN = /^[0-9a-f]{32}$/;
const PUBLIC_DIRECTORY = fileURLToPath(new URL("../../public/", import.meta.url));

/** Options for embedding or starting the local Causentra HTTP service. */
export interface RuntimeServerOptions {
  readonly host?: string;
  readonly port?: number;
  readonly store: TraceStore;
  readonly publicDirectory?: string;
  /** Required to bind an unauthenticated M0 server outside loopback. */
  readonly allowUnsafeNetwork?: boolean;
}

/** Handle returned after the server successfully binds. */
export interface RunningRuntimeServer {
  readonly url: string;
  close(): Promise<void>;
}

/** Starts ingestion, queries, and dashboard assets on one local HTTP server. */
export async function startRuntimeServer(
  options: RuntimeServerOptions,
): Promise<RunningRuntimeServer> {
  const host = options.host ?? "127.0.0.1";
  if (!isLoopbackHost(host) && options.allowUnsafeNetwork !== true) {
    throw new Error(
      `Refusing unauthenticated non-loopback bind to ${host}; set allowUnsafeNetwork only in an isolated trusted network`,
    );
  }
  const port = options.port ?? 4318;
  const publicDirectory = options.publicDirectory ?? PUBLIC_DIRECTORY;
  const server = createServer((request, response) => {
    void route(request, response, options.store, publicDirectory).catch((error) => {
      console.error("Unhandled request error", error);
      if (!response.headersSent) {
        writeError(response, 500, "internal_error", "Internal server error");
      } else {
        response.destroy();
      }
    });
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => {
      server.off("error", reject);
      resolve();
    });
  });
  const address = server.address();
  if (address === null || typeof address === "string") {
    throw new Error("server did not expose a TCP address");
  }
  return {
    url: `http://${host}:${address.port}`,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.close((error) => (error === undefined ? resolve() : reject(error)));
      }),
  };
}

/** Returns true only for the explicitly supported local-only bind names. */
export function isLoopbackHost(host: string): boolean {
  return host === "127.0.0.1" || host === "::1" || host.toLowerCase() === "localhost";
}

async function route(
  request: IncomingMessage,
  response: ServerResponse,
  store: TraceStore,
  publicDirectory: string,
): Promise<void> {
  const method = request.method ?? "GET";
  const url = new URL(request.url ?? "/", "http://localhost");

  if (method === "GET" && url.pathname === "/health") {
    writeJson(response, 200, {
      status: "ok",
      traces: store.traceCount(),
      events: store.eventCount(),
      recoveryWarnings: store.recoveryWarningCount(),
    });
    return;
  }

  if (method === "POST" && url.pathname === "/v1/events") {
    await ingest(request, response, store);
    return;
  }

  if (method === "POST" && url.pathname === "/v1/traces") {
    await ingestOtlp(request, response, store);
    return;
  }

    if (method === "GET" && url.pathname === "/api/traces") {
    const requestedLimit = Number(url.searchParams.get("limit") ?? "50");
    const limit = Number.isSafeInteger(requestedLimit)
      ? Math.min(Math.max(requestedLimit, 1), 200)
      : 50;
      const filters = traceFilters(url.searchParams);
      if (filters instanceof Error) {
        writeError(response, 400, "invalid_trace_filter", filters.message);
        return;
      }
      writeJson(response, 200, { traces: store.list(limit, filters) });
      return;
  }

  if (method === "POST" && url.pathname === "/api/traces/import") {
    await importTrace(request, response, store);
    return;
  }

  if (method === "POST" && url.pathname === "/api/retention/prune") {
    await pruneTraces(request, response, store);
    return;
  }

  if (method === "GET" && url.pathname.endsWith("/export") && url.pathname.startsWith("/api/traces/")) {
    const traceId = decodeURIComponent(
      url.pathname.slice("/api/traces/".length, -"/export".length),
    );
    if (!TRACE_ID_PATTERN.test(traceId)) {
      writeError(response, 400, "invalid_trace_id", "Trace ID is invalid");
      return;
    }
    const trace = store.get(traceId);
    if (trace === undefined) {
      writeError(response, 404, "trace_not_found", "Trace was not found");
      return;
    }
    writeJson(response, 200, {
      format: "causentra.trace-bundle",
      version: 1,
      exportedAt: new Date().toISOString(),
      trace,
    });
    return;
  }

  if (method === "DELETE" && url.pathname.startsWith("/api/traces/")) {
    const traceId = decodeURIComponent(url.pathname.slice("/api/traces/".length));
    if (!TRACE_ID_PATTERN.test(traceId)) {
      writeError(response, 400, "invalid_trace_id", "Trace ID is invalid");
      return;
    }
    if (!(await store.delete(traceId))) {
      writeError(response, 404, "trace_not_found", "Trace was not found");
      return;
    }
    writeJson(response, 200, { deleted: true, traceId });
    return;
  }

  if (method === "GET" && url.pathname.startsWith("/api/traces/")) {
    const traceId = decodeURIComponent(url.pathname.slice("/api/traces/".length));
    if (!TRACE_ID_PATTERN.test(traceId)) {
      writeError(response, 400, "invalid_trace_id", "Trace ID is invalid");
      return;
    }
    const trace = store.get(traceId);
    if (trace === undefined) {
      writeError(response, 404, "trace_not_found", "Trace was not found");
      return;
    }
    writeJson(response, 200, trace);
    return;
  }

  const asset = new Map<string, readonly [string, string]>([
    ["/", ["index.html", "text/html; charset=utf-8"]],
    ["/app.js", ["app.js", "text/javascript; charset=utf-8"]],
    ["/styles.css", ["styles.css", "text/css; charset=utf-8"]],
  ]).get(url.pathname);
  if (method === "GET" && asset !== undefined) {
    const [filename, contentType] = asset;
    const contents = await readFile(`${publicDirectory}/${filename}`);
    response.writeHead(200, securityHeaders({ "content-type": contentType }));
    response.end(contents);
    return;
  }

  writeError(response, 404, "not_found", "Route was not found");
}

function traceFilters(parameters: URLSearchParams): TraceFilters | Error {
  const status = optionalQuery(parameters, "status", 16);
  const framework = optionalQuery(parameters, "framework", 256);
  const provider = optionalQuery(parameters, "provider", 256);
  const model = optionalQuery(parameters, "model", 256);
  const sessionId = optionalQuery(parameters, "session", 64);
  const tool = optionalQuery(parameters, "tool", 256);
  const query = optionalQuery(parameters, "q", 256);
  if (status instanceof Error) return status;
  if (framework instanceof Error) return framework;
  if (provider instanceof Error) return provider;
  if (model instanceof Error) return model;
  if (sessionId instanceof Error) return sessionId;
  if (tool instanceof Error) return tool;
  if (query instanceof Error) return query;
  if (status !== undefined && !["running", "ok", "error"].includes(status)) {
    return new TypeError("status must be running, ok, or error");
  }
  if (sessionId !== undefined && !/^[0-9a-f]{32}$/u.test(sessionId)) {
    return new TypeError("session must be a 32-character lowercase hex identifier");
  }
  return {
    ...(status === undefined ? {} : { status: status as "running" | "ok" | "error" }),
    ...(framework === undefined ? {} : { framework }),
    ...(provider === undefined ? {} : { provider }),
    ...(model === undefined ? {} : { model }),
    ...(sessionId === undefined ? {} : { sessionId }),
    ...(tool === undefined ? {} : { tool }),
    ...(query === undefined ? {} : { query }),
  };
}

function optionalQuery(
  parameters: URLSearchParams,
  name: string,
  maximum: number,
): string | undefined | Error {
  const raw = parameters.get(name);
  if (raw === null) return undefined;
  const value = raw.trim();
  if (value.length === 0 || value.length > maximum) {
    return new TypeError(`${name} must be a non-empty value up to ${String(maximum)} characters`);
  }
  return value;
}

async function importTrace(
  request: IncomingMessage,
  response: ServerResponse,
  store: TraceStore,
): Promise<void> {
  const parsed = await readJsonRequest(request, response);
  if (parsed === undefined) return;
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    writeError(response, 400, "invalid_bundle", "Trace bundle must be an object");
    return;
  }
  const bundle = parsed as Record<string, unknown>;
  const trace = bundle.trace;
  if (
    bundle.format !== "causentra.trace-bundle" ||
    bundle.version !== 1 ||
    typeof trace !== "object" ||
    trace === null ||
    !("events" in trace) ||
    !Array.isArray(trace.events) ||
    trace.events.length === 0 ||
    trace.events.length > 10_000
  ) {
    writeError(response, 400, "invalid_bundle", "Trace bundle format or event list is invalid");
    return;
  }
  try {
    for (const event of trace.events) validateEvent(event);
  } catch (error) {
    if (error instanceof EventValidationError) {
      writeError(response, 400, "invalid_event", error.message, { field: error.field });
      return;
    }
    throw error;
  }
  const traceIds = new Set((trace.events as RuntimeEvent[]).map((event) => event.traceId));
  if (traceIds.size !== 1) {
    writeError(response, 400, "invalid_bundle", "A trace bundle must contain one trace ID");
    return;
  }
  const accepted = await store.append(trace.events as RuntimeEvent[]);
  writeJson(response, 202, {
    accepted,
    duplicates: trace.events.length - accepted,
    traceId: [...traceIds][0],
  });
}

async function pruneTraces(
  request: IncomingMessage,
  response: ServerResponse,
  store: TraceStore,
): Promise<void> {
  const parsed = await readJsonRequest(request, response);
  if (parsed === undefined) return;
  const keepLatest = typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
    ? (parsed as Record<string, unknown>).keepLatest
    : undefined;
  if (!Number.isSafeInteger(keepLatest) || (keepLatest as number) < 0) {
    writeError(response, 400, "invalid_retention", "keepLatest must be a non-negative integer");
    return;
  }
  const removed = await store.prune(keepLatest as number);
  writeJson(response, 200, { removed, remaining: store.traceCount() });
}

async function readJsonRequest(
  request: IncomingMessage,
  response: ServerResponse,
): Promise<unknown | undefined> {
  const contentType = request.headers["content-type"] ?? "";
  if (!contentType.toLowerCase().startsWith("application/json")) {
    writeError(response, 415, "unsupported_media_type", "Expected application/json");
    return undefined;
  }
  let body: string;
  try {
    body = await readBody(request);
  } catch (error) {
    if (error instanceof BodyTooLargeError) {
      writeError(response, 413, "body_too_large", error.message);
      return undefined;
    }
    throw error;
  }
  try {
    return JSON.parse(body) as unknown;
  } catch {
    writeError(response, 400, "invalid_json", "Request body is not valid JSON");
    return undefined;
  }
}

async function ingest(
  request: IncomingMessage,
  response: ServerResponse,
  store: TraceStore,
): Promise<void> {
  const contentType = request.headers["content-type"] ?? "";
  if (!contentType.toLowerCase().startsWith("application/json")) {
    writeError(response, 415, "unsupported_media_type", "Expected application/json");
    return;
  }
  let body: string;
  try {
    body = await readBody(request);
  } catch (error) {
    if (error instanceof BodyTooLargeError) {
      writeError(response, 413, "body_too_large", error.message);
      return;
    }
    throw error;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    writeError(response, 400, "invalid_json", "Request body is not valid JSON");
    return;
  }
  if (
    typeof parsed !== "object" ||
    parsed === null ||
    !("events" in parsed) ||
    !Array.isArray(parsed.events) ||
    parsed.events.length === 0 ||
    parsed.events.length > 1_000
  ) {
    writeError(
      response,
      400,
      "invalid_batch",
      "events must be an array containing 1 to 1000 events",
    );
    return;
  }
  try {
    for (const event of parsed.events) validateEvent(event);
  } catch (error) {
    if (error instanceof EventValidationError) {
      writeError(response, 400, "invalid_event", error.message, { field: error.field });
      return;
    }
    throw error;
  }
  const events = parsed.events as RuntimeEvent[];
  const accepted = await store.append(events);
  writeJson(response, 202, {
    accepted,
    duplicates: events.length - accepted,
  });
}

async function ingestOtlp(
  request: IncomingMessage,
  response: ServerResponse,
  store: TraceStore,
): Promise<void> {
  const contentType = String(request.headers["content-type"] ?? "")
    .split(";", 1)[0]
    ?.trim()
    .toLowerCase();
  if (contentType !== "application/json" && contentType !== "application/x-protobuf") {
    writeError(
      response,
      415,
      "unsupported_media_type",
      "OTLP traces require application/json or application/x-protobuf",
    );
    return;
  }
  let body: Buffer;
  try {
    body = await readBodyBuffer(request);
    const encoding = String(request.headers["content-encoding"] ?? "identity").toLowerCase();
    if (encoding === "gzip") body = gunzipSync(body, { maxOutputLength: MAX_BODY_BYTES });
    else if (encoding !== "identity" && encoding.length > 0) {
      writeError(response, 415, "unsupported_content_encoding", "Only identity and gzip are supported");
      return;
    }
    if (body.length > MAX_BODY_BYTES) throw new BodyTooLargeError(`Request exceeds ${MAX_BODY_BYTES} bytes`);
  } catch (error) {
    if (error instanceof BodyTooLargeError || isBufferTooLarge(error)) {
      writeError(response, 413, "body_too_large", `Request exceeds ${MAX_BODY_BYTES} bytes`);
      return;
    }
    writeError(response, 400, "invalid_compression", "OTLP request compression is invalid");
    return;
  }

  let document: unknown;
  try {
    document = contentType === "application/json"
      ? JSON.parse(body.toString("utf8")) as unknown
      : decodeOtlpProtobuf(body);
  } catch {
    writeError(response, 400, "invalid_otlp", "OTLP trace request is malformed");
    return;
  }
  const converted = convertOtlpTraces(document);
  if (converted.events.length > 20_000) {
    writeError(response, 413, "too_many_spans", "OTLP request exceeds 10000 spans");
    return;
  }
  if (converted.events.length > 0) await store.append(converted.events);
  if (contentType === "application/x-protobuf") {
    const encoded = encodeOtlpProtobufResponse(
      converted.rejectedSpans,
      converted.errorMessage,
    );
    response.writeHead(200, securityHeaders({ "content-type": contentType }));
    response.end(encoded);
    return;
  }
  writeJson(response, 200, converted.rejectedSpans === 0
    ? {}
    : {
        partialSuccess: {
          rejectedSpans: String(converted.rejectedSpans),
          errorMessage: converted.errorMessage,
        },
      });
}

async function readBody(request: IncomingMessage): Promise<string> {
  return (await readBodyBuffer(request)).toString("utf8");
}

function readBodyBuffer(request: IncomingMessage): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    let settled = false;
    request.on("data", (chunk: Buffer) => {
      if (settled) return;
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        settled = true;
        reject(new BodyTooLargeError(`Request exceeds ${MAX_BODY_BYTES} bytes`));
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => {
      if (!settled) resolve(Buffer.concat(chunks));
    });
    request.on("error", (error) => {
      if (!settled) reject(error);
    });
  });
}

function isBufferTooLarge(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error
    && error.code === "ERR_BUFFER_TOO_LARGE";
}

class BodyTooLargeError extends Error {}

function writeJson(response: ServerResponse, status: number, value: unknown): void {
  response.writeHead(
    status,
    securityHeaders({ "content-type": "application/json; charset=utf-8" }),
  );
  response.end(JSON.stringify(value));
}

function writeError(
  response: ServerResponse,
  status: number,
  code: string,
  message: string,
  details?: Readonly<Record<string, string>>,
): void {
  writeJson(response, status, {
    error: { code, message, ...(details === undefined ? {} : { details }) },
  });
}

function securityHeaders(
  headers: Readonly<Record<string, string>>,
): Readonly<Record<string, string>> {
  return {
    ...headers,
    "cache-control": "no-store",
    "content-security-policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
  };
}

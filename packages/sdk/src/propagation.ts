import type { TraceContext } from "./types.js";

const TRACE_ID_PATTERN = /^[0-9a-f]{32}$/u;
const SPAN_ID_PATTERN = /^[0-9a-f]{16}$/u;
const TRACEPARENT_PATTERN = /^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$/u;

/** String carrier suitable for HTTP, messaging, or job metadata. */
export type TraceCarrier = Readonly<Record<string, string | undefined>>;

/** Valid remote W3C parent extracted from a carrier. */
export interface PropagatedTraceContext {
  readonly traceId: string;
  readonly spanId: string;
  readonly traceFlags: number;
  readonly traceState?: string;
}

/** Injects a W3C `traceparent` and optional `tracestate` without mutating input. */
export function injectTraceContext(
  context: TraceContext,
  carrier: TraceCarrier = {},
  options: { readonly sampled?: boolean; readonly traceState?: string } = {},
): Record<string, string> {
  const spanId = context.spanId.slice(0, 16);
  if (!validTraceId(context.traceId) || !validSpanId(spanId)) {
    throw new TypeError("trace context contains invalid W3C identifiers");
  }
  const result = Object.fromEntries(
    Object.entries(carrier).filter((entry): entry is [string, string] => entry[1] !== undefined),
  );
  result.traceparent = `00-${context.traceId}-${spanId}-${options.sampled === false ? "00" : "01"}`;
  if (options.traceState !== undefined) result.tracestate = options.traceState;
  return result;
}

/** Extracts a strict W3C version-00 parent; malformed/all-zero values are ignored. */
export function extractTraceContext(
  carrier: TraceCarrier,
): PropagatedTraceContext | undefined {
  const traceparent = header(carrier, "traceparent")?.trim();
  if (traceparent === undefined) return undefined;
  const match = TRACEPARENT_PATTERN.exec(traceparent);
  if (match === null) return undefined;
  const [, traceId, spanId, flags] = match;
  if (traceId === undefined || spanId === undefined || flags === undefined) return undefined;
  if (!validTraceId(traceId) || !validSpanId(spanId)) return undefined;
  const traceFlags = Number.parseInt(flags, 16);
  return {
    traceId,
    spanId,
    traceFlags,
    ...(header(carrier, "tracestate") === undefined
      ? {}
      : { traceState: header(carrier, "tracestate") as string }),
  };
}

function header(carrier: TraceCarrier, name: string): string | undefined {
  const entry = Object.entries(carrier).find(([key]) => key.toLowerCase() === name);
  return entry?.[1];
}

function validTraceId(value: string): boolean {
  return TRACE_ID_PATTERN.test(value) && !/^0+$/u.test(value);
}

function validSpanId(value: string): boolean {
  return SPAN_ID_PATTERN.test(value) && !/^0+$/u.test(value);
}

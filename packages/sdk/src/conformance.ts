import type { RuntimeEvent, TraceContext } from "./types.js";
import { validateEvent } from "./validation.js";

/** Inputs for the framework-adapter conformance contract. */
export interface AdapterConformanceOptions {
  readonly events: readonly RuntimeEvent[];
  /** Exact value emitted in the portable `framework.name` attribute. */
  readonly frameworkName: string;
  /** Values that must never appear in the serialized event stream. */
  readonly forbiddenContent?: readonly string[];
  /** Canonical context that the framework execution was asked to join. */
  readonly parentContext?: TraceContext;
}

/** Machine-readable result returned by the adapter conformance verifier. */
export interface AdapterConformanceReport {
  readonly passed: boolean;
  readonly checks: readonly string[];
  readonly failures: readonly string[];
}

/**
 * Verifies the public contract expected from a completed framework-adapter run.
 * The function is side-effect free so adapter authors can use it in any test
 * runner without depending on Causentra internals.
 */
export function verifyAdapterConformance(
  options: AdapterConformanceOptions,
): AdapterConformanceReport {
  const checks: string[] = [];
  const failures: string[] = [];
  const events = options.events;

  check(events.length > 0, "emits at least one event", failures, checks);
  checkEveryEventValid(events, failures, checks);
  check(
    new Set(events.map((event) => event.eventId)).size === events.length,
    "uses unique event identifiers",
    failures,
    checks,
  );
  check(
    events.every((event) => event.attributes["framework.name"] === options.frameworkName),
    `identifies framework as ${options.frameworkName}`,
    failures,
    checks,
  );
  checkLifecyclePairs(events, failures, checks);
  checkForbiddenContent(events, options.forbiddenContent ?? [], failures, checks);
  if (options.parentContext !== undefined) {
    checkParentContext(events, options.parentContext, failures, checks);
  }

  return { passed: failures.length === 0, checks, failures };
}

/** Throws a concise test failure when an adapter violates the contract. */
export function assertAdapterConformance(options: AdapterConformanceOptions): void {
  const report = verifyAdapterConformance(options);
  if (!report.passed) {
    throw new Error(`Adapter conformance failed:\n- ${report.failures.join("\n- ")}`);
  }
}

function checkEveryEventValid(
  events: readonly RuntimeEvent[],
  failures: string[],
  checks: string[],
): void {
  const errors: string[] = [];
  for (const [index, event] of events.entries()) {
    try {
      validateEvent(event);
    } catch (error) {
      errors.push(`event ${index}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  check(errors.length === 0, "emits schema-valid events", failures, checks, errors.join("; "));
}

function checkLifecyclePairs(
  events: readonly RuntimeEvent[],
  failures: string[],
  checks: string[],
): void {
  const lifecycle = new Map<string, { starts: number; ends: number }>();
  for (const event of events) {
    const phase = lifecyclePhase(event.type);
    if (phase === undefined) continue;
    const value = lifecycle.get(event.spanId) ?? { starts: 0, ends: 0 };
    value[phase] += 1;
    lifecycle.set(event.spanId, value);
  }
  const invalid = [...lifecycle.entries()]
    .filter(([, value]) => value.starts !== 1 || value.ends !== 1)
    .map(([spanId, value]) => `${spanId} has ${value.starts} start(s), ${value.ends} end(s)`);
  check(
    lifecycle.size > 0 && invalid.length === 0,
    "pairs every completed lifecycle exactly once",
    failures,
    checks,
    invalid.length === 0 ? "no lifecycle events found" : invalid.join("; "),
  );
}

function checkForbiddenContent(
  events: readonly RuntimeEvent[],
  forbidden: readonly string[],
  failures: string[],
  checks: string[],
): void {
  const serialized = JSON.stringify(events);
  const exposed = forbidden.filter((value) => value.length > 0 && serialized.includes(value));
  check(
    exposed.length === 0,
    "excludes declared private payloads",
    failures,
    checks,
    exposed.length === 0 ? undefined : `found ${exposed.length} forbidden value(s)`,
  );
}

function checkParentContext(
  events: readonly RuntimeEvent[],
  parent: TraceContext,
  failures: string[],
  checks: string[],
): void {
  check(
    events.every((event) => event.traceId === parent.traceId),
    "preserves the canonical parent trace identifier",
    failures,
    checks,
  );
  check(
    events.some((event) => event.parentSpanId === parent.spanId),
    "links a framework root to the canonical parent span",
    failures,
    checks,
  );
  if (parent.sessionId !== undefined) {
    check(
      events.every((event) => event.sessionId === parent.sessionId),
      "inherits the canonical session identifier",
      failures,
      checks,
    );
  }
}

function lifecyclePhase(type: RuntimeEvent["type"]): "starts" | "ends" | undefined {
  if (type.endsWith(".start")) return "starts";
  if (type.endsWith(".end")) return "ends";
  return undefined;
}

function check(
  passed: boolean,
  name: string,
  failures: string[],
  checks: string[],
  detail?: string,
): void {
  checks.push(name);
  if (!passed) failures.push(detail === undefined ? name : `${name}: ${detail}`);
}

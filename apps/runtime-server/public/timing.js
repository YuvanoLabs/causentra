/**
 * Derive truthful wall-time coverage from completed model/tool spans.
 * Missing ends, durations, or timestamps make the affected result unknown.
 */
export function deriveTimingBreakdown(summary, events) {
  const traceWallMs = finiteDuration(summary?.durationMs) ? summary.durationMs : undefined;
  const starts = events.filter((event) => event.type === "model.start" || event.type === "tool.start");
  const ends = new Map(
    events
      .filter((event) => event.type === "model.end" || event.type === "tool.end")
      .map((event) => [event.spanId, event]),
  );
  const intervals = [];
  const categories = { model: [], tool: [] };
  for (const start of starts) {
    const family = start.type.slice(0, -".start".length);
    const end = ends.get(start.spanId);
    const duration = end?.durationMs;
    const startMs = Date.parse(start.timestamp);
    const endMs = end === undefined ? NaN : Date.parse(end.timestamp);
    const complete = end !== undefined
      && finiteDuration(duration)
      && Number.isFinite(startMs)
      && Number.isFinite(endMs)
      && endMs >= startMs;
    categories[family].push({ complete, duration: complete ? duration : undefined });
    if (complete) intervals.push({ startMs, endMs });
  }
  const model = categoryResult(categories.model);
  const tool = categoryResult(categories.tool);
  const unionWallMs = starts.length === 0
    ? 0
    : intervals.length === starts.length
      ? intervalUnion(intervals)
      : undefined;
  const categorySumMs = model.durationMs === undefined || tool.durationMs === undefined
    ? undefined
    : model.durationMs + tool.durationMs;
  const overlap = categorySumMs !== undefined
    && unionWallMs !== undefined
    && categorySumMs > unionWallMs + 0.001;
  return {
    traceWallMs,
    model,
    tool,
    unionWallMs,
    unattributedWallMs: traceWallMs === undefined || unionWallMs === undefined
      ? undefined
      : Math.max(0, traceWallMs - unionWallMs),
    overlap,
  };
}

function categoryResult(values) {
  const incomplete = values.some((value) => !value.complete);
  return {
    durationMs: incomplete ? undefined : values.reduce((sum, value) => sum + (value.duration ?? 0), 0),
    completedCount: values.filter((value) => value.complete).length,
    incomplete,
  };
}

function intervalUnion(intervals) {
  const sorted = [...intervals].sort((left, right) => left.startMs - right.startMs);
  let total = 0;
  let start = sorted[0].startMs;
  let end = sorted[0].endMs;
  for (const interval of sorted.slice(1)) {
    if (interval.startMs > end) {
      total += end - start;
      start = interval.startMs;
      end = interval.endMs;
    } else {
      end = Math.max(end, interval.endMs);
    }
  }
  return total + end - start;
}

function finiteDuration(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

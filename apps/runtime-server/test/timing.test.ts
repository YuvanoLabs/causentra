import assert from "node:assert/strict";
import test from "node:test";
// @ts-expect-error Browser-only public module intentionally lives outside the TS build.
import { deriveTimingBreakdown } from "../../public/timing.js";

const event = (type: string, spanId: string, timestamp: string, durationMs?: number) => ({
  type,
  spanId,
  timestamp,
  ...(durationMs === undefined ? {} : { durationMs }),
});

test("timing sums completed categories and unions overlapping intervals", () => {
  const result = deriveTimingBreakdown(
    { durationMs: 100 },
    [
      event("model.start", "m", "2026-01-01T00:00:00.000Z"),
      event("model.end", "m", "2026-01-01T00:00:00.050Z", 50),
      event("tool.start", "t", "2026-01-01T00:00:00.030Z"),
      event("tool.end", "t", "2026-01-01T00:00:00.080Z", 50),
    ],
  );
  assert.equal(result.model.durationMs, 50);
  assert.equal(result.tool.durationMs, 50);
  assert.equal(result.unionWallMs, 80);
  assert.equal(result.unattributedWallMs, 20);
  assert.equal(result.overlap, true);
});

test("incomplete spans make category and derived coverage explicitly unknown", () => {
  const result = deriveTimingBreakdown(
    { durationMs: 100 },
    [event("model.start", "m", "2026-01-01T00:00:00.000Z")],
  );
  assert.equal(result.model.durationMs, undefined);
  assert.equal(result.model.incomplete, true);
  assert.equal(result.unionWallMs, undefined);
  assert.equal(result.unattributedWallMs, undefined);
});

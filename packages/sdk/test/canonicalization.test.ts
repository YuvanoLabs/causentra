import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { canonicalizeJson } from "../src/index.js";
import type { JsonValue } from "../src/types.js";

interface Vector {
  readonly name: string;
  readonly input: JsonValue;
  readonly canonical: string;
  readonly sha256: string;
}

test("RFC 8785 vectors produce byte-identical UTF-8 and SHA-256 output", async () => {
  const path = new URL("../../fixtures/signature/v1/canonicalization/vectors.json", import.meta.url);
  const vectors = JSON.parse(await readFile(path, "utf8")) as Vector[];
  for (const vector of vectors) {
    const bytes = canonicalizeJson(vector.input);
    assert.equal(new TextDecoder().decode(bytes), vector.canonical, vector.name);
    assert.equal(createHash("sha256").update(bytes).digest("hex"), vector.sha256, vector.name);
  }
});

test("canonicalizer rejects values outside the interoperable JSON domain", () => {
  assert.throws(() => canonicalizeJson(Number.NaN), /non-finite/u);
  assert.throws(() => canonicalizeJson(Number.MAX_SAFE_INTEGER + 1), /safe range/u);
  assert.throws(() => canonicalizeJson(undefined as never), /JSON (domain|value)/u);
  assert.throws(() => canonicalizeJson(new Date() as never), /plain JSON object/u);
});

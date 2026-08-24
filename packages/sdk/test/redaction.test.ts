import assert from "node:assert/strict";
import test from "node:test";
import {
  CausentraRuntime,
  MemoryExporter,
  createPolicyRedactor,
  defaultRedactor,
} from "../src/index.js";

test("policy redacts nested values and composes sensitive-key redaction", () => {
  const source = {
    password: "still-secret",
    nested: [
      "email alice@example.com",
      { card: "4111 1111 1111 1111", pan: "ABCDE1234F" },
    ],
  };

  assert.deepEqual(createPolicyRedactor()(source), {
    password: "[REDACTED]",
    nested: [
      "email [REDACTED]",
      { card: "[REDACTED]", pan: "[REDACTED]" },
    ],
  });
  assert.equal(source.password, "still-secret");
});

test("policy preserves detector false-positive boundaries and punctuation", () => {
  const value = {
    invalidCard: "4111 1111 1111 1112",
    embeddedPan: "XABCDE1234FY",
    emailLike: "alice@example",
    ordinary: "a 1234567890123456 b",
    punctuation: "Contact alice@example.com.",
  };

  assert.deepEqual(createPolicyRedactor()(value), {
    ...value,
    punctuation: "Contact [REDACTED].",
  });
});

test("policy supports individual detector toggles", () => {
  assert.deepEqual(
    createPolicyRedactor({ redactEmails: false })({
      email: "alice@example.com",
      pan: "ABCDE1234F",
    }),
    { email: "alice@example.com", pan: "[REDACTED]" },
  );
});

test("policy runs before the memory exporter receives data", async () => {
  const exporter = new MemoryExporter();
  const runtime = new CausentraRuntime({
    serviceName: "redaction-test",
    exporter,
    redactor: createPolicyRedactor(),
  });

  await runtime.trace("workflow", async () => undefined, {
    contact: "alice@example.com",
  });

  assert.equal(exporter.events[0]?.attributes.contact, "[REDACTED]");
  assert.equal(defaultRedactor({ contact: "alice@example.com" }).contact, "alice@example.com");
});

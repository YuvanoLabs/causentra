import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import test from "node:test";
import {
  signDetachedArtifact,
  verifyDetachedSignature,
  type DetachedArtifact,
} from "../src/index.js";

const artifact: DetachedArtifact = {
  kind: "trace-bundle",
  identity: "trace:test-signature",
  schemaVersion: "1.0",
  value: { message: "safe", nested: [1, true, null] },
};

function keys() {
  return generateKeyPairSync("ec", { namedCurve: "prime256v1" });
}

test("signs and verifies an ECDSA P-256 detached artifact", async () => {
  const pair = keys();
  const envelope = signDetachedArtifact({
    artifact,
    keyId: "local:test-key",
    keyVersion: "1",
    privateKey: pair.privateKey,
  });
  assert.equal(envelope.algorithm, "ECDSA_P256_SHA256");
  assert.equal(envelope.signatureEncoding, "base64-der");
  assert.equal(JSON.stringify(envelope).includes("BEGIN PRIVATE KEY"), false);
  const result = await verifyDetachedSignature({
    artifact,
    envelope,
    resolveKey: async (keyId, keyVersion) =>
      keyId === "local:test-key" && keyVersion === "1" ? { publicKey: pair.publicKey } : undefined,
  });
  assert.deepEqual(result, { verified: true, keyId: "local:test-key", keyVersion: "1" });
});

test("rejects tampering, wrong keys, unknown keys, and revoked keys", async () => {
  const pair = keys();
  const wrongPair = keys();
  const envelope = signDetachedArtifact({
    artifact,
    keyId: "local:test-key",
    keyVersion: "1",
    privateKey: pair.privateKey,
  });
  const tamperedArtifact = { ...artifact, value: { message: "tampered" } };
  const tampered = await verifyDetachedSignature({
    artifact: tamperedArtifact,
    envelope,
    resolveKey: () => ({ publicKey: pair.publicKey }),
  });
  assert.deepEqual(tampered, { verified: false, reason: "artifact-digest-mismatch" });
  const wrong = await verifyDetachedSignature({
    artifact,
    envelope,
    resolveKey: () => ({ publicKey: wrongPair.publicKey }),
  });
  assert.deepEqual(wrong, { verified: false, reason: "invalid-signature" });
  const unknown = await verifyDetachedSignature({ artifact, envelope, resolveKey: () => undefined });
  assert.deepEqual(unknown, { verified: false, reason: "unknown-key" });
  const revoked = await verifyDetachedSignature({
    artifact,
    envelope,
    resolveKey: () => ({ publicKey: pair.publicKey, revoked: true }),
  });
  assert.deepEqual(revoked, { verified: false, reason: "revoked-key" });
});

test("rejects malformed or unsupported envelopes fail-closed", async () => {
  const result = await verifyDetachedSignature({
    artifact,
    envelope: { signatureVersion: "causentra.signature/v1" },
    resolveKey: () => undefined,
  });
  assert.deepEqual(result, { verified: false, reason: "malformed-envelope" });
});

test("rejects non-P-256 private keys before producing an envelope", () => {
  const pair = generateKeyPairSync("rsa", { modulusLength: 2048 });
  assert.throws(
    () => signDetachedArtifact({ artifact, keyId: "local:rsa", keyVersion: "1", privateKey: pair.privateKey }),
    /EC P-256/u,
  );
});
test("distinguishes supported-schema algorithms and encodings", async () => {
  const pair = keys();
  const envelope = signDetachedArtifact({ artifact, keyId: "local:test-key", keyVersion: "1", privateKey: pair.privateKey });
  const ed25519 = { ...envelope, algorithm: "ED25519", signatureEncoding: "base64-raw" };
  assert.deepEqual(await verifyDetachedSignature({ artifact, envelope: ed25519, resolveKey: () => ({ publicKey: pair.publicKey }) }), { verified: false, reason: "unsupported-algorithm" });
  const wrongEncoding = { ...envelope, signatureEncoding: "base64-raw" };
  assert.deepEqual(await verifyDetachedSignature({ artifact, envelope: wrongEncoding, resolveKey: () => ({ publicKey: pair.publicKey }) }), { verified: false, reason: "unsupported-encoding" });
});

test("rejects extra properties and non-canonical Base64", async () => {
  const pair = keys();
  const envelope = signDetachedArtifact({ artifact, keyId: "local:test-key", keyVersion: "1", privateKey: pair.privateKey });
  const extra = { ...envelope, extra: true };
  assert.deepEqual(await verifyDetachedSignature({ artifact, envelope: extra, resolveKey: () => ({ publicKey: pair.publicKey }) }), { verified: false, reason: "malformed-envelope" });
  const nestedExtra = { ...envelope, artifact: { ...envelope.artifact, extra: true } };
  assert.deepEqual(await verifyDetachedSignature({ artifact, envelope: nestedExtra, resolveKey: () => ({ publicKey: pair.publicKey }) }), { verified: false, reason: "malformed-envelope" });
  const badBase64 = { ...envelope, signature: `${envelope.signature.slice(0, -1)}!` };
  assert.deepEqual(await verifyDetachedSignature({ artifact, envelope: badBase64, resolveKey: () => ({ publicKey: pair.publicKey }) }), { verified: false, reason: "malformed-envelope" });
});

test("rejects runtime-invalid artifact kinds and private verification keys", async () => {
  const pair = keys();
  const envelope = signDetachedArtifact({ artifact, keyId: "local:test-key", keyVersion: "1", privateKey: pair.privateKey });
  const invalidKind = { ...artifact, kind: "not-a-kind" };
  assert.throws(() => signDetachedArtifact({ artifact: invalidKind as never, keyId: "local:test-key", keyVersion: "1", privateKey: pair.privateKey }), /unsupported artifact kind/u);
  const privateKey = await verifyDetachedSignature({ artifact, envelope, resolveKey: () => ({ publicKey: pair.privateKey }) });
  assert.deepEqual(privateKey, { verified: false, reason: "invalid-key" });
});

test("metadata tampering fails even when the resolver returns a key", async () => {
  const pair = keys();
  const envelope = signDetachedArtifact({ artifact, keyId: "local:test-key", keyVersion: "1", privateKey: pair.privateKey });
  const tampered = { ...envelope, keyVersion: "2" };
  assert.deepEqual(await verifyDetachedSignature({ artifact, envelope: tampered, resolveKey: () => ({ publicKey: pair.publicKey }) }), { verified: false, reason: "invalid-signature" });
});
test("rejects public keys passed to signing", () => {
  const pair = keys();
  assert.throws(
    () => signDetachedArtifact({ artifact, keyId: "local:public", keyVersion: "1", privateKey: pair.publicKey }),
    /EC P-256/u,
  );
});

test("rejects inherited or custom-prototype envelopes and artifacts", async () => {
  const pair = keys();
  const envelope = signDetachedArtifact({ artifact, keyId: "local:test-key", keyVersion: "1", privateKey: pair.privateKey });
  const inherited = Object.create(envelope);
  assert.deepEqual(await verifyDetachedSignature({ artifact, envelope: inherited, resolveKey: () => ({ publicKey: pair.publicKey }) }), { verified: false, reason: "malformed-envelope" });
  const customArtifact = Object.assign(Object.create({ inherited: true }), envelope.artifact);
  const nested = { ...envelope, artifact: customArtifact };
  assert.deepEqual(await verifyDetachedSignature({ artifact, envelope: nested, resolveKey: () => ({ publicKey: pair.publicKey }) }), { verified: false, reason: "malformed-envelope" });
});
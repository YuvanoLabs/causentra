import {
  createHash,
  createPrivateKey,
  createPublicKey,
  createSign,
  createVerify,
  type KeyLike,
  KeyObject,
} from "node:crypto";
import { canonicalizeJson } from "./canonicalization.js";
import type { JsonValue } from "./types.js";

export type SignatureAlgorithm = "ECDSA_P256_SHA256";
export type SignatureEncoding = "base64-der";

type ParsedSignatureEnvelope = Omit<DetachedSignatureEnvelope, "algorithm" | "signatureEncoding"> & {
  readonly algorithm: string;
  readonly signatureEncoding: string;
};
export type SignatureArtifactKind = "event-batch" | "trace-bundle";

export interface DetachedArtifact {
  readonly kind: SignatureArtifactKind;
  readonly identity: string;
  readonly schemaVersion: "1.0";
  readonly value: JsonValue;
}

export interface DetachedSignatureEnvelope {
  readonly signatureVersion: "causentra.signature/v1";
  readonly artifact: {
    readonly kind: SignatureArtifactKind;
    readonly identity: string;
    readonly schemaVersion: "1.0";
    readonly sha256: string;
  };
  readonly canonicalization: "RFC8785-JCS";
  readonly algorithm: SignatureAlgorithm;
  readonly keyId: string;
  readonly keyVersion: string;
  readonly signatureEncoding: SignatureEncoding;
  readonly signature: string;
}

export interface DetachedSigningOptions {
  readonly artifact: DetachedArtifact;
  readonly keyId: string;
  readonly keyVersion: string;
  readonly privateKey: KeyLike;
}

export interface VerificationKey {
  readonly publicKey: KeyLike;
  readonly revoked?: boolean;
}

export type SignatureKeyResolver = (
  keyId: string,
  keyVersion: string,
) => VerificationKey | undefined | Promise<VerificationKey | undefined>;

export interface DetachedVerificationOptions {
  readonly artifact: DetachedArtifact;
  readonly envelope: unknown;
  readonly resolveKey: SignatureKeyResolver;
}

export type SignatureVerificationFailure =
  | "malformed-envelope"
  | "unsupported-algorithm"
  | "unsupported-encoding"
  | "artifact-digest-mismatch"
  | "unknown-key"
  | "revoked-key"
  | "invalid-key"
  | "invalid-signature"
  | "key-resolution-failed";

export type SignatureVerificationResult =
  | { readonly verified: true; readonly keyId: string; readonly keyVersion: string }
  | { readonly verified: false; readonly reason: SignatureVerificationFailure };

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/u;
const VERSION_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/u;

export function signDetachedArtifact(options: DetachedSigningOptions): DetachedSignatureEnvelope {
  validateArtifact(options.artifact);
  validateIdentity(options.keyId, ID_PATTERN, "key ID");
  validateIdentity(options.keyVersion, VERSION_PATTERN, "key version");
  const privateKey = validatePrivateKey(options.privateKey);
  const digest = digestArtifact(options.artifact.value);
  const descriptor = createDescriptor(options.artifact, digest, options.keyId, options.keyVersion);
  const signer = createSign("SHA256");
  signer.update(canonicalizeJson(descriptor));
  signer.end();
  const signature = signer.sign({ key: privateKey, dsaEncoding: "der" }).toString("base64");
  return {
    signatureVersion: "causentra.signature/v1",
    artifact: {
      kind: options.artifact.kind,
      identity: options.artifact.identity,
      schemaVersion: options.artifact.schemaVersion,
      sha256: digest,
    },
    canonicalization: "RFC8785-JCS",
    algorithm: "ECDSA_P256_SHA256",
    keyId: options.keyId,
    keyVersion: options.keyVersion,
    signatureEncoding: "base64-der",
    signature,
  };
}

export async function verifyDetachedSignature(
  options: DetachedVerificationOptions,
): Promise<SignatureVerificationResult> {
  try {
    validateArtifact(options.artifact);
    const envelope = parseEnvelope(options.envelope);
    if (envelope === undefined) return { verified: false, reason: "malformed-envelope" };
    if (envelope.algorithm !== "ECDSA_P256_SHA256") {
      return { verified: false, reason: "unsupported-algorithm" };
    }
    if (envelope.signatureEncoding !== "base64-der") {
      return { verified: false, reason: "unsupported-encoding" };
    }
    const digest = digestArtifact(options.artifact.value);
    if (digest !== envelope.artifact.sha256) {
      return { verified: false, reason: "artifact-digest-mismatch" };
    }
    if (
      envelope.artifact.kind !== options.artifact.kind ||
      envelope.artifact.identity !== options.artifact.identity ||
      envelope.artifact.schemaVersion !== options.artifact.schemaVersion
    ) {
      return { verified: false, reason: "artifact-digest-mismatch" };
    }
    let key: VerificationKey | undefined;
    try {
      key = await options.resolveKey(envelope.keyId, envelope.keyVersion);
    } catch {
      return { verified: false, reason: "key-resolution-failed" };
    }
    if (key === undefined) return { verified: false, reason: "unknown-key" };
    if (key.revoked === true) return { verified: false, reason: "revoked-key" };
    let publicKey: KeyObject;
    try {
      publicKey = validatePublicKey(key.publicKey);
    } catch {
      return { verified: false, reason: "invalid-key" };
    }
    const verifier = createVerify("SHA256");
    verifier.update(canonicalizeJson(envelopeDescriptor(envelope)));
    verifier.end();
    const valid = verifier.verify({ key: publicKey, dsaEncoding: "der" }, decodeSignature(envelope.signature)!);
    return valid
      ? { verified: true, keyId: envelope.keyId, keyVersion: envelope.keyVersion }
      : { verified: false, reason: "invalid-signature" };
  } catch (error) {
    if (error instanceof TypeError || error instanceof RangeError) {
      return { verified: false, reason: "malformed-envelope" };
    }
    return { verified: false, reason: "invalid-key" };
  }
}

function digestArtifact(value: JsonValue): string {
  return createHash("sha256").update(canonicalizeJson(value)).digest("hex");
}

function createDescriptor(
  artifact: DetachedArtifact,
  digest: string,
  keyId: string,
  keyVersion: string,
): JsonValue {
  return {
    signatureVersion: "causentra.signature/v1",
    artifact: {
      kind: artifact.kind,
      identity: artifact.identity,
      schemaVersion: artifact.schemaVersion,
      sha256: digest,
    },
    canonicalization: "RFC8785-JCS",
    algorithm: "ECDSA_P256_SHA256",
    keyId,
    keyVersion,
    signatureEncoding: "base64-der",
  };
}

function envelopeDescriptor(envelope: ParsedSignatureEnvelope): JsonValue {
  return {
    signatureVersion: envelope.signatureVersion,
    artifact: envelope.artifact,
    canonicalization: envelope.canonicalization,
    algorithm: envelope.algorithm,
    keyId: envelope.keyId,
    keyVersion: envelope.keyVersion,
    signatureEncoding: envelope.signatureEncoding,
  };
}

function validateArtifact(artifact: DetachedArtifact): void {
  if (!ID_PATTERN.test(artifact.identity)) throw new TypeError("invalid artifact identity");
  if (artifact.schemaVersion !== "1.0") throw new TypeError("unsupported artifact schema");
  if (artifact.kind !== "event-batch" && artifact.kind !== "trace-bundle") throw new TypeError("unsupported artifact kind");
  canonicalizeJson(artifact.value);
}

function validateIdentity(value: string, pattern: RegExp, label: string): void {
  if (!pattern.test(value)) throw new TypeError(`invalid ${label}`);
}

function validatePrivateKey(key: KeyLike): KeyObject {
  const privateKey = key instanceof KeyObject ? key : createPrivateKey(key);
  if (privateKey.type !== "private" || privateKey.asymmetricKeyType !== "ec" || privateKey.asymmetricKeyDetails?.namedCurve !== "prime256v1") {
    throw new TypeError("private key must be an EC P-256 key");
  }
  return privateKey;
}

function validatePublicKey(key: KeyLike): KeyObject {
  if (key instanceof KeyObject) {
    if (key.type !== "public") throw new TypeError("verifier key must be public");
    return validateP256PublicKey(key);
  }
  try {
    createPrivateKey(key);
    throw new TypeError("verifier key must be public");
  } catch (error) {
    if (error instanceof TypeError && error.message === "verifier key must be public") throw error;
  }
  return validateP256PublicKey(createPublicKey(key));
}

function validateP256PublicKey(publicKey: KeyObject): KeyObject {
  if (publicKey.type !== "public" || publicKey.asymmetricKeyType !== "ec" || publicKey.asymmetricKeyDetails?.namedCurve !== "prime256v1") {
    throw new TypeError("public key must be an EC P-256 key");
  }
  return publicKey;
}
function parseEnvelope(value: unknown): ParsedSignatureEnvelope | undefined {
  if (!isPlainObject(value)) return undefined;
  const candidate = value as Record<string, unknown>;
  if (!hasOnlyKeys(candidate, ["signatureVersion", "artifact", "canonicalization", "algorithm", "keyId", "keyVersion", "signatureEncoding", "signature"])) return undefined;
  if (
    candidate.signatureVersion !== "causentra.signature/v1" ||
    candidate.canonicalization !== "RFC8785-JCS" ||
    typeof candidate.algorithm !== "string" ||
    typeof candidate.signatureEncoding !== "string" ||
    typeof candidate.keyId !== "string" ||
    typeof candidate.keyVersion !== "string" ||
    typeof candidate.signature !== "string" ||
    decodeSignature(candidate.signature) === undefined
  ) return undefined;
  const artifact = candidate.artifact;
  if (!isPlainObject(artifact)) return undefined;
  const descriptor = artifact as Record<string, unknown>;
  if (!hasOnlyKeys(descriptor, ["kind", "identity", "schemaVersion", "sha256"])) return undefined;
  if (
    (descriptor.kind !== "event-batch" && descriptor.kind !== "trace-bundle") ||
    typeof descriptor.identity !== "string" ||
    descriptor.schemaVersion !== "1.0" ||
    typeof descriptor.sha256 !== "string" ||
    !/^[0-9a-f]{64}$/u.test(descriptor.sha256) ||
    !ID_PATTERN.test(candidate.keyId) ||
    !VERSION_PATTERN.test(candidate.keyVersion)
  ) return undefined;
  return value as ParsedSignatureEnvelope;
}

function decodeSignature(value: string): Buffer | undefined {
  if (value.length < 4 || value.length > 2048 || value.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/u.test(value)) return undefined;
  const decoded = Buffer.from(value, "base64");
  return decoded.length > 0 && decoded.toString("base64") === value ? decoded : undefined;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}
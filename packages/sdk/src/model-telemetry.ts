import type { EventAttributes } from "./types.js";

/** Current well-known provider identifiers from OpenTelemetry GenAI conventions. */
export const WELL_KNOWN_GENAI_PROVIDERS = [
  "anthropic",
  "aws.bedrock",
  "azure.ai.inference",
  "azure.ai.openai",
  "cohere",
  "deepseek",
  "gcp.gemini",
  "gcp.gen_ai",
  "gcp.vertex_ai",
  "groq",
  "ibm.watsonx.ai",
  "mistral_ai",
  "openai",
  "perplexity",
  "x_ai",
] as const;

export type WellKnownGenAiProvider = (typeof WELL_KNOWN_GENAI_PROVIDERS)[number];

const PROVIDER_ALIASES: Readonly<Record<string, WellKnownGenAiProvider>> = {
  bedrock: "aws.bedrock",
  gemini: "gcp.gemini",
  google: "gcp.gen_ai",
  "google-genai": "gcp.gen_ai",
  "vertex-ai": "gcp.vertex_ai",
  "azure-openai": "azure.ai.openai",
  mistral: "mistral_ai",
  xai: "x_ai",
};

/** Explicitly canonicalizes common aliases without rejecting custom providers. */
export function normalizeGenAiProviderName(provider: string): string {
  const normalized = provider.trim().toLowerCase();
  if (normalized.length === 0 || normalized.length > 256) {
    throw new TypeError("provider must be a non-empty string up to 256 characters");
  }
  return PROVIDER_ALIASES[normalized] ?? normalized;
}

/** How a monetary value was obtained; Causentra never guesses silently. */
export type CostBasis = "provider_reported" | "catalog_estimate" | "user_supplied";

/** Provider-neutral model operation facts using current OTel GenAI vocabulary. */
export interface ModelTelemetry {
  readonly providerName?: string;
  readonly requestModel?: string;
  readonly responseModel?: string;
  readonly inputTokens?: number;
  readonly outputTokens?: number;
  readonly cacheReadInputTokens?: number;
  /** Total operation cost in USD. Pricing lookup is deliberately caller-owned. */
  readonly costUsd?: number;
  /** Required whenever costUsd is present. */
  readonly costBasis?: CostBasis;
}

/**
 * Builds a consistent, validated model/provider/usage attribute set. Missing
 * facts remain absent (unknown); cost values always carry explicit provenance.
 */
export function createModelTelemetryAttributes(
  telemetry: ModelTelemetry,
): EventAttributes {
  optionalName(telemetry.providerName, "providerName");
  optionalName(telemetry.requestModel, "requestModel");
  optionalName(telemetry.responseModel, "responseModel");
  optionalCount(telemetry.inputTokens, "inputTokens");
  optionalCount(telemetry.outputTokens, "outputTokens");
  optionalCount(telemetry.cacheReadInputTokens, "cacheReadInputTokens");
  if (telemetry.costUsd !== undefined) {
    if (!Number.isFinite(telemetry.costUsd) || telemetry.costUsd < 0) {
      throw new RangeError("costUsd must be a finite non-negative number");
    }
    if (telemetry.costBasis === undefined) {
      throw new TypeError("costBasis is required when costUsd is provided");
    }
  } else if (telemetry.costBasis !== undefined) {
    throw new TypeError("costBasis cannot be provided without costUsd");
  }
  return {
    ...(telemetry.providerName === undefined
      ? {}
      : { "gen_ai.provider.name": normalizeGenAiProviderName(telemetry.providerName) }),
    ...(telemetry.requestModel === undefined
      ? {}
      : { "gen_ai.request.model": telemetry.requestModel }),
    ...(telemetry.responseModel === undefined
      ? {}
      : { "gen_ai.response.model": telemetry.responseModel }),
    ...(telemetry.inputTokens === undefined
      ? {}
      : { "gen_ai.usage.input_tokens": telemetry.inputTokens }),
    ...(telemetry.outputTokens === undefined
      ? {}
      : { "gen_ai.usage.output_tokens": telemetry.outputTokens }),
    ...(telemetry.cacheReadInputTokens === undefined
      ? {}
      : { "gen_ai.usage.cache_read.input_tokens": telemetry.cacheReadInputTokens }),
    ...(telemetry.costUsd === undefined
      ? {}
      : {
          "causentra.cost.usd": telemetry.costUsd,
          "causentra.cost.basis": telemetry.costBasis as CostBasis,
        }),
  };
}

function optionalName(value: string | undefined, field: string): void {
  if (value !== undefined && (value.trim().length === 0 || value.length > 256)) {
    throw new TypeError(`${field} must be a non-empty string up to 256 characters`);
  }
}

function optionalCount(value: number | undefined, field: string): void {
  if (value !== undefined && (!Number.isSafeInteger(value) || value < 0)) {
    throw new RangeError(`${field} must be a non-negative safe integer`);
  }
}

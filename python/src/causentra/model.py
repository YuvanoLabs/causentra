"""Provider-neutral model, usage, and cost vocabulary."""

from __future__ import annotations

import math
from typing import Literal

from .types import EventAttributes

WELL_KNOWN_GENAI_PROVIDERS = (
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
)

_ALIASES = {
    "bedrock": "aws.bedrock",
    "aws-bedrock": "aws.bedrock",
    "amazon-bedrock": "aws.bedrock",
    "gemini": "gcp.gemini",
    "google-gemini": "gcp.gemini",
    "google": "gcp.gen_ai",
    "google-genai": "gcp.gen_ai",
    "google-gen-ai": "gcp.gen_ai",
    "vertex-ai": "gcp.vertex_ai",
    "vertex": "gcp.vertex_ai",
    "vertexai": "gcp.vertex_ai",
    "azure-openai": "azure.ai.openai",
    "azure_openai": "azure.ai.openai",
    "azure-ai-inference": "azure.ai.inference",
    "azure-inference": "azure.ai.inference",
    "mistral": "mistral_ai",
    "mistralai": "mistral_ai",
    "watsonx": "ibm.watsonx.ai",
    "watsonx.ai": "ibm.watsonx.ai",
    "ibm-watsonx": "ibm.watsonx.ai",
    "deepseek-ai": "deepseek",
    "xai": "x_ai",
    "x-ai": "x_ai",
    "grok": "x_ai",
}

CostBasis = Literal["provider_reported", "catalog_estimate", "user_supplied"]
_COST_BASES = frozenset(("provider_reported", "catalog_estimate", "user_supplied"))


def normalize_provider_name(provider: str) -> str:
    """Canonicalize common aliases while preserving valid custom providers."""

    normalized = provider.strip().lower()
    if not normalized or len(normalized) > 256:
        raise ValueError("provider_name must be non-empty and at most 256 characters")
    return _ALIASES.get(normalized, normalized)


def model_attributes(
    *,
    provider_name: str | None = None,
    request_model: str | None = None,
    response_model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_input_tokens: int | None = None,
    cost_usd: float | None = None,
    cost_basis: CostBasis | None = None,
) -> EventAttributes:
    """Build canonical GenAI attributes without guessing missing facts or price."""

    result: EventAttributes = {}
    if provider_name is not None:
        result["gen_ai.provider.name"] = normalize_provider_name(provider_name)
    for model_value, field, key in (
        (request_model, "request_model", "gen_ai.request.model"),
        (response_model, "response_model", "gen_ai.response.model"),
    ):
        if model_value is not None:
            if not model_value.strip() or len(model_value) > 256:
                raise ValueError(f"{field} must be non-empty and at most 256 characters")
            result[key] = model_value
    for token_value, field, key in (
        (input_tokens, "input_tokens", "gen_ai.usage.input_tokens"),
        (output_tokens, "output_tokens", "gen_ai.usage.output_tokens"),
        (
            cache_read_input_tokens,
            "cache_read_input_tokens",
            "gen_ai.usage.cache_read.input_tokens",
        ),
    ):
        if token_value is not None:
            if isinstance(token_value, bool) or not isinstance(token_value, int) or token_value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
            result[key] = token_value
    if cost_usd is not None:
        if (
            isinstance(cost_usd, bool)
            or not isinstance(cost_usd, int | float)
            or not math.isfinite(cost_usd)
            or cost_usd < 0
        ):
            raise ValueError("cost_usd must be a finite non-negative number")
        if cost_basis not in _COST_BASES:
            raise ValueError(
                "cost_basis must be provider_reported, catalog_estimate, or user_supplied"
            )
        result["causentra.cost.usd"] = cost_usd
        result["causentra.cost.basis"] = cost_basis
    elif cost_basis is not None:
        raise ValueError("cost_basis cannot be provided without cost_usd")
    return result

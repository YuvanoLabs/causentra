"""Provider profiles and privacy-safe SDK response telemetry extraction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from .model import WELL_KNOWN_GENAI_PROVIDERS, model_attributes, normalize_provider_name
from .types import EventAttributes

SupportTier = Literal["deep", "compatible"]


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """Stable provider identity and integration strategy."""

    canonical_name: str
    display_name: str
    support_tier: SupportTier
    protocol_family: str
    python_packages: tuple[str, ...]
    aliases: tuple[str, ...] = ()


_PROFILES = (
    ProviderProfile("openai", "OpenAI", "deep", "openai", ("openai",)),
    ProviderProfile("anthropic", "Anthropic", "deep", "anthropic", ("anthropic",)),
    ProviderProfile(
        "gcp.gemini",
        "Google Gemini",
        "deep",
        "google",
        ("google-genai",),
        ("gemini", "google-gemini"),
    ),
    ProviderProfile(
        "aws.bedrock",
        "AWS Bedrock",
        "deep",
        "bedrock",
        ("boto3",),
        ("bedrock", "aws-bedrock", "amazon-bedrock"),
    ),
    ProviderProfile(
        "azure.ai.openai",
        "Azure OpenAI",
        "deep",
        "openai",
        ("openai",),
        ("azure-openai", "azure_openai"),
    ),
    ProviderProfile("cohere", "Cohere", "deep", "cohere", ("cohere",)),
    ProviderProfile(
        "mistral_ai",
        "Mistral AI",
        "deep",
        "openai",
        ("mistralai",),
        ("mistral", "mistralai"),
    ),
    ProviderProfile("groq", "Groq", "deep", "groq", ("groq",)),
    ProviderProfile(
        "azure.ai.inference",
        "Azure AI Inference",
        "compatible",
        "openai",
        ("azure-ai-inference",),
        ("azure-ai-inference", "azure-inference"),
    ),
    ProviderProfile("deepseek", "DeepSeek", "compatible", "openai", ("openai",)),
    ProviderProfile(
        "gcp.gen_ai",
        "Google Gen AI",
        "compatible",
        "google",
        ("google-genai",),
        ("google", "google-genai"),
    ),
    ProviderProfile(
        "gcp.vertex_ai",
        "Google Vertex AI",
        "compatible",
        "google",
        ("google-cloud-aiplatform",),
        ("vertex", "vertex-ai", "vertexai"),
    ),
    ProviderProfile(
        "ibm.watsonx.ai",
        "IBM watsonx.ai",
        "compatible",
        "watsonx",
        ("ibm-watsonx-ai",),
        ("watsonx", "watsonx.ai", "ibm-watsonx"),
    ),
    ProviderProfile("perplexity", "Perplexity", "compatible", "openai", ("openai",)),
    ProviderProfile(
        "x_ai",
        "xAI",
        "compatible",
        "openai",
        ("openai",),
        ("xai", "x-ai", "grok"),
    ),
)

PROVIDER_PROFILES: Mapping[str, ProviderProfile] = {
    profile.canonical_name: profile for profile in _PROFILES
}
DEEP_PROVIDER_NAMES = tuple(
    profile.canonical_name for profile in _PROFILES if profile.support_tier == "deep"
)

if set(PROVIDER_PROFILES) != set(WELL_KNOWN_GENAI_PROVIDERS):
    raise RuntimeError("provider profiles must exactly match the public OTel provider vocabulary")


def provider_profile(provider_name: str) -> ProviderProfile | None:
    """Resolve a canonical provider or alias; custom providers return ``None``."""

    return PROVIDER_PROFILES.get(normalize_provider_name(provider_name))


def provider_response_attributes(
    provider_name: str,
    response: object,
    *,
    request_model: str | None = None,
) -> EventAttributes:
    """Extract allowlisted operational facts without serializing response content.

    Both mappings and SDK response objects are supported. Missing fields remain
    absent, which keeps this compatible with SDK version changes and streaming
    aggregates. Provider payload bodies are never traversed.
    """

    canonical = normalize_provider_name(provider_name)
    profile = PROVIDER_PROFILES.get(canonical)
    family = profile.protocol_family if profile else "generic"
    paths = _FAMILY_PATHS.get(family, _FAMILY_PATHS["generic"])
    response_model = _text(response, paths["response_model"])
    attributes = model_attributes(
        provider_name=canonical,
        request_model=request_model,
        response_model=response_model,
        input_tokens=_count(response, paths["input_tokens"]),
        output_tokens=_count(response, paths["output_tokens"]),
        cache_read_input_tokens=_count(response, paths["cache_read_input_tokens"]),
    )
    cache_write_tokens = _count(response, paths["cache_write_input_tokens"])
    if cache_write_tokens is not None:
        attributes["causentra.usage.cache_write.input_tokens"] = cache_write_tokens
    reasoning_tokens = _count(response, paths["reasoning_tokens"])
    if reasoning_tokens is not None:
        attributes["causentra.usage.reasoning_tokens"] = reasoning_tokens
    if profile is not None:
        attributes["causentra.provider.integration.tier"] = profile.support_tier
        attributes["causentra.provider.protocol_family"] = profile.protocol_family
    response_id = _text(response, paths["response_id"])
    if response_id is not None:
        attributes["gen_ai.response.id"] = response_id
    finish_reason = _text(response, paths["finish_reason"])
    if finish_reason is not None:
        attributes["gen_ai.response.finish_reasons"] = [normalize_finish_reason(finish_reason)]
    duration = _number(response, paths["duration_ms"])
    if duration is not None:
        multiplier = 1_000 if family == "groq" else 1
        attributes["causentra.provider.server_duration_ms"] = duration * multiplier
    request_id = _text(response, paths["request_id"])
    if request_id is not None:
        attributes["causentra.provider.request_id"] = request_id
    return attributes


def normalize_finish_reason(reason: str) -> str:
    """Normalize common provider terminal reasons into a portable vocabulary."""

    value = reason.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "complete": "stop",
        "completed": "stop",
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "max_token": "length",
        "tool_use": "tool_call",
        "tool_calls": "tool_call",
        "function_call": "tool_call",
        "safety": "content_filter",
    }
    return aliases.get(value, value)[:128]


_FAMILY_PATHS: Mapping[str, Mapping[str, tuple[tuple[str | int, ...], ...]]] = {
    "openai": {
        "response_model": (("model",), ("model_id",)),
        "input_tokens": (("usage", "input_tokens"), ("usage", "prompt_tokens")),
        "output_tokens": (("usage", "output_tokens"), ("usage", "completion_tokens")),
        "cache_read_input_tokens": (
            ("usage", "input_tokens_details", "cached_tokens"),
            ("usage", "prompt_tokens_details", "cached_tokens"),
        ),
        "cache_write_input_tokens": (),
        "reasoning_tokens": (
            ("usage", "output_tokens_details", "reasoning_tokens"),
            ("usage", "completion_tokens_details", "reasoning_tokens"),
        ),
        "response_id": (("id",), ("response_id",)),
        "finish_reason": (("choices", 0, "finish_reason"), ("status",)),
        "duration_ms": (),
        "request_id": (("_request_id",),),
    },
    "anthropic": {
        "response_model": (("model",), ("message", "model")),
        "input_tokens": (
            ("usage", "input_tokens"),
            ("message", "usage", "input_tokens"),
        ),
        "output_tokens": (
            ("usage", "output_tokens"),
            ("message", "usage", "output_tokens"),
        ),
        "cache_read_input_tokens": (
            ("usage", "cache_read_input_tokens"),
            ("message", "usage", "cache_read_input_tokens"),
        ),
        "cache_write_input_tokens": (
            ("usage", "cache_creation_input_tokens"),
            ("message", "usage", "cache_creation_input_tokens"),
        ),
        "reasoning_tokens": (
            ("usage", "output_tokens_details", "thinking_tokens"),
            ("message", "usage", "output_tokens_details", "thinking_tokens"),
        ),
        "response_id": (("id",), ("message", "id")),
        "finish_reason": (("stop_reason",), ("delta", "stop_reason")),
        "duration_ms": (),
        "request_id": (("_request_id",),),
    },
    "google": {
        "response_model": (("model_version",), ("modelVersion",), ("model",)),
        "input_tokens": (
            ("usage_metadata", "prompt_token_count"),
            ("usageMetadata", "promptTokenCount"),
        ),
        "output_tokens": (
            ("usage_metadata", "candidates_token_count"),
            ("usageMetadata", "candidatesTokenCount"),
        ),
        "cache_read_input_tokens": (
            ("usage_metadata", "cached_content_token_count"),
            ("usageMetadata", "cachedContentTokenCount"),
        ),
        "cache_write_input_tokens": (),
        "reasoning_tokens": (
            ("usage_metadata", "thoughts_token_count"),
            ("usageMetadata", "thoughtsTokenCount"),
        ),
        "response_id": (("response_id",), ("responseId",)),
        "finish_reason": (
            ("candidates", 0, "finish_reason"),
            ("candidates", 0, "finishReason"),
        ),
        "duration_ms": (),
        "request_id": (),
    },
    "bedrock": {
        "response_model": (("modelId",), ("model_id",)),
        "input_tokens": (
            ("usage", "inputTokens"),
            ("usage", "input_tokens"),
            ("metadata", "usage", "inputTokens"),
        ),
        "output_tokens": (
            ("usage", "outputTokens"),
            ("usage", "output_tokens"),
            ("metadata", "usage", "outputTokens"),
        ),
        "cache_read_input_tokens": (
            ("usage", "cacheReadInputTokens"),
            ("usage", "cache_read_input_tokens"),
            ("metadata", "usage", "cacheReadInputTokens"),
        ),
        "cache_write_input_tokens": (
            ("usage", "cacheWriteInputTokens"),
            ("usage", "cache_write_input_tokens"),
            ("metadata", "usage", "cacheWriteInputTokens"),
        ),
        "reasoning_tokens": (),
        "response_id": (),
        "finish_reason": (
            ("stopReason",),
            ("stop_reason",),
            ("messageStop", "stopReason"),
        ),
        "duration_ms": (
            ("metrics", "latencyMs"),
            ("metrics", "latency_ms"),
            ("metadata", "metrics", "latencyMs"),
        ),
        "request_id": (
            ("ResponseMetadata", "RequestId"),
            ("response_metadata", "request_id"),
        ),
    },
    "cohere": {
        "response_model": (("model",),),
        "input_tokens": (
            ("usage", "tokens", "input_tokens"),
            ("usage", "billed_units", "input_tokens"),
            ("meta", "tokens", "input_tokens"),
            ("meta", "billed_units", "input_tokens"),
        ),
        "output_tokens": (
            ("usage", "tokens", "output_tokens"),
            ("usage", "billed_units", "output_tokens"),
            ("meta", "tokens", "output_tokens"),
            ("meta", "billed_units", "output_tokens"),
        ),
        "cache_read_input_tokens": (),
        "cache_write_input_tokens": (),
        "reasoning_tokens": (),
        "response_id": (("id",), ("response_id",)),
        "finish_reason": (("finish_reason",),),
        "duration_ms": (),
        "request_id": (),
    },
    "groq": {
        "response_model": (("model",),),
        "input_tokens": (("usage", "prompt_tokens"), ("usage", "input_tokens")),
        "output_tokens": (("usage", "completion_tokens"), ("usage", "output_tokens")),
        "cache_read_input_tokens": (
            ("usage", "prompt_tokens_details", "cached_tokens"),
            ("usage", "input_tokens_details", "cached_tokens"),
        ),
        "cache_write_input_tokens": (),
        "reasoning_tokens": (
            ("usage", "completion_tokens_details", "reasoning_tokens"),
            ("usage", "output_tokens_details", "reasoning_tokens"),
        ),
        "response_id": (("id",),),
        "finish_reason": (("choices", 0, "finish_reason"), ("status",)),
        "duration_ms": (("usage", "total_time"), ("metadata", "total_time")),
        "request_id": (("x_groq", "id"),),
    },
    "watsonx": {
        "response_model": (("model_id",), ("model",)),
        "input_tokens": (("usage", "prompt_tokens"), ("input_token_count",)),
        "output_tokens": (
            ("usage", "completion_tokens"),
            ("generated_token_count",),
        ),
        "cache_read_input_tokens": (),
        "cache_write_input_tokens": (),
        "reasoning_tokens": (),
        "response_id": (("id",),),
        "finish_reason": (("choices", 0, "finish_reason"),),
        "duration_ms": (),
        "request_id": (),
    },
    "generic": {
        "response_model": (("model",), ("model_id",)),
        "input_tokens": (("usage", "input_tokens"), ("usage", "prompt_tokens")),
        "output_tokens": (("usage", "output_tokens"), ("usage", "completion_tokens")),
        "cache_read_input_tokens": (),
        "cache_write_input_tokens": (),
        "reasoning_tokens": (),
        "response_id": (("id",),),
        "finish_reason": (("finish_reason",), ("choices", 0, "finish_reason")),
        "duration_ms": (),
        "request_id": (),
    },
}


def _read(source: object, path: tuple[str | int, ...]) -> object | None:
    current: object = source
    for part in path:
        try:
            if isinstance(part, int):
                if not isinstance(current, list | tuple) or part >= len(current):
                    return None
                current = current[part]
            elif isinstance(current, Mapping):
                if part not in current:
                    return None
                current = current[part]
            else:
                current = getattr(current, part)
        except (AttributeError, IndexError, KeyError, TypeError):
            return None
    return current


def _first(source: object, paths: tuple[tuple[str | int, ...], ...]) -> object | None:
    for path in paths:
        value = _read(source, path)
        if value is not None:
            return value
    return None


def _text(source: object, paths: tuple[tuple[str | int, ...], ...]) -> str | None:
    value = _first(source, paths)
    if isinstance(value, str) and value.strip():
        return value.strip()[:256]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str) and enum_value.strip():
        return enum_value.strip()[:256]
    return None


def _count(source: object, paths: tuple[tuple[str | int, ...], ...]) -> int | None:
    value = _first(source, paths)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _number(source: object, paths: tuple[tuple[str | int, ...], ...]) -> float | None:
    value = _first(source, paths)
    if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
            return parsed if parsed >= 0 else None
        except ValueError:
            return None
    return None

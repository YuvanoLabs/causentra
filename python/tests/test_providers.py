from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from causentra import (
    DEEP_PROVIDER_NAMES,
    PROVIDER_PROFILES,
    WELL_KNOWN_GENAI_PROVIDERS,
    CausentraRuntime,
    MemoryExporter,
    normalize_finish_reason,
    provider_response_attributes,
)

DEEP_FIXTURES = {
    "openai": {
        "response": {
            "id": "resp-openai",
            "model": "gpt-production",
            "usage": {
                "input_tokens": 101,
                "output_tokens": 22,
                "input_tokens_details": {"cached_tokens": 40},
                "output_tokens_details": {"reasoning_tokens": 7},
            },
            "choices": [{"finish_reason": "stop", "message": {"content": "private"}}],
        },
        "request_model": "gpt-requested",
    },
    "anthropic": {
        "response": {
            "id": "msg-anthropic",
            "model": "claude-production",
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 102,
                "output_tokens": 23,
                "cache_read_input_tokens": 41,
                "cache_creation_input_tokens": 11,
                "output_tokens_details": {"thinking_tokens": 8},
            },
            "content": [{"text": "private"}],
        },
        "request_model": "claude-requested",
    },
    "gcp.gemini": {
        "response": {
            "responseId": "gemini-response",
            "modelVersion": "gemini-production",
            "usageMetadata": {
                "promptTokenCount": 103,
                "candidatesTokenCount": 24,
                "cachedContentTokenCount": 42,
                "thoughtsTokenCount": 9,
            },
            "candidates": [{"finishReason": "STOP", "content": "private"}],
        },
        "request_model": "gemini-requested",
    },
    "aws.bedrock": {
        "response": {
            "modelId": "bedrock-production",
            "stopReason": "end_turn",
            "usage": {
                "inputTokens": 104,
                "outputTokens": 25,
                "cacheReadInputTokens": 43,
                "cacheWriteInputTokens": 12,
            },
            "metrics": {"latencyMs": 125.5},
            "ResponseMetadata": {"RequestId": "bedrock-request"},
            "output": {"message": {"content": "private"}},
        },
        "request_model": "bedrock-requested",
    },
    "azure.ai.openai": {
        "response": {
            "id": "azure-response",
            "model": "azure-deployment-version",
            "usage": {
                "prompt_tokens": 105,
                "completion_tokens": 26,
                "prompt_tokens_details": {"cached_tokens": 44},
                "completion_tokens_details": {"reasoning_tokens": 10},
            },
            "choices": [{"finish_reason": "length", "content": "private"}],
        },
        "request_model": "azure-deployment",
    },
    "cohere": {
        "response": {
            "id": "cohere-response",
            "finish_reason": "COMPLETE",
            "usage": {
                "tokens": {"input_tokens": 106, "output_tokens": 27},
                "billed_units": {"input_tokens": 100, "output_tokens": 25},
            },
            "message": {"content": "private"},
        },
        "request_model": "command-production",
    },
    "mistral_ai": {
        "response": {
            "id": "mistral-response",
            "model": "mistral-production",
            "usage": {
                "prompt_tokens": 107,
                "completion_tokens": 28,
                "prompt_tokens_details": {"cached_tokens": 45},
                "completion_tokens_details": {"reasoning_tokens": 13},
            },
            "choices": [{"finish_reason": "tool_calls", "message": "private"}],
        },
        "request_model": "mistral-requested",
    },
    "groq": {
        "response": {
            "id": "groq-response",
            "model": "groq-production",
            "usage": {
                "prompt_tokens": 108,
                "completion_tokens": 29,
                "prompt_tokens_details": {"cached_tokens": 46},
                "completion_tokens_details": {"reasoning_tokens": 14},
                "total_time": 0.25,
            },
            "x_groq": {"id": "groq-request"},
            "choices": [{"finish_reason": "stop", "message": "private"}],
        },
        "request_model": "groq-requested",
    },
}

SUPPORT_MANIFEST = (
    Path(__file__).parents[2] / "packages" / "sdk" / "fixtures" / "provider-support-v1.json"
)


def test_profiles_exactly_cover_15_providers_with_8_deep_integrations() -> None:
    assert set(PROVIDER_PROFILES) == set(WELL_KNOWN_GENAI_PROVIDERS)
    assert len(PROVIDER_PROFILES) == 15
    assert set(DEEP_PROVIDER_NAMES) == set(DEEP_FIXTURES)
    assert len(DEEP_PROVIDER_NAMES) == 8


def test_python_and_typescript_use_the_same_provider_support_contract() -> None:
    manifest = json.loads(SUPPORT_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schemaVersion"] == "1.0"
    assert set(manifest["canonicalProviders"]) == set(WELL_KNOWN_GENAI_PROVIDERS)
    assert set(manifest["deepPythonProviders"]) == set(DEEP_PROVIDER_NAMES)


@pytest.mark.parametrize("provider_name", DEEP_PROVIDER_NAMES)
def test_deep_provider_response_mapping(provider_name: str) -> None:
    fixture = DEEP_FIXTURES[provider_name]
    attributes = provider_response_attributes(
        provider_name,
        fixture["response"],
        request_model=fixture["request_model"],
    )
    assert attributes["gen_ai.provider.name"] == provider_name
    assert attributes["gen_ai.request.model"] == fixture["request_model"]
    assert attributes["gen_ai.usage.input_tokens"] >= 101
    assert attributes["gen_ai.usage.output_tokens"] >= 22
    assert attributes["gen_ai.response.finish_reasons"]
    assert attributes["causentra.provider.integration.tier"] == "deep"
    assert "private" not in str(attributes)


def test_sdk_attribute_objects_are_supported_without_serializing_content() -> None:
    response = SimpleNamespace(
        id="sdk-object-response",
        model="sdk-object-model",
        usage=SimpleNamespace(
            input_tokens=31,
            output_tokens=12,
            input_tokens_details=SimpleNamespace(cached_tokens=7),
            output_tokens_details=SimpleNamespace(reasoning_tokens=4),
        ),
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(content="private-sdk-object-content"),
            )
        ],
    )

    attributes = provider_response_attributes("openai", response)
    assert attributes["gen_ai.response.id"] == "sdk-object-response"
    assert attributes["gen_ai.usage.input_tokens"] == 31
    assert attributes["gen_ai.usage.cache_read.input_tokens"] == 7
    assert attributes["causentra.usage.reasoning_tokens"] == 4
    assert attributes["gen_ai.response.finish_reasons"] == ["tool_call"]
    assert "private" not in str(attributes)


@pytest.mark.parametrize(
    ("provider_name", "response"),
    [
        (
            "azure.ai.inference",
            {"model": "phi", "usage": {"prompt_tokens": 1, "completion_tokens": 2}},
        ),
        ("deepseek", {"model": "deepseek", "usage": {"prompt_tokens": 1, "completion_tokens": 2}}),
        (
            "gcp.gen_ai",
            {
                "modelVersion": "gemini",
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 2},
            },
        ),
        (
            "gcp.vertex_ai",
            {
                "model_version": "gemini",
                "usage_metadata": {"prompt_token_count": 1, "candidates_token_count": 2},
            },
        ),
        (
            "ibm.watsonx.ai",
            {"model_id": "granite", "usage": {"prompt_tokens": 1, "completion_tokens": 2}},
        ),
        ("perplexity", {"model": "sonar", "usage": {"prompt_tokens": 1, "completion_tokens": 2}}),
        ("x_ai", {"model": "grok", "usage": {"prompt_tokens": 1, "completion_tokens": 2}}),
    ],
)
def test_compatible_provider_mapping_covers_remaining_vocabulary(
    provider_name: str, response: object
) -> None:
    attributes = provider_response_attributes(provider_name, response)
    assert attributes["gen_ai.provider.name"] == provider_name
    assert attributes["gen_ai.usage.input_tokens"] == 1
    assert attributes["gen_ai.usage.output_tokens"] == 2
    assert attributes["causentra.provider.integration.tier"] == "compatible"


def test_provider_model_observes_response_on_terminal_event() -> None:
    exporter = MemoryExporter()
    runtime = CausentraRuntime("provider-test", exporter)
    with (
        runtime.trace("workflow"),
        runtime.provider_model(
            "generate", provider_name="anthropic", request_model="claude-requested"
        ) as observer,
    ):
        assert observer.observe_response(DEEP_FIXTURES["anthropic"]["response"])
    terminal = next(event for event in exporter.events if event.type == "model.end")
    assert terminal.attributes["gen_ai.response.model"] == "claude-production"
    assert terminal.attributes["gen_ai.usage.cache_read.input_tokens"] == 41
    assert terminal.attributes["causentra.usage.cache_write.input_tokens"] == 11
    assert terminal.attributes["causentra.usage.reasoning_tokens"] == 8


def test_provider_extraction_failure_is_reported_and_never_breaks_the_call() -> None:
    class HostileResponse:
        @property
        def model(self) -> str:
            raise RuntimeError("malformed provider response")

    diagnostics = []
    exporter = MemoryExporter()
    runtime = CausentraRuntime("provider-fail-open-test", exporter, on_error=diagnostics.append)
    response = HostileResponse()

    with runtime.trace("workflow"):
        returned = runtime.call_model(
            "generate", lambda: response, provider_name="openai", request_model="requested"
        )

    assert returned is response
    assert diagnostics and diagnostics[0].operation == "adapter"
    terminal = next(event for event in exporter.events if event.type == "model.end")
    assert terminal.status == "ok"


def test_provider_call_requires_and_records_cost_provenance() -> None:
    exporter = MemoryExporter()
    runtime = CausentraRuntime("provider-cost-test", exporter)
    response = DEEP_FIXTURES["groq"]["response"]

    with runtime.trace("workflow"):
        runtime.call_model(
            "generate",
            lambda: response,
            provider_name="groq",
            cost_usd=0.0125,
            cost_basis="provider_reported",
        )

    start = next(event for event in exporter.events if event.type == "model.start")
    assert start.attributes["causentra.cost.usd"] == 0.0125
    assert start.attributes["causentra.cost.basis"] == "provider_reported"

    with pytest.raises(ValueError, match="cost_basis must be"):
        runtime.provider_model("invalid", provider_name="groq", cost_usd=0.1)
    with pytest.raises(ValueError, match="cost_basis must be"):
        runtime.provider_model(
            "invalid-basis",
            provider_name="groq",
            cost_usd=0.1,
            cost_basis="unverified",  # type: ignore[arg-type]
        )


def test_streaming_terminal_shapes_merge_without_content_capture() -> None:
    exporter = MemoryExporter()
    runtime = CausentraRuntime("stream-provider-test", exporter)
    start_chunk = {
        "message": {
            "id": "message-stream",
            "model": "claude-stream",
            "usage": {
                "input_tokens": 17,
                "cache_read_input_tokens": 9,
                "cache_creation_input_tokens": 3,
            },
            "content": "private-start-content",
        }
    }
    end_chunk = {
        "delta": {"stop_reason": "tool_use", "text": "private-delta"},
        "usage": {"output_tokens": 6},
    }
    with (
        runtime.trace("stream"),
        runtime.provider_model(
            "anthropic-stream", provider_name="anthropic", request_model="claude-requested"
        ) as observer,
    ):
        assert observer.observe_response(start_chunk)
        assert observer.observe_response(end_chunk)
    terminal = next(event for event in exporter.events if event.type == "model.end")
    assert terminal.attributes["gen_ai.usage.input_tokens"] == 17
    assert terminal.attributes["gen_ai.usage.output_tokens"] == 6
    assert terminal.attributes["gen_ai.response.finish_reasons"] == ["tool_call"]
    assert "private" not in str(terminal.attributes)


def test_bedrock_stream_metadata_shape_is_supported() -> None:
    attributes = provider_response_attributes(
        "bedrock",
        {
            "metadata": {
                "usage": {
                    "inputTokens": 20,
                    "outputTokens": 7,
                    "cacheReadInputTokens": 5,
                    "cacheWriteInputTokens": 2,
                },
                "metrics": {"latencyMs": 88},
            },
            "messageStop": {"stopReason": "max_tokens"},
        },
        request_model="amazon.nova",
    )
    assert attributes["gen_ai.usage.input_tokens"] == 20
    assert attributes["causentra.usage.cache_write.input_tokens"] == 2
    assert attributes["causentra.provider.server_duration_ms"] == 88
    assert attributes["gen_ai.response.finish_reasons"] == ["length"]


def test_sync_and_async_call_sugar_preserve_provider_response_identity() -> None:
    exporter = MemoryExporter()
    runtime = CausentraRuntime("provider-call-test", exporter)
    response = DEEP_FIXTURES["openai"]["response"]
    with runtime.trace("sync"):
        assert (
            runtime.call_model("openai-call", lambda: response, provider_name="openai") is response
        )

    async def scenario() -> object:
        async def operation() -> object:
            return response

        async with runtime.trace("async"):
            return await runtime.call_model_async(
                "azure-call", operation, provider_name="azure-openai"
            )

    assert asyncio.run(scenario()) is response
    assert sum(event.type == "model.end" for event in exporter.events) == 2


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("end_turn", "stop"),
        ("COMPLETE", "stop"),
        ("MAX_TOKENS", "length"),
        ("tool_calls", "tool_call"),
        ("SAFETY", "content_filter"),
    ],
)
def test_finish_reason_standardization(source: str, expected: str) -> None:
    assert normalize_finish_reason(source) == expected

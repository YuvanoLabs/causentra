# ADR-005: Python-first, language-neutral runtime

Status: accepted

## Context

The original idea targets teams operating multiple AI agents and providers. The first implementation brief selected TypeScript without evidence from the source idea. Python has the stronger agent-framework integration need, while the completed TypeScript collector and SDK already prove the protocol and UI.

## Decision

Python is the primary SDK and adapter surface. TypeScript remains maintained. Both produce `RuntimeEvent` 1.0, use W3C Trace Context, and send to the same HTTP/OTLP collector. Neither language owns the schema.

Python code lives under `python/src/causentra` and is released with the same product contract as the TypeScript packages.

## Consequences

- Native Python adapters are prioritized for OpenAI Agents and LangGraph.
- AutoGen and other OTel-native frameworks use OTLP before custom adapters are justified.
- Shared fixtures and a Python-to-Node ingestion test prevent language drift.
- Framework payloads remain excluded by default in every language.
- A production claim requires supported-version CI, wheel installation, load/security evidence, and real-framework tests.

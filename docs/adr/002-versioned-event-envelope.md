# ADR-002: Versioned event envelope

Status: Accepted

## Context

Framework adapters and multiple language SDKs need a stable interchange format.

## Decision

Define a framework-neutral JSON envelope with a mandatory schema version, event and correlation IDs, timestamp, sequence, lifecycle type, operation name, status, duration, and bounded attributes. Validate before persistence and preserve unknown types.

## Consequences

Adapters remain thin and storage is portable. Semantic changes require explicit versioning and compatibility fixtures. Framework-specific detail belongs in namespaced attributes rather than new core fields by default.

# ADR-003: Bounded at-least-once HTTP export

Status: Accepted

## Context

Instrumentation must not make the application unavailable, yet silent event loss destroys trust.

## Decision

M0 uses a bounded in-memory queue, batched HTTP delivery, finite exponential retry, explicit flush, and an error callback. Application operations fail open. Event IDs allow downstream deduplication.

## Consequences

Abrupt process termination can lose queued data and duplicates are possible. Both are documented. A future collector adds disk spooling without changing the event contract.

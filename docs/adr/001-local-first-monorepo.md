# ADR-001: Local-first modular monorepo

Status: Accepted

## Context

The first milestone must validate the complete developer journey while preserving boundaries needed for hosted evolution.

## Decision

Use a TypeScript npm workspace with separate SDK, server, and CLI packages. Run the local service as one loopback-bound Node.js process with static dashboard assets and append-only storage.

## Consequences

One repository simplifies coordinated contract changes and end-to-end testing. Package boundaries prevent UI/server coupling to SDK internals. The local store is not a cloud database design; it is replaceable behind a store interface.

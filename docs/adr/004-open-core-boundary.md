# ADR-004: Enforced open-core boundary

Status: Accepted

## Context

The product needs a trusted open-source adoption layer and proprietary managed/enterprise capabilities without accidental code disclosure or runtime coupling.

## Decision

Public packages use `@causentra/*` in the self-contained `opensource/` workspace under Apache-2.0. Private packages use `@causentra-enterprise/*` in the sibling `enterprise/` workspace, are marked private and UNLICENSED, and may depend only on exact published public contracts. Local edition-contract verification rejects reverse dependencies, relative source links, and version drift.

## Consequences

The local product remains buildable and useful with no private checkout. Some interface duplication may be preferable to unsafe cross-boundary internal imports. Before public launch, enterprise code moves to a separate private repository.

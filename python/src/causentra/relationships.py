"""Portable multi-agent relationship vocabulary."""

from __future__ import annotations

from typing import Literal

from .types import EventAttributes

RelationshipKind = Literal["handoff", "delegation"]


def relationship_attributes(
    kind: RelationshipKind,
    from_agent: str,
    to_agent: str,
    relationship_id: str | None = None,
) -> EventAttributes:
    """Build framework-neutral handoff or delegation attributes."""

    for value, field in ((from_agent, "from_agent"), (to_agent, "to_agent")):
        if not value.strip() or len(value) > 256:
            raise ValueError(f"{field} must be non-empty and at most 256 characters")
    if relationship_id is not None and (not relationship_id or len(relationship_id) > 256):
        raise ValueError("relationship_id must be non-empty and at most 256 characters")
    result: EventAttributes = {
        "causentra.agent.relationship.kind": kind,
        "causentra.agent.from.name": from_agent,
        "causentra.agent.to.name": to_agent,
    }
    if relationship_id is not None:
        result["causentra.agent.relationship.id"] = relationship_id
    return result

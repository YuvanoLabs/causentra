import type { EventAttributes } from "./types.js";

/** Portable relationship between two logical agents. */
export type AgentRelationshipKind = "handoff" | "delegation";

export interface AgentRelationship {
  readonly kind: AgentRelationshipKind;
  readonly fromAgent: string;
  readonly toAgent: string;
  /** Framework or application correlation ID; content must not be placed here. */
  readonly relationshipId?: string;
}

/** Builds validated, framework-neutral handoff/delegation attributes. */
export function createAgentRelationshipAttributes(
  relationship: AgentRelationship,
): EventAttributes {
  name(relationship.fromAgent, "fromAgent");
  name(relationship.toAgent, "toAgent");
  if (
    relationship.relationshipId !== undefined
    && (relationship.relationshipId.length === 0 || relationship.relationshipId.length > 256)
  ) {
    throw new TypeError("relationshipId must be a non-empty string up to 256 characters");
  }
  return {
    "causentra.agent.relationship.kind": relationship.kind,
    "causentra.agent.from.name": relationship.fromAgent,
    "causentra.agent.to.name": relationship.toAgent,
    ...(relationship.relationshipId === undefined
      ? {}
      : { "causentra.agent.relationship.id": relationship.relationshipId }),
  };
}

function name(value: string, field: string): void {
  if (value.trim().length === 0 || value.length > 256) {
    throw new TypeError(`${field} must be a non-empty string up to 256 characters`);
  }
}

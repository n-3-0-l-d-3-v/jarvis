"""Routing/dispatch orchestration: ties classifier + tier engine + registry
together into one decision, used by both `jarvis route --dry-run` (compute
only) and `jarvis ask` (compute, then actually call the sibling agent's
MCP server).

Kept separate from cli.py so the routing logic is testable without going
through click's argument parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from jarvis.classifier import ClassificationResult, classify
from jarvis.registry import AgentSpec, RegistryError, load_registry
from jarvis.tiers import (
    Tier,
    TierConflictError,
    TierDecision,
    UnknownTierError,
    check_conflict,
    compute_tier,
    parse_tier,
)


@dataclass
class RouteDecision:
    agent: AgentSpec
    classification: Optional[ClassificationResult]
    tier_decision: TierDecision
    allowed: bool
    conflict_reason: Optional[str] = None


def route(
    text: str,
    *,
    agent_override: Optional[str] = None,
    tier_override: Optional[str] = None,
    agents_yaml_path: Optional[Path] = None,
) -> RouteDecision:
    """Compute (agent, tier, allowed) for a request without dispatching
    anything. Raises RegistryError for an unknown --agent, UnknownTierError
    for a malformed --tier. Does NOT raise on a tier/agent conflict —
    that's reported via `allowed`/`conflict_reason` so callers (dry-run vs.
    real dispatch) can decide what to do with it."""
    registry = load_registry(agents_yaml_path)

    classification: Optional[ClassificationResult] = None
    if agent_override:
        if agent_override not in registry:
            raise RegistryError(
                f"unknown agent '{agent_override}'. Known agents: {sorted(registry)}"
            )
        agent_key = agent_override
    else:
        classification = classify(text)
        agent_key = classification.agent

    agent = registry[agent_key]
    agent_floor = parse_tier(agent.default_sensitivity_tier)

    explicit_tier: Optional[Tier] = parse_tier(tier_override) if tier_override else None

    tier_decision = compute_tier(
        text, agent_floor=agent_floor, explicit_override=explicit_tier
    )

    allowed = True
    conflict_reason = None
    try:
        check_conflict(tier_decision.tier, agent.key, agent_floor)
    except TierConflictError as exc:
        allowed = False
        conflict_reason = str(exc)

    return RouteDecision(
        agent=agent,
        classification=classification,
        tier_decision=tier_decision,
        allowed=allowed,
        conflict_reason=conflict_reason,
    )

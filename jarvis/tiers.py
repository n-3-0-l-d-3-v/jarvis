"""Sensitivity-tier engine.

Implements the tier model from 10x/docs/omniroute-privacy-spec.md:

    private (most protective) < personal-token < work < public (least protective)

Jarvis v1 does not do provider routing (Phase 5 / Ollama+OmniRoute doesn't
exist yet) — this module only computes and enforces the *tier*, and that
enforcement is real: it decides whether a request is even allowed to reach
a given sibling agent's MCP server.

Judgment calls made here (see README.md "Design notes" for the full list):

- "Agent-declared default is the floor" is implemented as: the tier a
  request gets when nothing more specific overrides it. It is a floor in
  the sense that a request never gets routed to an agent with WEAKER
  protection than what the request needs — see `check_conflict`.
- "Path-based override forces private" is implemented as an *unconditional*
  override: if the request text references a path under vault/private/**,
  the tier is private and no --tier flag can weaken it. A --tier flag can
  still *strengthen* it (private -> private is a no-op; you cannot go the
  other way for a path-forced request).
- "Fail closed" is implemented as: if no agent is known yet (e.g. tier is
  being computed before routing has been decided) and there's no path
  override and no explicit override, the tier is `private`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Tier(str, Enum):
    PRIVATE = "private"
    PERSONAL_TOKEN = "personal-token"
    WORK = "work"
    PUBLIC = "public"


# Lower index = more protective / more restrictive.
_STRICTNESS = {
    Tier.PRIVATE: 0,
    Tier.PERSONAL_TOKEN: 1,
    Tier.WORK: 2,
    Tier.PUBLIC: 3,
}

_VALID_VALUES = {t.value: t for t in Tier}

# Matches vault/private/** (or a private-tagged folder) in either slash
# style, case-insensitively, anywhere in the request text — e.g. a pasted
# Windows path, a forward-slash path, or just someone typing
# "vault/private/health-notes.md" inline.
_PRIVATE_PATH_RE = re.compile(r"vault[\\/]+private[\\/]", re.IGNORECASE)
_PUBLIC_PATH_RE = re.compile(r"vault[\\/]+public[\\/]", re.IGNORECASE)


class TierError(Exception):
    """Base class for tier-engine errors."""


class UnknownTierError(TierError):
    def __init__(self, value: str):
        super().__init__(
            f"unknown sensitivity tier '{value}'. Valid tiers: "
            f"{[t.value for t in Tier]}"
        )
        self.value = value


class TierConflictError(TierError):
    """Raised when a computed tier is stricter than the target agent
    guarantees — dispatch must be refused, not silently downgraded."""

    def __init__(self, tier: Tier, agent_key: str, agent_floor: Tier):
        super().__init__(
            f"refusing to dispatch: computed tier '{tier.value}' is more "
            f"sensitive than agent '{agent_key}' guarantees (its declared "
            f"default_sensitivity_tier floor is '{agent_floor.value}'). "
            f"This request cannot be routed there."
        )
        self.tier = tier
        self.agent_key = agent_key
        self.agent_floor = agent_floor


class PathForcedTierError(TierError):
    """Raised when a --tier override tries to weaken a path-forced tier."""

    def __init__(self, requested: Tier):
        super().__init__(
            f"the request text references a path under vault/private/**, "
            f"which unconditionally forces tier 'private'. Cannot override "
            f"to '{requested.value}'."
        )
        self.requested = requested


def parse_tier(value: str) -> Tier:
    try:
        return _VALID_VALUES[value]
    except KeyError:
        raise UnknownTierError(value) from None


def is_stricter(a: Tier, b: Tier) -> bool:
    """True if tier `a` demands more protection than tier `b`."""
    return _STRICTNESS[a] < _STRICTNESS[b]


def path_forces_private(text: str) -> bool:
    return bool(_PRIVATE_PATH_RE.search(text))


def path_suggests_public(text: str) -> bool:
    return bool(_PUBLIC_PATH_RE.search(text))


@dataclass(frozen=True)
class TierDecision:
    tier: Tier
    reason: str
    path_forced: bool = False


def compute_tier(
    text: str,
    *,
    agent_floor: Optional[Tier] = None,
    explicit_override: Optional[Tier] = None,
) -> TierDecision:
    """Compute the sensitivity tier for a request.

    Precedence (highest first):
      1. Path-based override (vault/private/** in the text) -> private,
         unconditional. A conflicting explicit_override raises
         PathForcedTierError rather than being silently ignored.
      2. Explicit user override (--tier).
      3. Target agent's declared default_sensitivity_tier (the floor).
      4. Fail-closed default: private.
    """
    if path_forces_private(text):
        if explicit_override is not None and explicit_override != Tier.PRIVATE:
            raise PathForcedTierError(explicit_override)
        return TierDecision(
            tier=Tier.PRIVATE,
            reason="path-based override: request references vault/private/**",
            path_forced=True,
        )

    if explicit_override is not None:
        return TierDecision(
            tier=explicit_override,
            reason="explicit --tier override",
        )

    if agent_floor is not None:
        return TierDecision(
            tier=agent_floor,
            reason=f"agent-declared default_sensitivity_tier floor ({agent_floor.value})",
        )

    return TierDecision(
        tier=Tier.PRIVATE,
        reason="fail-closed default: no path override, no explicit override, "
        "no target agent known yet",
    )


def check_conflict(tier: Tier, agent_key: str, agent_floor: Tier) -> None:
    """Raise TierConflictError if `tier` demands more protection than the
    target agent guarantees. No-op (returns None) otherwise."""
    if is_stricter(tier, agent_floor):
        raise TierConflictError(tier, agent_key, agent_floor)

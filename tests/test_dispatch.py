import pytest

from jarvis.dispatch import route
from jarvis.registry import RegistryError
from jarvis.tiers import Tier, UnknownTierError


def test_route_uses_classifier_when_no_override():
    decision = route("please capture a note about this article")
    assert decision.agent.key == "friday"
    assert decision.classification is not None
    assert decision.classification.agent == "friday"


def test_route_agent_override_skips_classifier():
    decision = route("please capture a note", agent_override="ultron")
    assert decision.agent.key == "ultron"
    assert decision.classification is None


def test_route_unknown_agent_override_raises():
    with pytest.raises(RegistryError):
        route("hello", agent_override="nonexistent-agent")


def test_route_unknown_tier_override_raises():
    with pytest.raises(UnknownTierError):
        route("hello", tier_override="super-secret")


def test_route_tier_defaults_to_agent_floor():
    decision = route("explain hash maps", agent_override="friday")
    assert decision.tier_decision.tier is Tier.PERSONAL_TOKEN
    assert decision.allowed is True


def test_route_private_request_to_friday_is_refused():
    # explicit private override routed at an agent whose floor is
    # personal-token (friday) must be refused, not silently downgraded.
    decision = route(
        "sensitive stuff", agent_override="friday", tier_override="private"
    )
    assert decision.tier_decision.tier is Tier.PRIVATE
    assert decision.allowed is False
    assert decision.conflict_reason is not None
    assert "friday" in decision.conflict_reason


def test_route_private_request_to_ultron_is_allowed():
    decision = route(
        "reverse engineer this binary", agent_override="ultron", tier_override="private"
    )
    assert decision.tier_decision.tier is Tier.PRIVATE
    assert decision.allowed is True


def test_route_path_override_forces_private_and_may_refuse():
    decision = route(
        "summarize vault/private/journal.md", agent_override="friday"
    )
    assert decision.tier_decision.tier is Tier.PRIVATE
    assert decision.tier_decision.path_forced is True
    assert decision.allowed is False


def test_route_fail_closed_default_when_agent_override_given():
    # Even with an agent override, the tier still defaults to that agent's
    # own floor (not a global fail-closed private) since the agent is known.
    decision = route("generic question", agent_override="alfred")
    assert decision.tier_decision.tier is Tier.PERSONAL_TOKEN

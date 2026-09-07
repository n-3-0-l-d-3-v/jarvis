import pytest

from jarvis.tiers import (
    Tier,
    TierConflictError,
    PathForcedTierError,
    UnknownTierError,
    check_conflict,
    compute_tier,
    is_stricter,
    parse_tier,
    path_forces_private,
    path_suggests_public,
)


def test_parse_tier_valid():
    assert parse_tier("private") is Tier.PRIVATE
    assert parse_tier("personal-token") is Tier.PERSONAL_TOKEN
    assert parse_tier("work") is Tier.WORK
    assert parse_tier("public") is Tier.PUBLIC


def test_parse_tier_invalid():
    with pytest.raises(UnknownTierError):
        parse_tier("super-secret")


def test_strictness_ordering():
    assert is_stricter(Tier.PRIVATE, Tier.PERSONAL_TOKEN)
    assert is_stricter(Tier.PRIVATE, Tier.PUBLIC)
    assert is_stricter(Tier.PERSONAL_TOKEN, Tier.WORK)
    assert not is_stricter(Tier.WORK, Tier.PERSONAL_TOKEN)
    assert not is_stricter(Tier.PUBLIC, Tier.PRIVATE)
    assert not is_stricter(Tier.PRIVATE, Tier.PRIVATE)


class TestPathDetection:
    def test_forward_slash(self):
        assert path_forces_private("see vault/private/health.md")

    def test_back_slash(self):
        assert path_forces_private(r"see vault\private\health.md")

    def test_case_insensitive(self):
        assert path_forces_private("VAULT/PRIVATE/foo.md")

    def test_no_match(self):
        assert not path_forces_private("just a normal question about hash maps")

    def test_public_path_detected_separately(self):
        assert path_suggests_public("vault/public/blog-draft.md")
        assert not path_suggests_public("vault/private/blog-draft.md")


class TestComputeTier:
    def test_fail_closed_default(self):
        """No path override, no explicit override, no agent floor known ->
        private. This is the core fail-closed guarantee."""
        decision = compute_tier("explain hash maps to me")
        assert decision.tier is Tier.PRIVATE
        assert "fail-closed" in decision.reason

    def test_agent_floor_used_when_no_override(self):
        decision = compute_tier("explain hash maps", agent_floor=Tier.WORK)
        assert decision.tier is Tier.WORK
        assert not decision.path_forced

    def test_explicit_override_wins_over_agent_floor(self):
        decision = compute_tier(
            "explain hash maps", agent_floor=Tier.WORK, explicit_override=Tier.PUBLIC
        )
        assert decision.tier is Tier.PUBLIC

    def test_path_override_forces_private_even_with_agent_floor(self):
        decision = compute_tier(
            "summarize vault/private/journal.md", agent_floor=Tier.PUBLIC
        )
        assert decision.tier is Tier.PRIVATE
        assert decision.path_forced

    def test_path_override_forces_private_even_with_matching_explicit_override(self):
        decision = compute_tier(
            "summarize vault/private/journal.md", explicit_override=Tier.PRIVATE
        )
        assert decision.tier is Tier.PRIVATE
        assert decision.path_forced

    def test_path_override_rejects_conflicting_explicit_override(self):
        with pytest.raises(PathForcedTierError):
            compute_tier(
                "summarize vault/private/journal.md", explicit_override=Tier.PUBLIC
            )


class TestCheckConflict:
    def test_no_conflict_when_tier_matches_floor(self):
        check_conflict(Tier.PRIVATE, "ultron", Tier.PRIVATE)  # should not raise

    def test_no_conflict_when_tier_less_sensitive_than_floor(self):
        # work request routed to an agent whose floor is personal-token is
        # fine: the agent over-protects, it doesn't under-protect.
        check_conflict(Tier.WORK, "friday", Tier.PERSONAL_TOKEN)

    def test_conflict_when_tier_stricter_than_floor(self):
        # private data must not go to an agent that only guarantees
        # personal-token-level protection (e.g. Friday, Alfred).
        with pytest.raises(TierConflictError) as exc_info:
            check_conflict(Tier.PRIVATE, "friday", Tier.PERSONAL_TOKEN)
        assert exc_info.value.tier is Tier.PRIVATE
        assert exc_info.value.agent_key == "friday"

    def test_private_only_routes_to_private_floor_agent(self):
        # Mirrors the spec's own example: "don't let something explicitly
        # marked private get routed anywhere that isn't Ultron/local."
        check_conflict(Tier.PRIVATE, "ultron", Tier.PRIVATE)  # ok
        with pytest.raises(TierConflictError):
            check_conflict(Tier.PRIVATE, "alfred", Tier.PERSONAL_TOKEN)
        with pytest.raises(TierConflictError):
            check_conflict(Tier.PRIVATE, "some-public-agent", Tier.PUBLIC)

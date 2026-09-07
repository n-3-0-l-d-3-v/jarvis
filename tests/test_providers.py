"""Tests for jarvis.providers — the OmniRoute eligibility-table loader."""

from __future__ import annotations

import pytest
import yaml

from jarvis import providers


@pytest.fixture
def sample_yaml(tmp_path):
    path = tmp_path / "providers.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "tiers": {
                    "private": {"eligible_providers": ["ollama-local"]},
                    "work": {
                        "eligible_providers": ["ollama-local", "groq-free-tier"]
                    },
                },
                "providers": {
                    "ollama-local": {"kind": "local", "configured": True},
                    "groq-free-tier": {"kind": "shared-pool", "configured": False},
                    "groq-personal": {"kind": "personal-key"},
                },
            }
        )
    )
    return path


def test_eligible_providers_for_known_tier(sample_yaml):
    assert providers.eligible_providers_for_tier(
        "private", providers_yaml_path=sample_yaml
    ) == ["ollama-local"]


def test_eligible_providers_for_unknown_tier_raises(sample_yaml):
    with pytest.raises(providers.ProvidersConfigError):
        providers.eligible_providers_for_tier("nonexistent", providers_yaml_path=sample_yaml)


def test_get_provider_local(sample_yaml):
    info = providers.get_provider("ollama-local", providers_yaml_path=sample_yaml)
    assert info.configured is True
    assert info.kind == "local"


def test_get_provider_shared_pool_not_configured(sample_yaml):
    info = providers.get_provider("groq-free-tier", providers_yaml_path=sample_yaml)
    assert info.configured is False


def test_get_provider_personal_key_reports_configured_true(sample_yaml):
    # personal-key providers report configured=True (capability exists,
    # owned per-agent) even with no explicit `configured` field, per
    # providers.py's own reasoning for why that's the honest default.
    info = providers.get_provider("groq-personal", providers_yaml_path=sample_yaml)
    assert info.configured is True
    assert info.kind == "personal-key"


def test_get_provider_unknown_raises(sample_yaml):
    with pytest.raises(providers.ProvidersConfigError):
        providers.get_provider("nonexistent-provider", providers_yaml_path=sample_yaml)


def test_usable_providers_for_tier_excludes_unconfigured(sample_yaml):
    assert providers.usable_providers_for_tier(
        "work", providers_yaml_path=sample_yaml
    ) == ["ollama-local"]


def test_malformed_config_missing_top_level_keys_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump({"tiers": {}}))
    with pytest.raises(providers.ProvidersConfigError):
        providers.eligible_providers_for_tier("private", providers_yaml_path=path)


def test_real_providers_yaml_loads_and_matches_omniroute_spec_tiers():
    """Run against the actual shipped providers.yaml, not a fixture — the
    four tiers this file describes must match tiers.py's own Tier enum,
    or the two modules have silently drifted apart.
    """
    from jarvis.tiers import Tier

    for tier in Tier:
        assert providers.eligible_providers_for_tier(tier.value) != [] or tier.value in (
            "private",
        )


def test_real_providers_yaml_private_tier_is_ollama_only():
    assert providers.eligible_providers_for_tier("private") == ["ollama-local"]


def test_real_providers_yaml_ollama_local_is_configured():
    info = providers.get_provider("ollama-local")
    assert info.configured is True

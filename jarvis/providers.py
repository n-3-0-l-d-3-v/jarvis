"""Loader/query interface for providers.yaml — the OmniRoute provider
eligibility table (see that file's own header comment for what this does
and does not centrally enforce yet).

Kept separate from tiers.py: tiers.py decides *which tier* a request gets
and whether that tier conflicts with an agent's floor; this module answers
a different question, *which providers a tier permits* and whether one is
actually usable right now. Two concerns, two modules, matching this
codebase's existing separation (registry.py knows nothing about MCP
transport, tiers.py knows nothing about the registry, etc).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

_DEFAULT_PROVIDERS_YAML = Path(__file__).with_name("providers.yaml")


class ProvidersConfigError(Exception):
    """Raised for malformed providers.yaml."""


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    kind: str
    configured: bool
    notes: str = ""


def _load_raw(providers_yaml_path: Optional[Path] = None) -> dict:
    path = providers_yaml_path or _DEFAULT_PROVIDERS_YAML
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except FileNotFoundError as exc:
        raise ProvidersConfigError(f"providers.yaml not found at {path}") from exc
    if "tiers" not in data or "providers" not in data:
        raise ProvidersConfigError(
            f"{path} must have top-level 'tiers' and 'providers' keys"
        )
    return data


def eligible_providers_for_tier(
    tier: str, *, providers_yaml_path: Optional[Path] = None
) -> list[str]:
    """Providers eligible-in-principle for a tier (not necessarily
    configured/usable right now — see is_provider_usable for that).
    """
    data = _load_raw(providers_yaml_path)
    tiers = data["tiers"]
    if tier not in tiers:
        raise ProvidersConfigError(
            f"unknown tier {tier!r}. Known tiers: {sorted(tiers)}"
        )
    return list(tiers[tier].get("eligible_providers", []))


def get_provider(
    name: str, *, providers_yaml_path: Optional[Path] = None
) -> ProviderInfo:
    data = _load_raw(providers_yaml_path)
    providers = data["providers"]
    if name not in providers:
        raise ProvidersConfigError(
            f"unknown provider {name!r}. Known providers: {sorted(providers)}"
        )
    entry = providers[name]
    # "configured" is explicit for local/shared-pool providers; a
    # personal-key provider is "configured" in the sense that *some* agent
    # owns configuring it themselves — this file doesn't and can't check
    # each agent's actual env vars, so it reports true (the capability
    # exists, per-agent) rather than false (which would misleadingly read
    # as "personal-key auth is broken ecosystem-wide").
    configured = entry.get("configured", entry.get("kind") == "personal-key")
    return ProviderInfo(
        name=name,
        kind=entry.get("kind", "unknown"),
        configured=bool(configured),
        notes=entry.get("notes", "").strip(),
    )


def usable_providers_for_tier(
    tier: str, *, providers_yaml_path: Optional[Path] = None
) -> list[str]:
    """Eligible AND currently configured/usable — the practical answer to
    "what can a request of this tier actually use right now."
    """
    return [
        name
        for name in eligible_providers_for_tier(tier, providers_yaml_path=providers_yaml_path)
        if get_provider(name, providers_yaml_path=providers_yaml_path).configured
    ]

"""Sibling-agent registry: loads jarvis/agents.yaml and resolves each
agent's repo path (env var override, falling back to the default recorded
in that file) plus its launch/health commands.

This module only reads config. It knows nothing about MCP transport (see
mcp_client.py) or tiers (see tiers.py) — kept separate so each concern is
independently testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

_DEFAULT_AGENTS_YAML = Path(__file__).with_name("agents.yaml")


class RegistryError(Exception):
    """Raised for malformed or unresolvable agent registry config."""


@dataclass(frozen=True)
class AgentSpec:
    key: str
    display_name: str
    role: str
    default_sensitivity_tier: str
    path: Path
    working_directory: str
    mcp_launch_command: list[str]
    health_check_command: list[str]
    needs_project_path: bool = False

    @property
    def cwd(self) -> Path:
        """Absolute directory the launch/health commands must run from."""
        return (self.path / self.working_directory).resolve()

    def resolved_mcp_launch_command(self, project_path: Optional[str] = None) -> list[str]:
        """Substitute ``{project_path}`` placeholders (Ultron only)."""
        if self.needs_project_path and not project_path:
            raise RegistryError(
                f"agent '{self.key}' needs a project path to launch its MCP "
                f"server (pass --ultron-project <path> or the equivalent "
                f"for this agent)."
            )
        return [
            part.replace("{project_path}", project_path or "")
            for part in self.mcp_launch_command
        ]


def _resolve_path(entry: dict, key: str) -> Path:
    env_name = entry.get("path_env")
    env_value = os.environ.get(env_name) if env_name else None
    raw = env_value or entry.get("default_path")
    if not raw:
        raise RegistryError(f"agent '{key}' has no path_env value and no default_path set")
    return Path(raw)


def load_registry(agents_yaml_path: Optional[Path] = None) -> dict[str, AgentSpec]:
    """Load and validate jarvis/agents.yaml into a dict of AgentSpec, keyed
    by agent key (e.g. 'friday'). Raises RegistryError on malformed config
    (loud validation, per the privacy spec's "loud validation at startup if
    an agent has no default tier declared" instruction — extended here to
    the whole registry, not just the tier field)."""
    yaml_path = agents_yaml_path or _DEFAULT_AGENTS_YAML
    if not yaml_path.exists():
        raise RegistryError(f"agents registry file not found: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    agents = data.get("agents") or {}
    if not agents:
        raise RegistryError(f"no agents declared in {yaml_path}")

    result: dict[str, AgentSpec] = {}
    required_fields = (
        "display_name",
        "role",
        "default_sensitivity_tier",
        "default_path",
        "mcp_launch_command",
        "health_check_command",
    )
    for key, entry in agents.items():
        missing = [f for f in required_fields if f not in entry]
        if missing:
            raise RegistryError(f"agent '{key}' is missing required field(s): {missing}")
        result[key] = AgentSpec(
            key=key,
            display_name=entry["display_name"],
            role=entry["role"],
            default_sensitivity_tier=entry["default_sensitivity_tier"],
            path=_resolve_path(entry, key),
            working_directory=entry.get("working_directory", "."),
            mcp_launch_command=list(entry["mcp_launch_command"]),
            health_check_command=list(entry["health_check_command"]),
            needs_project_path=bool(entry.get("needs_project_path", False)),
        )
    return result


def get_agent(key: str, agents_yaml_path: Optional[Path] = None) -> AgentSpec:
    registry = load_registry(agents_yaml_path)
    if key not in registry:
        raise RegistryError(f"unknown agent '{key}'. Known agents: {sorted(registry)}")
    return registry[key]

"""Health checking: runs each sibling agent's declared health_check_command
as a subprocess and aggregates the results, plus Jarvis's own self-check.

Two distinct things live here, matching the CLI's two health surfaces:

  - `check_agent_health` / `check_all_agents_health`: used by `jarvis health`
    (the aggregate command) to call each sibling's own health_check_command.
  - `jarvis_self_health`: used by `jarvis --health` (the eager top-level
    flag matching Friday/Ultron/Alfred's own `--health` pattern) to report
    ONLY Jarvis's own status — context store reachable, at least one agent
    config loadable — per agent.yaml's health_check_command: jarvis --health.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from jarvis import __version__
from jarvis.registry import AgentSpec, RegistryError, load_registry
from jarvis.store import ContextStore


def check_agent_health(agent: AgentSpec, timeout: float = 30.0) -> dict:
    """Run one agent's health_check_command as a subprocess and report the
    outcome. Never raises — a failure to launch is reported as unhealthy,
    not as an exception, since this feeds `jarvis health`'s aggregate JSON
    output and one unreachable agent must not crash the whole command."""
    try:
        proc = subprocess.run(
            agent.health_check_command,
            cwd=str(agent.cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return {
            "agent": agent.key,
            "healthy": False,
            "error": f"command not found: {agent.health_check_command[0]} "
            f"({exc}). Is {agent.display_name}'s package installed "
            f"(console script / venv active)?",
        }
    except subprocess.TimeoutExpired:
        return {
            "agent": agent.key,
            "healthy": False,
            "error": f"health_check_command timed out after {timeout}s",
        }
    except OSError as exc:
        return {"agent": agent.key, "healthy": False, "error": str(exc)}

    healthy = proc.returncode == 0
    detail: object = proc.stdout.strip()
    try:
        detail = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        pass

    result = {"agent": agent.key, "healthy": healthy, "detail": detail}
    if not healthy:
        result["error"] = proc.stderr.strip() or f"exit code {proc.returncode}"
    return result


def check_all_agents_health(
    agents_yaml_path: Optional[Path] = None, timeout: float = 30.0
) -> dict:
    """Aggregate health for all registered sibling agents. Used by
    `jarvis health`."""
    try:
        registry = load_registry(agents_yaml_path)
    except RegistryError as exc:
        return {"registry_error": str(exc), "agents": {}}

    agents_status = {
        key: check_agent_health(agent, timeout=timeout) for key, agent in registry.items()
    }
    return {"agents": agents_status}


def jarvis_self_health(
    agents_yaml_path: Optional[Path] = None, db_path: Optional[Path] = None
) -> dict:
    """Jarvis's own health only — the payload for `jarvis --health`, per
    agent.yaml's health_check_command. Deliberately does NOT call out to
    sibling agents (that's `jarvis health`'s job) so this stays fast and
    matches the "report your own status" contract Friday/Ultron/Alfred
    each implement for their own `--health`."""
    context_ok = True
    context_error: Optional[str] = None
    try:
        store = ContextStore(db_path)
        context_ok = store.is_reachable()
        store.close()
    except Exception as exc:  # noqa: BLE001
        context_ok = False
        context_error = str(exc)

    registry_ok = False
    registry_error: Optional[str] = None
    loadable_agents: list[str] = []
    try:
        registry = load_registry(agents_yaml_path)
        loadable_agents = sorted(registry)
        registry_ok = len(loadable_agents) > 0
    except RegistryError as exc:
        registry_error = str(exc)

    healthy = context_ok and registry_ok
    payload = {
        "version": __version__,
        "healthy": healthy,
        "context_store": {"reachable": context_ok, "error": context_error},
        "agent_registry": {
            "loadable": registry_ok,
            "agents": loadable_agents,
            "error": registry_error,
        },
    }
    return payload

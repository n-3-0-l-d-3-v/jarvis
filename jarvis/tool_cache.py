"""Cache of every agent's MCP tool specs (name, description, input schema).

Listing tools means launching each agent's MCP server (~1-3 s each), so a
planner that needs every agent's tools reads this cache instead. It lives
next to the context store (~/.jarvis/tools.json), expires after a day, and is
rebuilt with `jarvis tools --refresh`. Ultron is included only when a project
path is given, since its server is project-scoped.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Callable, Optional

from jarvis.registry import AgentSpec

MAX_AGE_SECONDS = 24 * 3600


def cache_path() -> Path:
    override = os.environ.get("JARVIS_TOOLS_CACHE")
    if override:
        return Path(override)
    db = os.environ.get("JARVIS_DB_PATH")
    base = Path(db).parent if db else Path.home() / ".jarvis"
    return base / "tools.json"


def _load() -> dict:
    try:
        return json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    p = cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")


def get_specs(
    registry: dict[str, AgentSpec],
    *,
    refresh: bool = False,
    ultron_project: Optional[str] = None,
    lister: Optional[Callable] = None,
    now: Optional[float] = None,
) -> dict[str, list[dict]]:
    """{agent_key: [tool specs]} for every agent that can be dispatched to now."""
    from jarvis.mcp_client import list_tool_specs

    lister = lister or (lambda agent, proj: asyncio.run(list_tool_specs(agent, proj)))
    now = now if now is not None else time.time()
    cache = {} if refresh else _load()
    out: dict[str, list[dict]] = {}
    changed = False
    for key, agent in registry.items():
        if agent.mcp_launch_command is None:
            continue
        if agent.needs_project_path and not ultron_project:
            continue
        entry = cache.get(key)
        fresh = entry and now - entry.get("fetched_at", 0) < MAX_AGE_SECONDS
        if not fresh:
            try:
                entry = {"fetched_at": now, "tools": lister(agent, ultron_project)}
            except Exception:  # noqa: BLE001 - an unreachable agent just isn't plannable
                continue
            cache[key] = entry
            changed = True
        out[key] = entry["tools"]
    if changed:
        _save(cache)
    return out

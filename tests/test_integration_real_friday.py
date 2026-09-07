"""Real end-to-end integration test: launches Friday's actual MCP server as
a subprocess (not a mock, not the fake_mcp_server.py fixture) and calls a
real tool on it.

This proves jarvis.mcp_client's wiring works against a genuine sibling
agent, not just against the trivial fake server used by test_mcp_client.py.

Skips (rather than fails) if the Friday repo isn't present at the resolved
path, or if `python -m friday.mcp_server` can't be imported there (missing
deps) — this test intentionally does not require Friday's environment to
exist for the rest of the suite to pass; see README.md "Test discipline".
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from jarvis.mcp_client import call_tool, list_tools
from jarvis.registry import RegistryError, get_agent


def _friday_agent():
    try:
        return get_agent("friday")
    except RegistryError:
        return None


def _friday_importable(agent) -> bool:
    """Cheap precheck: can `friday.mcp_server` be imported in agent.cwd
    with the current interpreter? Avoids a slow subprocess launch attempt
    when deps obviously aren't installed."""
    probe = subprocess.run(
        [sys.executable, "-c", "import friday.mcp_server"],
        cwd=str(agent.cwd),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return probe.returncode == 0


agent = _friday_agent()
skip_reason = None
if agent is None:
    skip_reason = "friday agent not in registry / RegistryError"
elif not agent.path.exists():
    skip_reason = f"friday repo not found at {agent.path} (set JARVIS_FRIDAY_PATH)"
elif not _friday_importable(agent):
    skip_reason = (
        f"friday.mcp_server not importable from {agent.cwd} — its deps "
        f"(see friday/requirements.txt) are not installed in this "
        f"interpreter"
    )

pytestmark = pytest.mark.skipif(skip_reason is not None, reason=skip_reason or "")


@pytest.mark.asyncio
async def test_real_friday_list_tools():
    tools = await list_tools(agent)
    assert "search_notes" in tools
    assert "knowledge_stats" in tools


@pytest.mark.asyncio
async def test_real_friday_call_knowledge_stats():
    result = await call_tool(agent, "knowledge_stats", {})
    assert result.is_error is False
    assert "notes" in result.text.lower()

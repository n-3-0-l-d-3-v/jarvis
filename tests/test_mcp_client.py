import sys
from pathlib import Path

import pytest

from jarvis.mcp_client import DispatchError, call_tool, list_tools
from jarvis.registry import AgentSpec

FAKE_SERVER = Path(__file__).with_name("fake_mcp_server.py")


def _fake_agent(**overrides) -> AgentSpec:
    defaults = dict(
        key="fake",
        display_name="Fake",
        role="testing",
        default_sensitivity_tier="work",
        path=FAKE_SERVER.parent,
        working_directory=".",
        mcp_launch_command=[sys.executable, str(FAKE_SERVER)],
        health_check_command=[sys.executable, "--version"],
        needs_project_path=False,
    )
    defaults.update(overrides)
    return AgentSpec(**defaults)


class TestAgainstFakeServer:
    """These launch a real (if trivial) MCP server subprocess speaking the
    real protocol — not a hand-mocked transport — so the wiring between
    jarvis.mcp_client and the `mcp` SDK is genuinely exercised."""

    @pytest.mark.asyncio
    async def test_list_tools(self):
        tools = await list_tools(_fake_agent())
        assert set(tools) == {"echo", "boom"}

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        result = await call_tool(_fake_agent(), "echo", {"text": "hello"})
        assert result.tool_name == "echo"
        assert "hello" in result.text
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_call_tool_error_path(self):
        result = await call_tool(_fake_agent(), "boom", {})
        assert result.is_error is True
        assert "boom" in result.text.lower()

    @pytest.mark.asyncio
    async def test_needs_project_path_without_one_raises_dispatch_error(self):
        agent = _fake_agent(
            needs_project_path=True,
            mcp_launch_command=[sys.executable, str(FAKE_SERVER), "-P", "{project_path}"],
        )
        with pytest.raises(DispatchError):
            await call_tool(agent, "echo", {"text": "hi"})

    @pytest.mark.asyncio
    async def test_bad_command_raises_dispatch_error(self):
        agent = _fake_agent(mcp_launch_command=["this-binary-does-not-exist-xyz"])
        with pytest.raises(DispatchError):
            await list_tools(agent)

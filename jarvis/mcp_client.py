"""MCP client manager: launches a sibling agent's MCP server as a stdio
subprocess and calls a tool on it.

v1 launches a fresh server subprocess per call (no connection pooling / no
long-lived server process). That's a documented simplification, not a
silent limitation:

    Every `jarvis ask` invocation pays full interpreter-startup +
    MCP-handshake cost for the target agent. For a CLI used a few times a
    day this is unnoticeable; it would matter for a hot-path/voice-latency
    use case. The future optimization is a long-lived per-agent server
    process (or process pool) that Jarvis keeps warm and reuses across
    calls — tracked as a v1 placeholder, not implemented here.

Uses the standard `mcp` PyPI package's stdio client (mcp.client.stdio,
mcp.ClientSession) — this works against Friday, Alfred, and Ultron's MCP
servers identically because all three speak real MCP over stdio (JSON-RPC
2.0, newline-delimited), including Ultron's hand-rolled server (see
ultron/mcp/server.py, ultron/adr/0004 and 0011) which implements the
protocol directly without the `mcp` package for its own zero-dependency
reasons but is still a compliant server from the client's point of view.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from jarvis.registry import AgentSpec, RegistryError


class DispatchError(Exception):
    """Raised for MCP launch/call failures, with enough context to show the
    user a clear error rather than a raw traceback."""


@dataclass
class ToolCallResult:
    tool_name: str
    text: str
    is_error: bool = False
    raw: Any = None


def _launch_params(agent: AgentSpec, project_path: Optional[str]) -> StdioServerParameters:
    try:
        command_parts = agent.resolved_mcp_launch_command(project_path)
    except RegistryError as exc:
        raise DispatchError(str(exc)) from exc

    command, *args = command_parts
    return StdioServerParameters(
        command=command,
        args=args,
        cwd=str(agent.cwd),
    )


async def list_tools(agent: AgentSpec, project_path: Optional[str] = None) -> list[str]:
    """Launch the agent's MCP server, list its tools, and shut it down.
    Mainly useful for diagnostics/tests."""
    params = _launch_params(agent, project_path)
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [t.name for t in result.tools]
    except DispatchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DispatchError(
            f"failed to launch or talk to '{agent.key}' MCP server "
            f"(command={params.command} {params.args}, cwd={params.cwd}): "
            f"{type(exc).__name__}: {exc}"
        ) from exc


async def call_tool(
    agent: AgentSpec,
    tool_name: str,
    arguments: dict,
    project_path: Optional[str] = None,
) -> ToolCallResult:
    """Launch the agent's MCP server, call one tool, shut it down, return
    the result. This is the v1 launch-per-call path described in the
    module docstring."""
    params = _launch_params(agent, project_path)
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                text_parts = []
                for block in result.content or []:
                    text = getattr(block, "text", None)
                    if text is not None:
                        text_parts.append(text)
                is_error = bool(
                    getattr(result, "is_error", None)
                    if getattr(result, "is_error", None) is not None
                    else getattr(result, "isError", False)
                )
                return ToolCallResult(
                    tool_name=tool_name,
                    text="\n".join(text_parts),
                    is_error=is_error,
                    raw=result,
                )
    except DispatchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DispatchError(
            f"failed to launch or talk to '{agent.key}' MCP server "
            f"(command={params.command} {params.args}, cwd={params.cwd}): "
            f"{type(exc).__name__}: {exc}"
        ) from exc

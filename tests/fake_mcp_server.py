"""A minimal real MCP stdio server, used ONLY by tests to exercise
jarvis.mcp_client against a genuine (if trivial) MCP protocol
implementation instead of a hand-mocked transport.

Run directly: `python fake_mcp_server.py`. Speaks stdio MCP using the same
`mcp` PyPI package Friday/Alfred use for their real servers.
"""

from mcp.server.mcpserver import MCPServer

server = MCPServer(name="fake-agent")


@server.tool()
def echo(text: str) -> str:
    """Echo the given text back, prefixed."""
    return f"echo: {text}"


@server.tool()
def boom() -> str:
    """Always raises, to exercise the error path."""
    raise RuntimeError("boom triggered on purpose")


if __name__ == "__main__":
    server.run()

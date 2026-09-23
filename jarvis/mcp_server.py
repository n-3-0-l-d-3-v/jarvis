"""Jarvis as one MCP server: the whole agent ecosystem behind a single connection.

    claude mcp add --transport stdio -s user jarvis -- python -m jarvis.mcp_server

Tools:
  plan(request)                      -> validated multi-step plan, no side effects
  run(request, confirm)              -> plans and executes; refuses unless confirm=true
  route(request)                     -> which agent + tier would handle it
  agent_tool(agent, tool, arguments) -> call one sibling tool directly (tier-checked)
  health(), daily()                  -> ecosystem status and morning briefing

Planning always uses the LOCAL model; privacy tiers are enforced per step exactly
as in the CLI, so a client can never route private-tier work to a non-local agent.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import sys

from mcp.server.mcpserver import MCPServer

server = MCPServer(
    name="jarvis",
    instructions=(
        "Jarvis orchestrates the user's local agents (Friday: notes/knowledge, Alfred: learning, "
        "TARS: code projects, Vision: creative, Ultron: reverse engineering, Wall-E: system health). "
        "Call `plan` first to see what would happen; call `run` with confirm=true only after the "
        "user agrees. `route` and `health` are read-only."
    ),
)


@contextlib.contextmanager
def _quiet():
    """stdout is the MCP transport; keep library prints off it."""
    old = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = old


@server.tool(description="Plan a natural-language request as 1-3 validated tool calls across the agents. No side effects.")
def plan(request: str, agent: str = "") -> str:
    from jarvis.orchestrate import plan_request
    from jarvis.planner import PlanError

    try:
        with _quiet():
            p = plan_request(request, agent=agent or None)
    except PlanError as exc:
        return f"Error: {exc}"
    return p.describe() + ("" if p.allowed else "\nBLOCKED by tier policy.")


@server.tool(description="Plan AND execute a request. Refuses unless confirm=true; show the user the plan (via `plan`) first.")
def run(request: str, confirm: bool = False, agent: str = "") -> str:
    from jarvis.orchestrate import execute_steps, plan_request
    from jarvis.planner import PlanError

    try:
        with _quiet():
            p = plan_request(request, agent=agent or None)
            if not confirm:
                return "Not run (confirm=false). Plan:\n" + p.describe()
            results = execute_steps(p)
    except PlanError as exc:
        return f"Error: {exc}"
    out = []
    for n, r in enumerate(results, 1):
        out.append(f"--- step {n}: {r.step.agent}.{r.step.tool}{' (FAILED)' if r.result.is_error else ''}")
        out.append(r.result.text)
    return "\n".join(out)


@server.tool(description="Which agent and privacy tier would handle a request (read-only).")
def route(request: str) -> str:
    from jarvis.dispatch import route as _route

    with _quiet():
        d = _route(request)
    return json.dumps({"agent": d.agent.key, "tier": d.tier_decision.tier.value, "allowed": d.allowed,
                       "reason": d.classification.reason if d.classification else ""})


@server.tool(description="Call one tool on one agent directly. arguments is a JSON object string. Tier policy still applies.")
def agent_tool(agent: str, tool: str, arguments: str = "{}") -> str:
    from jarvis.dispatch import route as _route
    from jarvis.mcp_client import call_tool
    from jarvis.registry import RegistryError, get_agent

    try:
        args = json.loads(arguments or "{}")
        spec = get_agent(agent)
    except (ValueError, RegistryError) as exc:
        return f"Error: {exc}"
    with _quiet():
        decision = _route(f"{tool} {arguments}", agent_override=agent)
        if not decision.allowed:
            return f"Refused by tier policy: {decision.conflict_reason}"
        result = asyncio.run(call_tool(spec, tool, args))
    return result.text


@server.tool(description="Health of Jarvis and every agent (JSON).")
def health() -> str:
    from jarvis.health import check_all_agents_health, jarvis_self_health

    with _quiet():
        return json.dumps({"jarvis": jarvis_self_health(), "agents": check_all_agents_health()}, indent=1)


@server.tool(description="Morning briefing: agent health plus vault data (reviews due, pending findings, last Wall-E report).")
def daily() -> str:
    from jarvis.health import check_all_agents_health
    from jarvis.vault_briefing import vault_briefing

    with _quiet():
        health_all = check_all_agents_health()
        return json.dumps({"vault": vault_briefing(),
                           "unhealthy": [k for k, v in health_all.items() if isinstance(v, dict) and not v.get("healthy", True)]},
                          indent=1)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

"""Jarvis CLI.

`jarvis --health` is an eager top-level flag (not a subcommand), matching
the pattern Friday (`friday --health`) and Ultron (`ultron --health`) use
for their own agent.yaml health_check_command, and reports ONLY Jarvis's
own status. `jarvis health` (a real subcommand, no leading dashes) is a
different, broader command: it aggregates all three sibling agents' own
health_check_command output plus Jarvis's own self-health. See README.md
"jarvis health vs jarvis --health" for why both exist side by side rather
than picking one — they answer different questions and the ecosystem
contract only fixes the *name* of the self-check flag, not whether an
aggregate command may also exist.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Optional

import click

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from jarvis import __version__
from jarvis.classifier import classify
from jarvis.dispatch import route
from jarvis.health import check_all_agents_health, jarvis_self_health
from jarvis.mcp_client import DispatchError, call_tool
from jarvis.registry import RegistryError
from jarvis.store import AuditLog, ContextStore
from jarvis.tiers import TierError


def _print_json(data: dict) -> None:
    click.echo(json.dumps(data, indent=2, default=str))


@click.group(invoke_without_command=True)
@click.option(
    "--health",
    "show_health",
    is_flag=True,
    default=False,
    help="Print Jarvis's own JSON health report (context store reachable, "
    "at least one sibling agent config loadable) and exit. This is the "
    "ecosystem agent contract's health_check_command — see agent.yaml. "
    "For a report covering the sibling agents too, use `jarvis health`.",
)
@click.version_option(__version__, prog_name="jarvis")
@click.pass_context
def cli(ctx: click.Context, show_health: bool) -> None:
    """Jarvis: orchestrator for the personal multi-agent developer ecosystem."""
    if show_health:
        payload = jarvis_self_health()
        _print_json(payload)
        ctx.exit(0 if payload["healthy"] else 1)
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument("text")
@click.option("--agent", "agent_override", default=None, help="Force routing to this agent (skips the classifier).")
@click.option("--tier", "tier_override", default=None, help="Force this sensitivity tier (still subject to fail-closed refusal against the target agent's declared tier).")
@click.option("--ultron-project", "ultron_project", default=None, help="RE project path, required when routing to Ultron (it is project-scoped, not global).")
@click.option("--tool", "tool_name", default=None, help="MCP tool to call on the target agent. Defaults to that agent's configured default_tool if it has one.")
@click.option("--tool-arg", "tool_args_raw", multiple=True, help="key=value tool argument, repeatable. Overrides/augments the default_tool_arg mapping.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Print machine-readable JSON instead of plain text.")
def ask(
    text: str,
    agent_override: Optional[str],
    tier_override: Optional[str],
    ultron_project: Optional[str],
    tool_name: Optional[str],
    tool_args_raw: tuple[str, ...],
    as_json: bool,
) -> None:
    """Classify intent + tier, dispatch to the right agent's MCP server, print the result."""
    audit = AuditLog()
    context = ContextStore()

    try:
        decision = route(text, agent_override=agent_override, tier_override=tier_override)
    except (RegistryError, TierError) as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)

    agent = decision.agent
    tier = decision.tier_decision.tier

    if not decision.allowed:
        audit.record(agent.key, tier.value, allowed=False, reason=decision.conflict_reason or "")
        click.echo(f"refused: {decision.conflict_reason}", err=True)
        sys.exit(3)

    if agent.needs_project_path and not ultron_project:
        audit.record(agent.key, tier.value, allowed=False, reason="missing --ultron-project")
        click.echo(
            f"error: agent '{agent.key}' needs a project path to launch its "
            f"MCP server. Pass --ultron-project <path>.",
            err=True,
        )
        sys.exit(2)

    resolved_tool = tool_name or agent.default_tool
    tool_arg_key = agent.default_tool_arg

    arguments: dict = {}
    if resolved_tool is None:
        audit.record(agent.key, tier.value, allowed=False, reason="no tool specified and agent has no default_tool")
        click.echo(
            f"error: agent '{agent.key}' has no default_tool configured for "
            f"free-text requests. Pass --tool <name> --tool-arg key=value "
            f"explicitly.",
            err=True,
        )
        sys.exit(2)
    elif not tool_args_raw and tool_arg_key:
        arguments = {tool_arg_key: text}
    else:
        for raw in tool_args_raw:
            if "=" not in raw:
                click.echo(f"error: --tool-arg must be key=value, got '{raw}'", err=True)
                sys.exit(2)
            key, _, value = raw.partition("=")
            arguments[key] = value

    audit.record(agent.key, tier.value, allowed=True, reason=decision.tier_decision.reason)

    try:
        result = asyncio.run(
            call_tool(agent, resolved_tool, arguments, project_path=ultron_project)
        )
    except DispatchError as exc:
        context.record(text, agent.key, tier.value, result_summary=f"DISPATCH ERROR: {exc}")
        click.echo(f"dispatch error: {exc}", err=True)
        sys.exit(4)

    context.record(text, agent.key, tier.value, result_summary=result.text[:500])

    if as_json:
        _print_json(
            {
                "agent": agent.key,
                "tier": tier.value,
                "tool": resolved_tool,
                "is_error": result.is_error,
                "text": result.text,
            }
        )
    else:
        click.echo(f"[agent={agent.key} tier={tier.value} tool={resolved_tool}]")
        click.echo(result.text)

    if result.is_error:
        sys.exit(1)


@click.command(name="route")
@click.argument("text")
@click.option("--agent", "agent_override", default=None, help="Force routing to this agent (skips the classifier).")
@click.option("--tier", "tier_override", default=None, help="Force this sensitivity tier.")
@click.option("--dry-run", "dry_run", is_flag=True, default=True, help="Show routing without dispatching (this is the only mode 'route' supports; the flag exists for readability/scripting).")
@click.option("--json", "as_json", is_flag=True, default=False, help="Print machine-readable JSON instead of plain text.")
def route_cmd(
    text: str,
    agent_override: Optional[str],
    tier_override: Optional[str],
    dry_run: bool,
    as_json: bool,
) -> None:
    """Show which agent and tier would be chosen, without dispatching anything."""
    try:
        decision = route(text, agent_override=agent_override, tier_override=tier_override)
    except (RegistryError, TierError) as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)

    payload = {
        "agent": decision.agent.key,
        "tier": decision.tier_decision.tier.value,
        "tier_reason": decision.tier_decision.reason,
        "path_forced": decision.tier_decision.path_forced,
        "allowed": decision.allowed,
        "conflict_reason": decision.conflict_reason,
        "classification": (
            {
                "reason": decision.classification.reason,
                "scores": decision.classification.scores,
            }
            if decision.classification
            else None
        ),
    }

    if as_json:
        _print_json(payload)
    else:
        click.echo(f"agent:    {payload['agent']}")
        click.echo(f"tier:     {payload['tier']}  ({payload['tier_reason']})")
        click.echo(f"allowed:  {payload['allowed']}")
        if not payload["allowed"]:
            click.echo(f"reason:   {payload['conflict_reason']}")
        if payload["classification"]:
            click.echo(f"routing:  {payload['classification']['reason']}")

    if not decision.allowed:
        sys.exit(3)


cli.add_command(route_cmd, name="route")


@cli.command()
@click.option("--json", "as_json", is_flag=True, default=True, help="Print machine-readable JSON (default).")
def health(as_json: bool) -> None:
    """Aggregate health for all sibling agents plus Jarvis's own self-health."""
    agents_status = check_all_agents_health()
    self_status = jarvis_self_health()
    payload = {"jarvis": self_status, **agents_status}
    _print_json(payload)

    all_healthy = self_status["healthy"] and all(
        a.get("healthy", False) for a in agents_status.get("agents", {}).values()
    )
    sys.exit(0 if all_healthy else 1)


@cli.command()
def daily() -> None:
    """Morning briefing: Jarvis + sibling health, plus Friday's daily_briefing MCP tool if reachable."""
    agents_status = check_all_agents_health()
    self_status = jarvis_self_health()
    payload = {"jarvis": self_status, "health": agents_status}

    try:
        from jarvis.registry import get_agent

        friday = get_agent("friday")
        result = asyncio.run(call_tool(friday, "daily_briefing", {}))
        payload["friday_daily_briefing"] = {
            "ok": not result.is_error,
            "text": result.text,
        }
    except Exception as exc:  # noqa: BLE001
        # Documented v1 gap: don't block `jarvis daily` on Friday's MCP
        # server being reachable. Health-only output is a valid v1 result.
        payload["friday_daily_briefing"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    from jarvis.vault_briefing import vault_briefing

    payload["vault"] = vault_briefing()
    _print_json(payload)



@cli.command(name="listen")
@click.option("--file", "audio_file", type=click.Path(exists=True, dir_okay=False), help="Transcribe this audio file instead of recording.")
@click.option("--seconds", default=6.0, show_default=True, help="Recording length.")
@click.option("--speak", "do_speak", is_flag=True, help="Read the agent's answer aloud.")
@click.option("--dry-run", is_flag=True, help="Only transcribe and show routing; do not dispatch.")
def listen_cmd(audio_file, seconds, do_speak, dry_run):
    """Voice in: transcribe locally, route, and (unless --dry-run) dispatch like `jarvis ask`."""
    import subprocess
    import sys

    from jarvis import voice

    try:
        path = audio_file or str(voice.record(seconds))
        text = voice.transcribe(path)
    except voice.VoiceError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"heard: {text}")
    if not text:
        raise click.ClickException("no speech detected")
    cmd = [sys.executable, "-m", "jarvis.cli", "route" if dry_run else "ask", text] + (["--dry-run"] if dry_run else [])
    out = subprocess.run(cmd, capture_output=True, text=True)
    click.echo(out.stdout.strip() or out.stderr.strip())
    if do_speak and out.stdout.strip() and not dry_run:
        voice.speak(out.stdout.strip()[:400])


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

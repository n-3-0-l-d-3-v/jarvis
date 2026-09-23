"""Turn a natural-language request into one validated MCP tool call, using the
LOCAL model (qwen2.5:7b by default, which supports structured output well).

The model only *proposes*; every proposal is validated against the tool's real
JSON schema (tool exists, required args present, no unknown args) before it is
ever executed, and the plan is always printed. Local-only, so it satisfies every tier.
"""
from __future__ import annotations

import json
import os
import re

from jarvis.ollama_client import OllamaUnavailable, chat

PLANNER_MODEL = os.environ.get("JARVIS_PLANNER_MODEL", "qwen2.5:7b")


class PlanError(Exception):
    pass


def build_prompt(text: str, specs: list[dict]) -> str:
    tools = "\n".join(
        f"- {s['name']}: {s['description'].splitlines()[0] if s['description'] else ''} | args: "
        + json.dumps({k: v.get("type", "string") for k, v in (s["schema"].get("properties") or {}).items()})
        + " | required: " + json.dumps(s["schema"].get("required", []))
        for s in specs
    )
    return (
        "Pick exactly one tool and fill its arguments to satisfy the user request. "
        "Reply with ONLY a JSON object: {\"tool\": \"<name>\", \"arguments\": {...}}. "
        "Use only argument names listed. Do not invent values the request does not imply; "
        "if a required value is missing from the request, put null for it.\n\n"
        f"Tools:\n{tools}\n\nRequest: {text}\nJSON:"
    )


def parse_plan(raw: str, specs: list[dict]) -> tuple[str, dict]:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise PlanError(f"model did not return JSON: {raw[:120]!r}")
    try:
        obj = json.loads(m.group(0))
        tool, args = obj["tool"], obj.get("arguments") or {}
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PlanError(f"malformed plan: {exc}") from exc
    spec = next((s for s in specs if s["name"] == tool), None)
    if spec is None:
        raise PlanError(f"model chose unknown tool {tool!r}; available: {[s['name'] for s in specs]}")
    props = (spec["schema"].get("properties") or {})
    unknown = [k for k in args if k not in props]
    if unknown:
        raise PlanError(f"unknown argument(s) {unknown} for {tool}")
    args = {k: v for k, v in args.items() if v is not None}
    missing = [r for r in spec["schema"].get("required", []) if r not in args]
    if missing:
        raise PlanError(f"missing required argument(s) {missing} for {tool} - say them in your request")
    return tool, args


def plan(text: str, specs: list[dict], model: str = PLANNER_MODEL) -> tuple[str, dict]:
    try:
        raw = chat(model, build_prompt(text, specs), temperature=0.0, timeout=120).text
    except OllamaUnavailable as exc:
        raise PlanError(f"local planner unavailable: {exc}") from exc
    return parse_plan(raw, specs)


# --------------------------------------------------------------------------- #
# Multi-step, cross-agent planning
# --------------------------------------------------------------------------- #
MAX_STEPS = 3
# Ollama structured output: guarantees parseable JSON of this shape.
_MULTI_SCHEMA = {
    "type": "object",
    "properties": {"steps": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
        "type": "object",
        "properties": {"agent": {"type": "string"}, "tool": {"type": "string"}, "arguments": {"type": "object"}},
        "required": ["agent", "tool", "arguments"]}}},
    "required": ["steps"],
}
PREV = "{{prev}}"


def _tool_line(agent: str, s: dict) -> str:
    props = s["schema"].get("properties") or {}
    return (f"- {agent}.{s['name']}: {s['description'].splitlines()[0] if s['description'] else ''} | args: "
            + json.dumps({k: v.get("type", "string") for k, v in props.items()})
            + " | required: " + json.dumps(s["schema"].get("required", [])))


def build_multi_prompt(text: str, specs_by_agent: dict[str, list[dict]]) -> str:
    tools = "\n".join(_tool_line(a, s) for a, specs in sorted(specs_by_agent.items()) for s in specs)
    return (
        f"Plan the SHORTEST sequence (1 to {MAX_STEPS} steps) of tool calls that fulfils the user request. "
        "Most requests need exactly ONE step; only add steps the request explicitly asks for. "
        'Reply with ONLY JSON: {"steps": [{"agent": "<agent>", "tool": "<tool>", "arguments": {...}}]}. '
        "Use only the tools and argument names listed. Do not invent values the request does not imply; "
        f"if a required value is missing, put null. To pass the previous step's output text into an argument, use the literal string {PREV}.\n\n"
        f"Tools (agent.tool):\n{tools}\n\nRequest: {text}\nJSON:"
    )


def parse_multi(raw: str, specs_by_agent: dict[str, list[dict]], request: str | None = None) -> list[tuple[str, str, dict]]:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise PlanError(f"model did not return JSON: {raw[:120]!r}")
    try:
        steps = json.loads(m.group(0))["steps"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PlanError(f"malformed plan: {exc}") from exc
    if not isinstance(steps, list) or not steps:
        raise PlanError("plan has no steps")
    if len(steps) > MAX_STEPS:
        raise PlanError(f"plan has {len(steps)} steps; the limit is {MAX_STEPS}")
    out = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise PlanError(f"step {i + 1} is not an object")
        agent, tool_name = _resolve(step.get("agent"), step.get("tool"), specs_by_agent, i + 1)
        tool, args = parse_plan(json.dumps({"tool": tool_name, "arguments": step.get("arguments")}), specs_by_agent[agent])
        if i == 0 and any(PREV in str(v) for v in args.values()):
            raise PlanError("step 1 cannot reference {{prev}}")
        if request is not None:
            spec = next(s for s in specs_by_agent[agent] if s["name"] == tool)
            args = drop_ungrounded(args, spec["schema"].get("required", []), request)
        out.append((agent, tool, args))
    return out


def _resolve(agent, tool, specs_by_agent: dict[str, list[dict]], n: int) -> tuple[str, str]:
    """Tolerate small models writing "agent.tool" or naming the wrong agent: a
    tool name that exists on exactly one agent identifies that agent."""
    agent = str(agent or "").strip().lower()
    tool = str(tool or "").strip()
    if "." in tool:
        prefix, _, tool = tool.partition(".")
        agent = agent or prefix.lower()
    owners = [a for a, specs in specs_by_agent.items() if any(s["name"] == tool for s in specs)]
    if agent in owners:
        return agent, tool
    if len(owners) == 1:
        return owners[0], tool
    if not owners:
        raise PlanError(f"step {n}: no available agent has a tool named {tool!r}")
    raise PlanError(f"step {n}: tool {tool!r} is ambiguous between {owners}; agent {agent!r} doesn't have it")


_GLUE = {"the", "and", "for", "with", "from", "this", "that", "note", "notes"}


def drop_ungrounded(args: dict, required: list[str], request: str) -> dict:
    """Drop OPTIONAL string arguments whose content never appears in the request:
    small models like to invent sources, tags and descriptions."""
    words = set(re.findall(r"[a-z0-9]{3,}", request.lower()))
    kept = {}
    for k, v in args.items():
        if k in required or not isinstance(v, str) or PREV in v:
            kept[k] = v
            continue
        vw = set(re.findall(r"[a-z0-9]{3,}", v.lower()))
        if vw and vw <= words | _GLUE:
            kept[k] = v
    return kept


def fill_prev(args: dict, prev_text: str, limit: int = 2000) -> dict:
    return {k: (v.replace(PREV, prev_text[:limit]) if isinstance(v, str) else v) for k, v in args.items()}


def plan_multi(text: str, specs_by_agent: dict[str, list[dict]], model: str = PLANNER_MODEL) -> list[tuple[str, str, dict]]:
    try:
        raw = chat(model, build_multi_prompt(text, specs_by_agent), temperature=0.0, timeout=180, fmt=_MULTI_SCHEMA).text
    except OllamaUnavailable as exc:
        raise PlanError(f"local planner unavailable: {exc}") from exc
    return parse_multi(raw, specs_by_agent, request=text)

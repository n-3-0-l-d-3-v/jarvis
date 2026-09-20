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

"""Plan-then-execute core shared by `jarvis do` (CLI) and the Jarvis MCP server.

plan_request() never has side effects: it plans with the local model, validates
every step against the target tool's schema, and runs the tier policy for each
step. execute_steps() runs an already-validated plan in order, stopping at the
first failing step.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from jarvis.dispatch import RouteDecision, route
from jarvis.mcp_client import ToolCallResult, call_tool
from jarvis.planner import PlanError, fill_prev, plan_multi
from jarvis.registry import AgentSpec, load_registry
from jarvis.tool_cache import get_specs


@dataclass
class Step:
    agent: str
    tool: str
    args: dict
    decision: RouteDecision

    @property
    def allowed(self) -> bool:
        return self.decision.allowed

    def describe(self) -> str:
        flag = "" if self.allowed else f"  BLOCKED: {self.decision.conflict_reason}"
        return f"{self.agent}.{self.tool}({self.args})  tier={self.decision.tier_decision.tier.value}{flag}"


@dataclass
class Plan:
    text: str
    steps: list[Step] = field(default_factory=list)
    registry: dict[str, AgentSpec] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return all(s.allowed for s in self.steps)

    def describe(self) -> str:
        return "\n".join(f"{n}. {s.describe()}" for n, s in enumerate(self.steps, 1))


def plan_request(text: str, *, agent: Optional[str] = None, ultron_project: Optional[str] = None) -> Plan:
    registry = load_registry()
    if agent and agent not in registry:
        raise PlanError(f"unknown agent {agent!r}; known: {sorted(registry)}")
    specs = get_specs(registry, ultron_project=ultron_project)
    if agent:
        specs = {agent: specs.get(agent, [])}
    if not any(specs.values()):
        raise PlanError("no dispatchable tools (run `jarvis tools --refresh`)")
    raw_steps = plan_multi(text, specs)
    steps = [Step(a, t, args, route(text, agent_override=a)) for a, t, args in raw_steps]
    return Plan(text, steps, registry)


@dataclass
class StepResult:
    step: Step
    result: ToolCallResult


def execute_steps(plan: Plan, *, ultron_project: Optional[str] = None) -> list[StepResult]:
    if not plan.allowed:
        raise PlanError("plan blocked by tier policy; nothing was run")
    out: list[StepResult] = []
    prev = ""
    for step in plan.steps:
        result = asyncio.run(call_tool(plan.registry[step.agent], step.tool, fill_prev(step.args, prev), ultron_project))
        out.append(StepResult(step, result))
        if result.is_error:
            break
        prev = result.text
    return out

import json

import pytest

from jarvis import planner, tool_cache

SPECS = {
    "friday": [{"name": "capture_note", "description": "Capture", "schema": {"properties": {"text": {"type": "string"}, "source": {"type": "string"}, "tags": {"type": "string"}}, "required": ["text"]}}],
    "tars": [{"name": "scaffold", "description": "Scaffold", "schema": {"properties": {"template": {"type": "string"}, "name": {"type": "string"}}, "required": ["template", "name"]}},
             {"name": "test", "description": "Run tests", "schema": {"properties": {"path": {"type": "string"}}, "required": []}}],
    "vision": [{"name": "test", "description": "dup name", "schema": {"properties": {}, "required": []}}],
}


def _raw(*steps):
    return json.dumps({"steps": [dict(zip(("agent", "tool", "arguments"), s)) for s in steps]})


def test_two_step_plan():
    steps = planner.parse_multi(_raw(("friday", "capture_note", {"text": "x"}), ("tars", "scaffold", {"template": "python-cli", "name": "a"})), SPECS)
    assert [(a, t) for a, t, _ in steps] == [("friday", "capture_note"), ("tars", "scaffold")]


def test_agent_dot_tool_and_wrong_agent_are_resolved_by_unique_tool_name():
    steps = planner.parse_multi(_raw(("alfred", "tars.scaffold", {"template": "t", "name": "n"})), SPECS)
    assert steps[0][:2] == ("tars", "scaffold")


def test_ambiguous_tool_with_wrong_agent_is_rejected():
    with pytest.raises(planner.PlanError, match="ambiguous"):
        planner.parse_multi(_raw(("friday", "test", {})), SPECS)


def test_too_many_steps_rejected():
    step = ("tars", "test", {})
    with pytest.raises(planner.PlanError, match="limit"):
        planner.parse_multi(_raw(step, step, step, step), SPECS)


def test_prev_not_allowed_in_first_step_and_filled_later():
    with pytest.raises(planner.PlanError):
        planner.parse_multi(_raw(("friday", "capture_note", {"text": "{{prev}}"})), SPECS)
    assert planner.fill_prev({"text": "saw: {{prev}}", "n": 1}, "OUT") == {"text": "saw: OUT", "n": 1}


def test_invented_optional_args_are_dropped_required_kept():
    req = "capture a note that git rebase rewrites history"
    steps = planner.parse_multi(_raw(("friday", "capture_note", {"text": "totally different", "source": "git documentation", "tags": "git"})), SPECS, request=req)
    assert steps[0][2] == {"text": "totally different", "tags": "git"}


def test_tool_cache_reuses_fresh_entries_and_skips_unplannable(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("JARVIS_TOOLS_CACHE", str(tmp_path / "tools.json"))
    reg = {
        "a": SimpleNamespace(mcp_launch_command=["x"], needs_project_path=False),
        "u": SimpleNamespace(mcp_launch_command=["x"], needs_project_path=True),
        "v": SimpleNamespace(mcp_launch_command=None, needs_project_path=False),
    }
    calls = []
    lister = lambda agent, proj: calls.append(agent) or [{"name": "t"}]  # noqa: E731
    assert tool_cache.get_specs(reg, lister=lister, now=1000) == {"a": [{"name": "t"}]}
    tool_cache.get_specs(reg, lister=lister, now=2000)
    assert len(calls) == 1  # second call served from cache
    tool_cache.get_specs(reg, lister=lister, now=1000 + tool_cache.MAX_AGE_SECONDS + 1)
    assert len(calls) == 2  # expired -> re-listed

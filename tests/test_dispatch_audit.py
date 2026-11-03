"""Every dispatch path writes the audit log Wall-E's privacy audit reads.

Before this, only `jarvis ask` did: the real ~/.jarvis/jarvis.db held 2 rows
after weeks of `jarvis do` use, so Wall-E could not see those dispatches.
"""
import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest

from jarvis import orchestrate
from jarvis.planner import PlanError
from jarvis.store import AuditLog


def _decision(allowed=True, tier="work"):
    return SimpleNamespace(allowed=allowed, conflict_reason=None if allowed else "private tier needs a local agent",
                           tier_decision=SimpleNamespace(tier=SimpleNamespace(value=tier), reason="agent floor"))


def _rows(db):
    con = sqlite3.connect(db)
    rows = con.execute("select agent, tier, allowed, reason, detail from audit_entries order by id").fetchall()
    con.close()
    return rows


def _fake_call(calls):
    async def call(spec, tool, args, project=None):
        calls.append(tool)
        return SimpleNamespace(text="ok", is_error=False)
    return call


def test_execute_steps_audits_each_allowed_step(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrate, "call_tool", _fake_call(calls))
    plan = orchestrate.Plan("t", [orchestrate.Step("friday", "capture_note", {}, _decision()),
                                  orchestrate.Step("tars", "scaffold", {}, _decision(tier="work"))], {"friday": 1, "tars": 2})
    db = tmp_path / "a.db"
    orchestrate.execute_steps(plan, audit=AuditLog(db), via="cli-do")
    rows = _rows(db)
    assert [(r[0], r[2]) for r in rows] == [("friday", 1), ("tars", 1)]
    assert json.loads(rows[0][4]) == {"tool": "capture_note", "via": "cli-do"}
    assert calls == ["capture_note", "scaffold"]


def test_blocked_plan_is_audited_as_refused_and_nothing_runs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrate, "call_tool", _fake_call(calls))
    plan = orchestrate.Plan("t", [orchestrate.Step("friday", "capture_note", {}, _decision(False, "private"))], {"friday": 1})
    db = tmp_path / "a.db"
    with pytest.raises(PlanError):
        orchestrate.execute_steps(plan, audit=AuditLog(db))
    assert [(r[0], r[1], r[2]) for r in _rows(db)] == [("friday", "private", 0)]
    assert calls == []


def test_mcp_agent_tool_audits_allowed_and_refused(monkeypatch, tmp_path):
    import os
    from jarvis import dispatch, mcp_client, mcp_server

    calls = []
    monkeypatch.setattr(mcp_client, "call_tool", _fake_call(calls))
    for allowed in (True, False):
        monkeypatch.setattr(dispatch, "route", lambda text, agent_override=None, a=allowed: _decision(a, "personal-token"))
        asyncio.run(mcp_server.server.call_tool("agent_tool", {"agent": "friday", "tool": "today"}))
    rows = _rows(os.environ["JARVIS_DB_PATH"])
    assert [(r[0], r[2], json.loads(r[4])["via"]) for r in rows] == [("friday", 1, "mcp-agent_tool"), ("friday", 0, "mcp-agent_tool")]
    assert calls == ["today"]

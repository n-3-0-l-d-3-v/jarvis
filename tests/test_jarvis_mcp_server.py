import asyncio

from jarvis import mcp_server, orchestrate


def _call(name, args):
    res = asyncio.run(mcp_server.server.call_tool(name, args))
    return str(res)


def test_tools_registered():
    names = {t.name for t in asyncio.run(mcp_server.server.list_tools())}
    assert names == {"plan", "run", "route", "agent_tool", "health", "daily"}


class _FakePlan:
    allowed = True
    steps = [object()]

    def describe(self):
        return "1. tars.scaffold({'name': 'x'})"


def test_run_without_confirm_executes_nothing(monkeypatch):
    executed = []
    monkeypatch.setattr(orchestrate, "plan_request", lambda *a, **k: _FakePlan())
    monkeypatch.setattr(orchestrate, "execute_steps", lambda *a, **k: executed.append(1) or [])
    out = _call("run", {"request": "make a project called x"})
    assert "Not run" in out and "tars.scaffold" in out and executed == []


def test_run_with_confirm_executes(monkeypatch):
    executed = []
    monkeypatch.setattr(orchestrate, "plan_request", lambda *a, **k: _FakePlan())
    monkeypatch.setattr(orchestrate, "execute_steps", lambda *a, **k: executed.append(1) or [])
    _call("run", {"request": "make a project called x", "confirm": True})
    assert executed == [1]


def test_agent_tool_rejects_bad_json_and_unknown_agent():
    assert "Error" in _call("agent_tool", {"agent": "friday", "tool": "t", "arguments": "{not json"})
    assert "Error" in _call("agent_tool", {"agent": "nobody", "tool": "t"})

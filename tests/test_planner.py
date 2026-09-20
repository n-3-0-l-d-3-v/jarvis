import pytest

from jarvis import planner

SPECS = [
    {"name": "scaffold", "description": "Scaffold a project", "schema": {"properties": {"template": {"type": "string"}, "name": {"type": "string"}, "dest": {"type": "string"}}, "required": ["template", "name"]}},
    {"name": "test", "description": "Run tests", "schema": {"properties": {"path": {"type": "string"}}, "required": []}},
]


def test_valid_plan():
    assert planner.parse_plan('sure {"tool":"scaffold","arguments":{"template":"python-cli","name":"demo","dest":null}}', SPECS) == ("scaffold", {"template": "python-cli", "name": "demo"})


def test_unknown_tool_rejected():
    with pytest.raises(planner.PlanError):
        planner.parse_plan('{"tool":"rm_rf","arguments":{}}', SPECS)


def test_unknown_arg_rejected():
    with pytest.raises(planner.PlanError):
        planner.parse_plan('{"tool":"test","arguments":{"evil":"1"}}', SPECS)


def test_missing_required_rejected():
    with pytest.raises(planner.PlanError, match="missing required"):
        planner.parse_plan('{"tool":"scaffold","arguments":{"template":"x","name":null}}', SPECS)


def test_no_json_rejected():
    with pytest.raises(planner.PlanError):
        planner.parse_plan("I think you should scaffold", SPECS)

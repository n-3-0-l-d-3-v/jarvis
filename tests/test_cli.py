import json

import pytest
from click.testing import CliRunner

from jarvis.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DB_PATH", str(tmp_path / "jarvis-test.db"))
    yield


class TestRouteCommand:
    def test_route_dry_run_json_defaults_to_friday_with_no_keyword_hits(self, runner):
        result = runner.invoke(cli, ["route", "explain hash maps to me", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["agent"] == "friday"  # no keyword hits -> classifier default

    def test_route_alfred_keyword_dry_run(self, runner):
        result = runner.invoke(cli, ["route", "give me a hint for this leetcode problem", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["agent"] == "alfred"
        assert payload["tier"] == "personal-token"
        assert payload["allowed"] is True

    def test_route_agent_override(self, runner):
        result = runner.invoke(cli, ["route", "anything", "--agent", "ultron", "--json"])
        payload = json.loads(result.output)
        assert payload["agent"] == "ultron"
        assert payload["tier"] == "private"

    def test_route_unknown_agent_errors(self, runner):
        result = runner.invoke(cli, ["route", "anything", "--agent", "nonexistent"])
        assert result.exit_code == 2

    def test_route_private_override_to_friday_refused(self, runner):
        result = runner.invoke(
            cli, ["route", "anything", "--agent", "friday", "--tier", "private", "--json"]
        )
        payload = json.loads(result.output)
        assert payload["allowed"] is False
        assert result.exit_code == 3

    def test_route_plain_text_output(self, runner):
        result = runner.invoke(cli, ["route", "capture this note"])
        assert result.exit_code == 0, result.output
        assert "agent:" in result.output
        assert "tier:" in result.output


class TestHealthFlag:
    def test_jarvis_health_flag_prints_json(self, runner):
        result = runner.invoke(cli, ["--health"])
        payload = json.loads(result.output)
        assert "context_store" in payload
        assert "agent_registry" in payload
        assert result.exit_code in (0, 1)


class TestHealthCommand:
    def test_health_command_runs_and_prints_json(self, runner):
        # This calls out to real subprocess health checks for each sibling
        # agent, which may or may not be installed on the test machine —
        # we only assert the shape and that it doesn't crash.
        result = runner.invoke(cli, ["health"])
        payload = json.loads(result.output)
        assert "jarvis" in payload
        assert "agents" in payload
        assert set(payload["agents"]) == {"friday", "ultron", "alfred"}


class TestAskCommand:
    def test_ask_unknown_agent_override_errors(self, runner):
        result = runner.invoke(cli, ["ask", "hello", "--agent", "nonexistent"])
        assert result.exit_code == 2

    def test_ask_ultron_without_project_path_fails_clearly(self, runner):
        result = runner.invoke(cli, ["ask", "hello", "--agent", "ultron"])
        assert result.exit_code == 2
        assert "ultron-project" in result.output or "project path" in result.output

    def test_ask_private_override_to_friday_refused_before_dispatch(self, runner):
        result = runner.invoke(
            cli, ["ask", "hello", "--agent", "friday", "--tier", "private"]
        )
        assert result.exit_code == 3
        assert "refused" in result.output

    def test_ask_agent_without_default_tool_and_no_explicit_tool_errors(self, runner):
        # alfred has no default_tool; without --tool this must fail cleanly,
        # not crash trying to guess an argument.
        result = runner.invoke(cli, ["ask", "hello", "--agent", "alfred"])
        assert result.exit_code == 2
        assert "default_tool" in result.output or "--tool" in result.output


class TestDailyCommand:
    def test_daily_runs_and_prints_json(self, runner):
        result = runner.invoke(cli, ["daily"])
        payload = json.loads(result.output)
        assert "jarvis" in payload
        assert "health" in payload
        assert "friday_daily_briefing" in payload

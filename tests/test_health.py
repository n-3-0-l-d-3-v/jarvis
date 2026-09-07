import json
import sys
import textwrap

import pytest

from jarvis.health import check_agent_health, check_all_agents_health, jarvis_self_health
from jarvis.registry import AgentSpec


def _script_agent(tmp_path, script_body: str, key="scripty") -> AgentSpec:
    script = tmp_path / "script.py"
    script.write_text(textwrap.dedent(script_body), encoding="utf-8")
    return AgentSpec(
        key=key,
        display_name="Scripty",
        role="testing",
        default_sensitivity_tier="work",
        path=tmp_path,
        working_directory=".",
        mcp_launch_command=[sys.executable, str(script)],
        health_check_command=[sys.executable, str(script)],
    )


class TestCheckAgentHealth:
    def test_healthy_agent_json_output(self, tmp_path):
        agent = _script_agent(
            tmp_path,
            """
            import json
            print(json.dumps({"ok": True}))
            """,
        )
        result = check_agent_health(agent)
        assert result["healthy"] is True
        assert result["detail"] == {"ok": True}

    def test_unhealthy_agent_nonzero_exit(self, tmp_path):
        agent = _script_agent(
            tmp_path,
            """
            import sys
            print("boom", file=sys.stderr)
            sys.exit(1)
            """,
        )
        result = check_agent_health(agent)
        assert result["healthy"] is False
        assert "boom" in result["error"]

    def test_missing_command_reports_unhealthy_not_exception(self, tmp_path):
        agent = AgentSpec(
            key="ghost",
            display_name="Ghost",
            role="testing",
            default_sensitivity_tier="work",
            path=tmp_path,
            working_directory=".",
            mcp_launch_command=["this-binary-does-not-exist-xyz"],
            health_check_command=["this-binary-does-not-exist-xyz"],
        )
        result = check_agent_health(agent)
        assert result["healthy"] is False
        assert "not found" in result["error"]


class TestCheckAllAgentsHealth:
    def test_aggregates_mixed_healthy_and_unhealthy(self, tmp_path, monkeypatch):
        healthy_script = tmp_path / "healthy.py"
        healthy_script.write_text(
            "import json; print(json.dumps({'ok': True}))", encoding="utf-8"
        )
        unhealthy_script = tmp_path / "unhealthy.py"
        unhealthy_script.write_text(
            "import sys; sys.exit(1)", encoding="utf-8"
        )

        tmp_path_j = json.dumps(str(tmp_path))
        exe_j = json.dumps(sys.executable)
        healthy_j = json.dumps(str(healthy_script))
        unhealthy_j = json.dumps(str(unhealthy_script))

        agents_yaml = tmp_path / "agents.yaml"
        agents_yaml.write_text(
            textwrap.dedent(
                f"""
                agents:
                  good:
                    display_name: Good
                    role: testing
                    default_sensitivity_tier: work
                    path_env: JARVIS_TEST_GOOD_PATH
                    default_path: {tmp_path_j}
                    working_directory: "."
                    mcp_launch_command: [{exe_j}, {healthy_j}]
                    health_check_command: [{exe_j}, {healthy_j}]
                  bad:
                    display_name: Bad
                    role: testing
                    default_sensitivity_tier: work
                    path_env: JARVIS_TEST_BAD_PATH
                    default_path: {tmp_path_j}
                    working_directory: "."
                    mcp_launch_command: [{exe_j}, {unhealthy_j}]
                    health_check_command: [{exe_j}, {unhealthy_j}]
                """
            ),
            encoding="utf-8",
        )
        monkeypatch.delenv("JARVIS_TEST_GOOD_PATH", raising=False)
        monkeypatch.delenv("JARVIS_TEST_BAD_PATH", raising=False)

        result = check_all_agents_health(agents_yaml)
        assert result["agents"]["good"]["healthy"] is True
        assert result["agents"]["bad"]["healthy"] is False


class TestJarvisSelfHealth:
    def test_healthy_when_db_and_registry_ok(self, tmp_path):
        db_path = tmp_path / "jarvis.db"
        payload = jarvis_self_health(db_path=db_path)
        assert payload["context_store"]["reachable"] is True
        assert payload["agent_registry"]["loadable"] is True
        assert payload["healthy"] is True

    def test_unhealthy_when_registry_missing(self, tmp_path):
        db_path = tmp_path / "jarvis.db"
        payload = jarvis_self_health(
            agents_yaml_path=tmp_path / "does-not-exist.yaml", db_path=db_path
        )
        assert payload["agent_registry"]["loadable"] is False
        assert payload["healthy"] is False

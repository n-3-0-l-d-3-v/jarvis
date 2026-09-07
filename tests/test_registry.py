import textwrap

import pytest

from jarvis.registry import RegistryError, get_agent, load_registry


@pytest.fixture
def sample_yaml(tmp_path):
    content = textwrap.dedent(
        """
        agents:
          alpha:
            display_name: Alpha
            role: testing
            default_sensitivity_tier: work
            path_env: JARVIS_TEST_ALPHA_PATH
            default_path: "/default/alpha"
            working_directory: "."
            mcp_launch_command: ["python", "-m", "alpha.mcp"]
            health_check_command: ["alpha", "--health"]
            needs_project_path: false
          beta:
            display_name: Beta
            role: testing-project-scoped
            default_sensitivity_tier: private
            path_env: JARVIS_TEST_BETA_PATH
            default_path: "/default/beta"
            working_directory: "."
            mcp_launch_command: ["beta", "-P", "{project_path}", "mcp"]
            health_check_command: ["beta", "--health"]
            needs_project_path: true
        """
    )
    path = tmp_path / "agents.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_registry_defaults(sample_yaml, monkeypatch):
    monkeypatch.delenv("JARVIS_TEST_ALPHA_PATH", raising=False)
    registry = load_registry(sample_yaml)
    assert set(registry) == {"alpha", "beta"}
    assert str(registry["alpha"].path) == "\\default\\alpha" or str(
        registry["alpha"].path
    ).endswith("default/alpha") or str(registry["alpha"].path).endswith(
        "default\\alpha"
    )
    assert registry["alpha"].default_sensitivity_tier == "work"
    assert registry["beta"].needs_project_path is True


def test_env_var_overrides_default_path(sample_yaml, monkeypatch, tmp_path):
    override = tmp_path / "custom-alpha"
    monkeypatch.setenv("JARVIS_TEST_ALPHA_PATH", str(override))
    registry = load_registry(sample_yaml)
    assert registry["alpha"].path == override


def test_get_agent_unknown_raises(sample_yaml):
    with pytest.raises(RegistryError):
        get_agent("nonexistent", sample_yaml)


def test_get_agent_known(sample_yaml, monkeypatch):
    monkeypatch.delenv("JARVIS_TEST_ALPHA_PATH", raising=False)
    agent = get_agent("alpha", sample_yaml)
    assert agent.display_name == "Alpha"


def test_missing_file_raises(tmp_path):
    with pytest.raises(RegistryError):
        load_registry(tmp_path / "does-not-exist.yaml")


def test_missing_required_field_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        textwrap.dedent(
            """
            agents:
              broken:
                display_name: Broken
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(RegistryError):
        load_registry(path)


def test_needs_project_path_without_project_raises(sample_yaml, monkeypatch):
    monkeypatch.delenv("JARVIS_TEST_BETA_PATH", raising=False)
    agent = get_agent("beta", sample_yaml)
    with pytest.raises(Exception):
        agent.resolved_mcp_launch_command()


def test_needs_project_path_with_project_substitutes(sample_yaml, monkeypatch):
    monkeypatch.delenv("JARVIS_TEST_BETA_PATH", raising=False)
    agent = get_agent("beta", sample_yaml)
    cmd = agent.resolved_mcp_launch_command(project_path="/some/re/project")
    assert cmd == ["beta", "-P", "/some/re/project", "mcp"]


def test_real_agents_yaml_loads():
    """Sanity check against the actual shipped jarvis/agents.yaml."""
    registry = load_registry()
    assert set(registry) == {"friday", "ultron", "alfred", "tars", "vision"}
    assert registry["ultron"].needs_project_path is True
    assert registry["friday"].needs_project_path is False
    assert registry["alfred"].working_directory == "apps/api"

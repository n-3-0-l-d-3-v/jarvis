"""Tests for jarvis.local_classifier — the Phase 5 upgrade over the v1
keyword classifier. Every test monkeypatches the ollama_client seam
(local_classifier_available / chat) rather than talking to a real server,
except none here need a real one to prove the fallback logic is correct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis import local_classifier
from jarvis.ollama_client import OllamaResponse, OllamaUnavailable
from jarvis.registry import AgentSpec


def _agent(key: str, role: str) -> AgentSpec:
    return AgentSpec(
        key=key,
        display_name=key.title(),
        role=role,
        default_sensitivity_tier="work",
        path=Path("."),
        working_directory=".",
        mcp_launch_command=["true"],
        health_check_command=["true"],
    )


@pytest.fixture
def registry() -> dict[str, AgentSpec]:
    return {
        "friday": _agent("friday", "knowledge-capture-and-writing"),
        "alfred": _agent("alfred", "learning-and-upskilling"),
        "ultron": _agent("ultron", "reverse-engineering-and-security"),
        "tars": _agent("tars", "code-build-test-scaffolding"),
        "vision": _agent("vision", "creative-and-ideation"),
    }


def test_falls_back_to_keyword_when_unreachable(monkeypatch, registry):
    monkeypatch.setattr(local_classifier, "is_reachable", lambda: False)
    result = local_classifier.classify("capture this note about Redis", registry)
    assert result.agent == "friday"
    assert "keyword" in result.reason or "local model" not in result.reason


def test_falls_back_to_keyword_when_model_not_pulled(monkeypatch, registry):
    monkeypatch.setattr(local_classifier, "is_reachable", lambda: True)
    monkeypatch.setattr(local_classifier, "list_models", lambda: ["llama3:8b"])
    result = local_classifier.classify("capture this note about Redis", registry)
    assert result.agent == "friday"


def test_uses_local_model_when_available_and_returns_known_agent(monkeypatch, registry):
    monkeypatch.setattr(local_classifier, "is_reachable", lambda: True)
    monkeypatch.setattr(local_classifier, "list_models", lambda: ["qwen2.5:3b"])
    monkeypatch.setattr(
        local_classifier,
        "chat",
        lambda model, prompt: OllamaResponse(text="alfred", model=model),
    )
    result = local_classifier.classify("explain hash maps", registry)
    assert result.agent == "alfred"
    assert "local model" in result.reason


def test_fixes_the_known_keyword_classifier_gap(monkeypatch, registry):
    """The exact case classifier.py's own module docstring calls out as its
    known gap — no keyword hits, silently defaulted to friday. The local
    classifier (mocked here to behave like a competent model would) must
    place it correctly.
    """
    monkeypatch.setattr(local_classifier, "is_reachable", lambda: True)
    monkeypatch.setattr(local_classifier, "list_models", lambda: ["qwen2.5:3b"])
    monkeypatch.setattr(
        local_classifier,
        "chat",
        lambda model, prompt: OllamaResponse(text="alfred", model=model),
    )
    result = local_classifier.classify("explain hash maps", registry)
    assert result.agent == "alfred"


def test_handles_model_wrapping_its_answer(monkeypatch, registry):
    monkeypatch.setattr(local_classifier, "is_reachable", lambda: True)
    monkeypatch.setattr(local_classifier, "list_models", lambda: ["qwen2.5:3b"])
    monkeypatch.setattr(
        local_classifier,
        "chat",
        lambda model, prompt: OllamaResponse(text="Agent: tars", model=model),
    )
    result = local_classifier.classify("scaffold a new fastapi project", registry)
    assert result.agent == "tars"


def test_falls_back_when_model_returns_unknown_agent(monkeypatch, registry):
    monkeypatch.setattr(local_classifier, "is_reachable", lambda: True)
    monkeypatch.setattr(local_classifier, "list_models", lambda: ["qwen2.5:3b"])
    monkeypatch.setattr(
        local_classifier,
        "chat",
        lambda model, prompt: OllamaResponse(text="skynet", model=model),
    )
    result = local_classifier.classify("capture this note about Redis", registry)
    assert result.agent == "friday"
    assert "unrecognized agent" in result.reason


def test_falls_back_when_chat_raises_ollama_unavailable(monkeypatch, registry):
    monkeypatch.setattr(local_classifier, "is_reachable", lambda: True)
    monkeypatch.setattr(local_classifier, "list_models", lambda: ["qwen2.5:3b"])

    def _raise(model, prompt):
        raise OllamaUnavailable("model unloaded mid-request")

    monkeypatch.setattr(local_classifier, "chat", _raise)
    result = local_classifier.classify("capture this note about Redis", registry)
    assert result.agent == "friday"


def test_disable_env_var_forces_keyword_fallback(monkeypatch, registry):
    monkeypatch.setenv(local_classifier.DISABLE_ENV_VAR, "1")
    monkeypatch.setattr(local_classifier, "is_reachable", lambda: True)
    monkeypatch.setattr(local_classifier, "list_models", lambda: ["qwen2.5:3b"])
    assert local_classifier.local_classifier_available() is False
    result = local_classifier.classify("capture this note about Redis", registry)
    assert result.agent == "friday"


def test_prompt_includes_every_registry_agent_and_its_role(registry):
    prompt = local_classifier._build_prompt("do something", registry)
    for key, spec in registry.items():
        assert key in prompt
        assert spec.role in prompt


def test_model_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv(local_classifier.MODEL_ENV_VAR, "custom-model:latest")
    assert local_classifier._configured_model() == "custom-model:latest"

"""Tests for jarvis.ollama_client. No real Ollama server needed — every
test monkeypatches urllib.request.urlopen with a fake response, matching
the module's own boundary (it only ever talks to urllib, so that's the
one seam to fake).
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from jarvis import ollama_client


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_is_reachable_true_on_200(monkeypatch):
    monkeypatch.setattr(
        ollama_client.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse({"models": []}, status=200),
    )
    assert ollama_client.is_reachable() is True


def test_is_reachable_false_on_connection_error(monkeypatch):
    def _raise(*a, **k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(ollama_client.urllib.request, "urlopen", _raise)
    assert ollama_client.is_reachable() is False


def test_list_models_returns_names(monkeypatch):
    monkeypatch.setattr(
        ollama_client.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(
            {"models": [{"name": "qwen2.5:3b"}, {"name": "qwen2.5:7b"}]}
        ),
    )
    assert ollama_client.list_models() == ["qwen2.5:3b", "qwen2.5:7b"]


def test_list_models_empty_on_unreachable(monkeypatch):
    def _raise(*a, **k):
        raise urllib.error.URLError("nope")

    monkeypatch.setattr(ollama_client.urllib.request, "urlopen", _raise)
    assert ollama_client.list_models() == []


def test_chat_returns_content(monkeypatch):
    monkeypatch.setattr(
        ollama_client.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(
            {"model": "qwen2.5:3b", "message": {"content": "friday"}}
        ),
    )
    result = ollama_client.chat("qwen2.5:3b", "route this: capture a note")
    assert result.text == "friday"
    assert result.model == "qwen2.5:3b"


def test_chat_raises_ollama_unavailable_on_connection_error(monkeypatch):
    def _raise(*a, **k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(ollama_client.urllib.request, "urlopen", _raise)
    with pytest.raises(ollama_client.OllamaUnavailable):
        ollama_client.chat("qwen2.5:3b", "hello")


def test_chat_raises_ollama_unavailable_on_api_error_payload(monkeypatch):
    monkeypatch.setattr(
        ollama_client.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse({"error": "model 'x' not found"}),
    )
    with pytest.raises(ollama_client.OllamaUnavailable):
        ollama_client.chat("nonexistent-model", "hello")


def test_chat_raises_ollama_unavailable_on_empty_content(monkeypatch):
    monkeypatch.setattr(
        ollama_client.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse({"model": "qwen2.5:3b", "message": {}}),
    )
    with pytest.raises(ollama_client.OllamaUnavailable):
        ollama_client.chat("qwen2.5:3b", "hello")


def test_context_options_only_grows_the_window_when_needed():
    from jarvis.ollama_client import context_options
    assert context_options("short prompt") == {}
    assert context_options("x" * 12000) == {"num_ctx": 8192}
    assert context_options("x" * 50000) == {"num_ctx": 16384}
    assert context_options("x" * 10**7) == {"num_ctx": 32768}

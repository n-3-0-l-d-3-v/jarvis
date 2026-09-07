"""Minimal client for a local Ollama server's HTTP API.

Stdlib-only (urllib), matching this ecosystem's preference for not dragging
in a dependency for something this small (see Ultron's own zero-runtime-
dependency ADR for the stronger version of this reasoning). Every call is
local-only by construction: the host defaults to 127.0.0.1 and there is no
parameter that lets a caller point this at a remote address, which is the
correct shape for something that only ever needs to satisfy the `private`/
`work` tiers (see omniroute-privacy-spec.md) — there is nothing to guard
against leaving the machine because there is no code path that can.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 15.0


class OllamaUnavailable(Exception):
    """Raised when the local Ollama server can't be reached, doesn't have the
    requested model, or returns something this client can't parse. Callers
    in this codebase are expected to catch this and fall back to a
    non-local-model code path (see local_classifier.py) rather than let it
    propagate as a hard failure — a missing/unpulled model is an expected,
    recoverable state, not a bug.
    """


@dataclass(frozen=True)
class OllamaResponse:
    text: str
    model: str


def is_reachable(*, host: str = DEFAULT_HOST, timeout: float = 2.0) -> bool:
    """Cheap reachability check — does NOT verify any particular model is
    pulled, only that something is listening and speaks the Ollama API.
    """
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def list_models(*, host: str = DEFAULT_HOST, timeout: float = 5.0) -> list[str]:
    """Names of models currently pulled. Empty list (not an exception) if
    the server is unreachable — callers that need to distinguish
    "unreachable" from "reachable but nothing pulled" should call
    is_reachable() first.
    """
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        return []
    return [m.get("name", "") for m in payload.get("models", [])]


def chat(
    model: str,
    prompt: str,
    *,
    host: str = DEFAULT_HOST,
    timeout: float = DEFAULT_TIMEOUT,
    temperature: float = 0.0,
) -> OllamaResponse:
    """One-shot, non-streaming chat completion. temperature=0.0 by default
    since this client's first real caller (local_classifier.py) wants
    deterministic routing decisions, not creative ones — pass a higher
    value explicitly for callers that want otherwise.
    """
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": temperature},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{host}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise OllamaUnavailable(f"could not reach Ollama at {host}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OllamaUnavailable(f"Ollama at {host} returned unparseable JSON: {exc}") from exc

    if "error" in payload:
        raise OllamaUnavailable(f"Ollama returned an error: {payload['error']}")

    message = payload.get("message", {})
    content = message.get("content")
    if not content:
        raise OllamaUnavailable(f"Ollama response had no message content: {payload!r}")

    return OllamaResponse(text=content, model=payload.get("model", model))

"""Phase 5 intent classifier: a local Ollama model, with the v1 keyword
classifier (classifier.py) as an automatic, silent-to-the-caller fallback.

This is the "replace the v1 placeholder with a local-model classifier" work
classifier.py's own docstring said was tracked for Phase 5. Two problems
solved at once by building the prompt from the live agent registry instead
of a hardcoded keyword table:

1. The keyword classifier's known gap -- "explain hash maps" matches no
   keyword and silently defaults to Friday -- a model reading each agent's
   actual `role` string can place a request like that correctly.
2. The keyword classifier never learned about TARS/Vision (added to the
   registry after it was written) -- this classifier reads whichever
   agents are in the registry *right now*, so a sixth or seventh agent
   added later needs no classifier code change at all.

Falls back to the keyword classifier -- not to an error -- whenever Ollama
is unreachable, the configured model isn't pulled, or the model's response
doesn't parse to a known agent key. A misbehaving local model must never
make Jarvis less useful than it was in v1.
"""

from __future__ import annotations

import os

from jarvis.classifier import ClassificationResult
from jarvis.classifier import classify as keyword_classify
from jarvis.ollama_client import OllamaUnavailable, chat, is_reachable, list_models
from jarvis.registry import AgentSpec

DEFAULT_MODEL = "qwen2.5:3b"
MODEL_ENV_VAR = "JARVIS_CLASSIFIER_MODEL"
DISABLE_ENV_VAR = "JARVIS_DISABLE_LOCAL_CLASSIFIER"


def _build_prompt(text: str, registry: dict[str, AgentSpec]) -> str:
    agent_lines = "\n".join(
        f"- {key}: {spec.role}" for key, spec in sorted(registry.items())
    )
    return (
        "You are a router. Given a user request and a list of specialist "
        "agents (name: what it does), reply with ONLY the single agent name "
        "that should handle the request. No punctuation, no explanation, "
        "just the name exactly as written below.\n\n"
        f"Agents:\n{agent_lines}\n\n"
        f'Request: "{text}"\n\n'
        "Agent name:"
    )


def _configured_model() -> str:
    return os.environ.get(MODEL_ENV_VAR, DEFAULT_MODEL)


def local_classifier_available(*, model: str | None = None) -> bool:
    """True only if Ollama is reachable AND the specific model this
    classifier would use is actually pulled -- "reachable" alone isn't
    enough, a request for an unpulled model fails the same way an
    unreachable server does from this module's point of view.
    """
    if os.environ.get(DISABLE_ENV_VAR):
        return False
    if not is_reachable():
        return False
    wanted = model or _configured_model()
    return any(m.startswith(wanted) for m in list_models())


def classify(text: str, registry: dict[str, AgentSpec]) -> ClassificationResult:
    """Classify via the local model if available, else the keyword
    fallback. Never raises -- any failure of the local-model path is
    caught and silently downgraded to the keyword classifier, which itself
    cannot fail (it has its own default-agent fallback).
    """
    model = _configured_model()

    if not local_classifier_available(model=model):
        return keyword_classify(text)

    try:
        response = chat(model, _build_prompt(text, registry))
    except OllamaUnavailable:
        return keyword_classify(text)

    candidate = response.text.strip().strip(".").strip().lower()
    # Models sometimes wrap the answer ("agent: friday") despite the prompt;
    # take the last whitespace-free token as a cheap, safe extraction.
    candidate = candidate.split()[-1] if candidate.split() else candidate

    if candidate in registry:
        return ClassificationResult(
            agent=candidate,
            reason=f"local model '{model}' selected '{candidate}'",
            matched_keywords=[],
            scores={},
        )

    # Model answered with something that isn't a known agent key -- don't
    # guess at what it meant, fall back rather than route somewhere wrong.
    fallback = keyword_classify(text)
    return ClassificationResult(
        agent=fallback.agent,
        reason=(
            f"local model '{model}' returned unrecognized agent "
            f"{response.text.strip()!r}; fell back to keyword classifier "
            f"({fallback.reason})"
        ),
        matched_keywords=fallback.matched_keywords,
        scores=fallback.scores,
    )

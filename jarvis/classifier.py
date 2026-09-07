"""Intent classifier — v1 PLACEHOLDER.

This is a straightforward keyword/rule-based router, not a smart one. It
exists so Jarvis has *something* to route on before Phase 5 (local Ollama
models) lands. Once that infrastructure exists, this module should be
replaced by a local-model classifier — do not read more intelligence into
this than "counts keyword hits per agent, picks the max, falls back to a
default." See README.md "v1 placeholders" for the tracked follow-up.

The manual `--agent` override on the CLI always wins over this classifier
(see cli.py) — that is intentional and is the escape hatch for every case
this module gets wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# Keyword -> agent key. Word-boundary matched, case-insensitive. Order
# within a category doesn't matter; category-to-agent mapping does.
KEYWORDS: dict[str, list[str]] = {
    "alfred": [
        "leetcode", "hint", "learn", "study", "mastery", "interview",
        "mentor", "practice problem", "algorithm practice", "spaced repetition",
        "quiz", "flashcard",
    ],
    "ultron": [
        "binary", "firmware", "reverse engineer", "reverse-engineer",
        "cve", "exploit", "ghidra", "disassemble", "malware", "vulnerability",
        "pwn", "buffer overflow", "shellcode",
    ],
    "friday": [
        "note", "capture", "remember", "youtube", "article", "wiki",
        "knowledge base", "bookmark", "summarize this link", "daily log",
    ],
}

DEFAULT_AGENT = "friday"


@dataclass(frozen=True)
class ClassificationResult:
    agent: str
    reason: str
    matched_keywords: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)


def _compile_patterns() -> dict[str, list[re.Pattern]]:
    compiled: dict[str, list[re.Pattern]] = {}
    for agent, words in KEYWORDS.items():
        compiled[agent] = [
            re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
            for word in words
        ]
    return compiled


_PATTERNS = _compile_patterns()


def classify(text: str) -> ClassificationResult:
    """Rule-based intent classification (v1 placeholder, see module docstring).

    Counts keyword hits per agent; the agent with the most hits wins. Ties
    are broken by a fixed priority order (alfred, ultron, friday) since
    that's a deterministic, explainable tie-break rather than an arbitrary
    dict-iteration-order one. No hits at all -> DEFAULT_AGENT.
    """
    scores: dict[str, int] = {agent: 0 for agent in KEYWORDS}
    matched: dict[str, list[str]] = {agent: [] for agent in KEYWORDS}

    for agent, patterns in _PATTERNS.items():
        for word, pattern in zip(KEYWORDS[agent], patterns):
            if pattern.search(text):
                scores[agent] += 1
                matched[agent].append(word)

    priority = ["alfred", "ultron", "friday"]
    best_agent: Optional[str] = None
    best_score = 0
    for agent in priority:
        if scores[agent] > best_score:
            best_score = scores[agent]
            best_agent = agent

    if best_agent is None or best_score == 0:
        return ClassificationResult(
            agent=DEFAULT_AGENT,
            reason="no keyword matched any known category; defaulting to "
            f"'{DEFAULT_AGENT}' (v1 keyword classifier - use --agent to "
            "override)",
            matched_keywords=[],
            scores=scores,
        )

    return ClassificationResult(
        agent=best_agent,
        reason=f"keyword match: {matched[best_agent]} (v1 keyword classifier)",
        matched_keywords=matched[best_agent],
        scores=scores,
    )

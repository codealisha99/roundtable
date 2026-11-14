"""Cheap, deterministic text cues: who is being addressed, is it a question, is it decision-relevant."""

from __future__ import annotations

import re
from collections.abc import Iterable

_WORD = re.compile(r"[a-z0-9']+")
_QUESTION_WORDS = frozenset(
    {
        "who",
        "what",
        "when",
        "where",
        "why",
        "how",
        "which",
        "can",
        "could",
        "would",
        "should",
        "do",
        "does",
        "did",
        "is",
        "are",
        "any",
        "anyone",
    }
)
_RELEVANT = re.compile(
    r"\b(decid\w*|deadline|blocked|blocker|owner|action item|todo|risk|launch|ship|by (mon|tue|wed|thu|fri|sat|sun)\w*|eod|priority)\b"
)


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _contains_phrase(haystack: list[str], phrase: list[str]) -> bool:
    n = len(phrase)
    return any(haystack[i : i + n] == phrase for i in range(len(haystack) - n + 1))


def addresses_agent(text: str, aliases: Iterable[str]) -> bool:
    """True if any alias (possibly multi-word) appears as whole words, or as @alias."""
    tokens = words(text)
    lowered = text.lower()
    for alias in aliases:
        alias_words = words(alias)
        if not alias_words:
            continue
        if _contains_phrase(tokens, alias_words) or f"@{alias.lower()}" in lowered:
            return True
    return False


_GREETINGS = frozenset(
    {"hey", "hi", "hello", "thanks", "thank", "ok", "okay", "so", "yo"}
)


def addressed_human(text: str, humans: Iterable[str]) -> str | None:
    """Another participant the line opens with ("Dan, ..." / "Hey Dan ...") or @-mentions, else None."""
    tokens = words(text)
    opening = tokens[:2] if tokens and tokens[0] in _GREETINGS else tokens[:1]
    lowered = text.lower()
    for name in sorted(humans):
        first = name.lower().split()[0]
        if first in opening or f"@{first}" in lowered:
            return name
    return None


def mentioned_human(text: str, humans: Iterable[str]) -> str | None:
    """Any other participant named anywhere in the line (used for action-item owners)."""
    tokens = set(words(text))
    for name in sorted(humans):
        if name.lower().split()[0] in tokens:
            return name
    return None


def is_question(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    tokens = words(stripped)
    return bool(tokens) and tokens[0] in _QUESTION_WORDS


def is_decision_relevant(text: str) -> bool:
    return bool(_RELEVANT.search(text.lower()))


def mentions_you(text: str) -> bool:
    return bool(set(words(text)) & {"you", "your", "yours", "you're"})

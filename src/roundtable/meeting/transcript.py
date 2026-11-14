"""Speaker-attributed, time-ordered transcript helpers. Lines are immutable `Utterance`s."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from roundtable.floor.model import Utterance

_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "she",
        "so",
        "that",
        "the",
        "their",
        "them",
        "they",
        "this",
        "to",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
        "about",
        "say",
        "said",
        "tell",
    ]
)
_WORD = re.compile(r"[a-z0-9']+")


def fmt_time(ms: int) -> str:
    total = max(ms, 0) // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


def format_lines(lines: Iterable[Utterance]) -> str:
    return "\n".join(f"[{fmt_time(u.start_ms)}] {u.speaker}: {u.text}" for u in lines)


def keywords(text: str) -> frozenset[str]:
    return frozenset(
        w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1
    )


def retrieve(
    lines: Sequence[Utterance],
    question: str,
    speakers: Iterable[str] = (),
    k: int = 6,
) -> tuple[Utterance, ...]:
    """Keyword retrieval with a speaker boost: "what did Priya say about the deadline?"."""
    wanted = keywords(question)
    named = {s.lower() for s in speakers if s.lower() in question.lower()}
    scored: list[tuple[int, int, Utterance]] = []
    for index, line in enumerate(lines):
        overlap = len(wanted & keywords(line.text))
        boost = 2 if line.speaker.lower() in named else 0
        score = overlap + boost
        if score > 0 and (overlap > 0 or boost > 0):
            scored.append((score, index, line))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    best = sorted(scored[:k], key=lambda item: item[1])
    return tuple(line for _, _, line in best)

"""Meeting memory: decisions, action items with owners, and notes, built from final transcript lines.

Extraction is deterministic (cue phrases), so it works keyless and is testable. An LLM can
summarise on top of this, but the notes never depend on one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from roundtable.floor.addressing import is_decision_relevant, mentioned_human
from roundtable.floor.model import Utterance

Kind = Literal["decision", "action", "note"]

_DECISION = re.compile(
    r"\b(we decided|decided to|decision is|we'll go with|we will go with|we're going with|we are going with|agreed to|let's go with)\b"
)
_ACTION = re.compile(
    r"\b(i'll|i will|i can take|i'm going to|can you|could you|will you|please|we need to|someone needs to|action item)\b"
)
_I_OWNER = re.compile(r"\b(i'll|i will|i can take|i'm going to)\b")


@dataclass(frozen=True)
class Item:
    kind: Kind
    text: str
    speaker: str
    at_ms: int
    owner: str | None = None


def _owner_for(line: Utterance, humans: frozenset[str]) -> str | None:
    lowered = line.text.lower()
    if _I_OWNER.search(lowered):
        return line.speaker
    named = mentioned_human(line.text, humans - {line.speaker})
    if named is not None:
        return named
    return None


def classify(line: Utterance, humans: frozenset[str]) -> Item | None:
    """Return a memory item for a line, or None if it is just conversation."""
    lowered = line.text.lower()
    if _DECISION.search(lowered):
        return Item("decision", line.text, line.speaker, line.start_ms)
    if _ACTION.search(lowered):
        return Item(
            "action",
            line.text,
            line.speaker,
            line.start_ms,
            owner=_owner_for(line, humans),
        )
    if is_decision_relevant(line.text):
        return Item("note", line.text, line.speaker, line.start_ms)
    return None


class MeetingMemory:
    """Immutable: `observe` returns a new memory."""

    def __init__(self, items: tuple[Item, ...] = ()) -> None:
        self._items = items

    @property
    def items(self) -> tuple[Item, ...]:
        return self._items

    def observe(self, line: Utterance, humans: frozenset[str]) -> MeetingMemory:
        item = classify(line, humans)
        if item is None:
            return self
        return MeetingMemory(self._items + (item,))

    def of_kind(self, kind: Kind) -> tuple[Item, ...]:
        return tuple(item for item in self._items if item.kind == kind)

    def to_markdown(self, title: str = "Meeting notes") -> str:
        lines = [f"# {title}", ""]
        for heading, kind in (
            ("Decisions", "decision"),
            ("Action items", "action"),
            ("Notes", "note"),
        ):
            lines.append(f"## {heading}")
            items = self.of_kind(kind)
            if not items:
                lines.append("_None captured._")
            for item in items:
                lines.append(_render(item))
            lines.append("")
        return "\n".join(lines)


def _render(item: Item) -> str:
    if item.kind == "action":
        owner = item.owner or "unassigned"
        return f"- [ ] {owner}: {item.text} _(from {item.speaker})_"
    return f"- {item.text} _({item.speaker})_"

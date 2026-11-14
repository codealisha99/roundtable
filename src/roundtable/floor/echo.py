"""Echo guard: one sound heard on two human tracks becomes one transcript line. Pure, no LiveKit imports.

A participant's speakers leaking into their microphone put the same words on two tracks. Each
copy is transcribed, and without this guard the room sees the line twice and the agent may answer
it twice. Lines wait a short hold so the copy that started first can be chosen, then copies that
match an overlapping line from another speaker are dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from roundtable.floor.model import Utterance

HOLD_MS = 800  # a line waits this long after it ends, so a copy on another track can arrive first
SLACK_MS = 500  # two segments count as overlapping when they are within this of each other
TIE_MS = 300  # starts this close are "the same moment"; then the louder copy wins
MIN_WORDS = 3  # shorter lines ("yes, agreed") repeat too often to call them echo
SIMILAR = 0.85  # speech-to-text copies of one sound differ by a word or two
MEMORY_MS = 15_000  # admitted lines are kept this long, so a late copy is still matched
# ponytail: pairwise compare over a short memory; O(n) per line is fine at meeting sizes.


@dataclass(frozen=True)
class Heard:
    """Segments transcribed but not yet admitted, and recently admitted lines to match late copies against."""

    held: tuple[Utterance, ...] = ()
    admitted: tuple[Utterance, ...] = ()


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def is_echo_of(a: Utterance, b: Utterance) -> bool:
    """True when `a` and `b` are the same sound from two different speakers."""
    if a.speaker == b.speaker:
        return False
    if a.start_ms >= b.end_ms + SLACK_MS or b.start_ms >= a.end_ms + SLACK_MS:
        return False
    wa, wb = _words(a.text), _words(b.text)
    if min(len(wa), len(wb)) < MIN_WORDS:
        return False
    ratio = SequenceMatcher(None, " ".join(wa), " ".join(wb)).ratio()
    return ratio >= SIMILAR


def hear(state: Heard, line: Utterance) -> Heard:
    return Heard(held=(*state.held, line), admitted=state.admitted)


def release(state: Heard, now_ms: int) -> tuple[Heard, tuple[Utterance, ...]]:
    """Admit the held lines whose hold has passed. Returns the new state and the lines to use, in start order."""
    ready = sorted(
        (u for u in state.held if now_ms >= u.end_ms + HOLD_MS),
        key=lambda u: u.start_ms,
    )
    still_held = tuple(u for u in state.held if now_ms < u.end_ms + HOLD_MS)
    memory = tuple(u for u in state.admitted if now_ms - u.end_ms <= MEMORY_MS)
    kept: list[Utterance] = []
    for line in ready:
        if any(is_echo_of(line, earlier) for earlier in memory):
            continue  # a copy of a line already admitted
        twin = next((i for i, k in enumerate(kept) if is_echo_of(line, k)), None)
        if twin is None:
            kept.append(line)
        elif line.level > kept[twin].level and abs(line.start_ms - kept[twin].start_ms) <= TIE_MS:
            kept[twin] = line  # same moment, louder copy: attribute to the louder track
    return Heard(held=still_held, admitted=(*memory, *kept)), tuple(kept)

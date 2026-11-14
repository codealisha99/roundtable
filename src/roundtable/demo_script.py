"""Canned replies for the keyless path (ROUNDTABLE_LLM=scripted). Order matters: first match wins."""

from __future__ import annotations

from roundtable.llm import Brain, ScriptedBrain
from roundtable.meeting.transcript import keywords

FULL_STATUS = (
    "Here is the full status. The vendor API is done and the tests are green. "
    "The payments cutover is on Friday behind a feature flag. "
    "Dan owns the rollback runbook, due Thursday. Nothing is blocked."
)

DEMO_RULES: tuple[tuple[str, str], ...] = (
    ("floor gate", '{"speak": false, "text": ""}'),
    ("full status", FULL_STATUS),
    ("vendor API is done", "Dan said the vendor API is done and the tests are green."),
)

STANDUP_PREFIX = "You attend a standup on behalf of"
STANDUP_DEFER = "I do not have that in my notes. I will take that back to Sam."


# ponytail: lexical overlap, not semantics. Good enough to show grounding and deferral on a scripted
# meeting; a real deployment uses the LLM with the notes in the prompt.
MIN_COVERAGE = 0.5  # the note must cover at least half of the question's content words


class KeylessBrain:
    """Keyless brain for the demos. Standup proxy replies are read from the notes it is given (never
    invented): the note line that covers the question's content words, or a deferral if none does."""

    def __init__(self, fallback: Brain) -> None:
        self._fallback = fallback

    async def complete(self, system: str, user: str) -> str:
        if not system.startswith(STANDUP_PREFIX):
            return await self._fallback.complete(system, user)
        notes = system.split("Notes:\n", 1)[-1]
        question = user.rsplit('just said to you: "', 1)[-1].split('"', 1)[0]
        # Words of 4+ letters only: "out" in "roll out" must not match a note about "back on the 30th".
        wanted = {w for w in keywords(question) if len(w) >= 4}
        best_line, best_cover = "", 0.0
        for line in notes.splitlines():
            if not line.startswith("- "):
                continue
            cover = len(wanted & keywords(line)) / len(wanted) if wanted else 0.0
            if cover > best_cover:
                best_line, best_cover = line[2:].strip(), cover
        return best_line if best_cover >= MIN_COVERAGE else STANDUP_DEFER


def demo_brain() -> KeylessBrain:
    return KeylessBrain(
        ScriptedBrain(rules=DEMO_RULES, default="Noted, I will follow up on that.")
    )

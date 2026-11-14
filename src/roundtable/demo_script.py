"""Canned replies for the keyless path (ROUNDTABLE_LLM=scripted). Order matters: first match wins."""

from roundtable.llm import ScriptedBrain

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


def demo_brain() -> ScriptedBrain:
    return ScriptedBrain(rules=DEMO_RULES, default="Noted, I will follow up on that.")

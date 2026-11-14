"""Transcript retrieval and meeting memory over scripted lines."""

from roundtable.floor.model import Utterance
from roundtable.meeting.memory import MeetingMemory
from roundtable.meeting.transcript import fmt_time, format_lines, retrieve

HUMANS = frozenset({"Priya", "Dan"})


def line(speaker, text, at=0):
    return Utterance(speaker=speaker, text=text, start_ms=at, end_ms=at + 1000)


CALL = [
    line("Priya", "Let's start with the migration status.", 0),
    line("Dan", "Vendor API is done, tests are green.", 5000),
    line("Priya", "The deadline is Friday for the payments cutover.", 10000),
    line("Dan", "I'll write the rollback runbook by Thursday.", 15000),
    line("Priya", "We decided to ship behind a feature flag.", 20000),
    line("Dan", "Can you review the flag config, Priya?", 25000),
    line("Priya", "Yes, I can take that.", 30000),
]


def test_format_lines_is_speaker_attributed_and_timed():
    rendered = format_lines(CALL[:2]).splitlines()
    assert rendered[0] == "[00:00] Priya: Let's start with the migration status."
    assert rendered[1].startswith("[00:05] Dan:")


def test_fmt_time_rolls_minutes():
    assert fmt_time(65_000) == "01:05"


def test_retrieve_what_did_priya_say_about_the_deadline():
    hits = retrieve(CALL, "what did Priya say about the deadline?", speakers=HUMANS)
    assert hits, "expected at least one hit"
    deadline = [h for h in hits if "deadline" in h.text.lower()]
    assert deadline and deadline[0].speaker == "Priya"


def test_retrieve_returns_nothing_for_unrelated_question():
    assert retrieve(CALL, "what is the weather in Lisbon", speakers=HUMANS) == ()


def test_memory_captures_decision_action_with_owner_and_note():
    memory = MeetingMemory()
    for item in CALL:
        memory = memory.observe(item, HUMANS)
    decisions = memory.of_kind("decision")
    actions = memory.of_kind("action")
    notes = memory.of_kind("note")
    assert [d.text for d in decisions] == ["We decided to ship behind a feature flag."]
    assert [(a.owner, a.speaker) for a in actions] == [
        ("Dan", "Dan"),
        ("Priya", "Dan"),
        ("Priya", "Priya"),
    ]
    assert any("deadline" in n.text for n in notes)


def test_observe_is_immutable():
    empty = MeetingMemory()
    filled = empty.observe(CALL[3], HUMANS)
    assert empty.items == ()
    assert len(filled.items) == 1


def test_markdown_lists_owners_and_unassigned():
    memory = MeetingMemory().observe(line("Dan", "We need to pick a vendor."), HUMANS)
    markdown = memory.to_markdown("Sync")
    assert markdown.startswith("# Sync")
    assert "## Action items" in markdown
    assert "- [ ] unassigned: We need to pick a vendor." in markdown

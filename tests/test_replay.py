"""Logic behind the recorded demo: timeline placement, notes-grounded keyless replies, standup checks."""

import asyncio

from roundtable.demo_script import STANDUP_DEFER, demo_brain
from roundtable.e2e.checks import standup_checks
from roundtable.e2e.record import placed, timeline
from roundtable.e2e.script import STANDUP_NOTES, STANDUP_SCRIPT, STANDUP_UPDATE
from roundtable.floor.model import Utterance
from roundtable.persona import Persona
from roundtable.respond import build_reply_prompt, standup_system


def test_utterances_are_placed_on_the_agent_clock():
    # Agent process started at wall 100.0; the utterance starts 2.5 s into its clock,
    # but was only reported (STT finished) at 106.0. The recorder must use 102.5.
    event = {"t_ms": 6000, "wall": 106.0, "kind": "utterance", "start_ms": 2500}
    assert placed(event, t0=100.0) == 2.5


def test_timeline_drops_noise_and_sorts_by_time():
    events = [
        {
            "t_ms": 900,
            "wall": 101.0,
            "kind": "state",
            "label": "listening",
            "reason": "x",
        },
        {
            "t_ms": 500,
            "wall": 100.5,
            "kind": "decision",
            "action": "wait",
            "reason": "r",
        },
        {"t_ms": 300, "wall": 100.3, "kind": "vad_start", "speaker": "A", "at_ms": 100},
    ]
    rows = timeline(events, t0=100.0)
    assert [r["kind"] for r in rows] == ["vad_start", "decision"]


def test_keyless_standup_answers_from_notes_or_defers():
    persona = Persona.standup("Sam", STANDUP_UPDATE, STANDUP_NOTES)

    def reply(text: str) -> str:
        line = Utterance("Priya", text, 0, 1000)
        user = build_reply_prompt(
            summary="", transcript=(line,), question=line, items=(), humans=["Priya"]
        )
        return asyncio.run(demo_brain().complete(standup_system(persona), user))

    assert reply("Sam, is anything blocked?") == (
        "Blocked on the vendor sandbox credentials, asked Ops on Monday."
    )
    assert reply("Sam, when does the EU roll out ship?") == STANDUP_DEFER


def test_standup_checks_pass_on_the_expected_sequence():
    def utt(i, speaker, text):
        return {
            "t_ms": 0,
            "kind": "utterance",
            "speaker": speaker,
            "text": text,
            "start_ms": i * 10_000,
            "end_ms": i * 10_000 + 2000,
        }

    def turn(start, text):
        return [
            {"t_ms": start, "kind": "agent_speech_start", "text": text, "why": "x"},
            {
                "t_ms": start + 3000,
                "kind": "agent_speech_end",
                "heard": text,
                "played_ms": 0,
                "total_ms": 0,
                "interrupted": False,
            },
        ]

    lines = [line.text for line in STANDUP_SCRIPT]
    events = [
        utt(i, line_speaker, text)
        for i, (line_speaker, text) in enumerate(
            [(line.speaker, line.text) for line in STANDUP_SCRIPT]
        )
    ]
    events += turn(3000, STANDUP_UPDATE)
    events += turn(
        23000, "Blocked on the vendor sandbox credentials, asked Ops on Monday."
    )
    events += turn(33000, STANDUP_DEFER)
    assert lines[0].startswith("Quick standup")
    checks = standup_checks(
        events, STANDUP_SCRIPT, listener_frames=5, update=STANDUP_UPDATE
    )
    assert all(c.ok for c in checks), [c.name for c in checks if not c.ok]

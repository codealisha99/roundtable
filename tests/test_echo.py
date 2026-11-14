"""Echo guard: one acoustic event heard on two tracks must become one transcript line, from the earliest copy."""

from pathlib import Path

from roundtable.agent import Roundtable
from roundtable.events import EventLog
from roundtable.floor.echo import HOLD_MS, Heard, hear, is_echo_of, release
from roundtable.floor.model import Utterance
from roundtable.llm import ScriptedBrain
from roundtable.persona import Persona
from roundtable.speech.audio import pcm_rms

Q = "Roundtable, what did Dan say about the vendor API?"


def line(speaker: str, text: str, start: int, end: int, level: float = 0.1) -> Utterance:
    return Utterance(speaker, text, start, end, level)


def run(*lines: Utterance, at: int) -> list[Utterance]:
    state = Heard()
    for item in lines:
        state = hear(state, item)
    _, out = release(state, at)
    return list(out)


def test_same_words_on_two_tracks_become_one_line_from_the_first_speaker():
    out = run(
        line("Priya", Q, 36_000, 38_000),
        line("Jo", Q, 36_100, 38_100),
        at=40_000,
    )
    assert [u.speaker for u in out] == ["Priya"]


def test_copy_transcribed_first_still_loses_to_the_earlier_start():
    out = run(
        line("Jo", "We decided to ship behind a feature flag.", 36_200, 37_500),
        line("Priya", "We decided to ship behind a feature flag.", 36_000, 38_000),
        at=40_000,
    )
    assert [u.speaker for u in out] == ["Priya"]


def test_louder_copy_wins_when_both_start_at_the_same_moment():
    out = run(
        line("Priya", Q, 36_000, 38_000, level=0.05),
        line("Jo", Q, 36_150, 38_100, level=0.4),
        at=40_000,
    )
    assert [u.speaker for u in out] == ["Jo"]


def test_different_words_on_two_tracks_are_both_kept():
    out = run(
        line("Priya", Q, 36_000, 38_000),
        line("Jo", "Jo here, the vendor deadline is Friday.", 36_100, 38_000),
        at=40_000,
    )
    assert sorted(u.speaker for u in out) == ["Jo", "Priya"]


def test_slightly_different_speech_to_text_of_one_sound_is_still_one_line():
    out = run(
        line("Priya", "Jo here, the vendor deadline is Friday.", 36_000, 38_000),
        line("Jo", "Joe Here, the vendor deadline is Friday", 36_100, 38_000),
        at=40_000,
    )
    assert len(out) == 1


def test_one_speaker_repeating_themselves_is_not_echo():
    out = run(
        line("Dan", "We decided to ship behind a feature flag.", 36_000, 38_000),
        line("Dan", "We decided to ship behind a feature flag.", 36_100, 38_000),
        at=40_000,
    )
    assert len(out) == 2


def test_short_lines_on_two_tracks_are_not_called_echo():
    out = run(
        line("Priya", "Yes, agreed.", 36_000, 37_000),
        line("Jo", "Yes, agreed.", 36_100, 37_000),
        at=40_000,
    )
    assert len(out) == 2


def test_same_words_said_much_later_are_a_new_line():
    out = run(
        line("Priya", Q, 36_000, 38_000),
        line("Jo", Q, 90_000, 92_000),
        at=95_000,
    )
    assert len(out) == 2


def test_a_line_is_held_until_the_hold_has_passed_after_it_ends():
    state = hear(Heard(), line("Priya", Q, 36_000, 38_000))
    state, early = release(state, 38_000 + HOLD_MS - 1)
    state, late = release(state, 38_000 + HOLD_MS)
    assert early == ()
    assert [u.speaker for u in late] == ["Priya"]


def test_copy_arriving_after_the_original_was_admitted_is_dropped():
    state = hear(Heard(), line("Priya", Q, 36_000, 38_000))
    state, first = release(state, 38_000 + HOLD_MS)
    state = hear(state, line("Jo", Q, 36_100, 38_100))
    _, second = release(state, 38_100 + HOLD_MS)
    assert [u.speaker for u in first] == ["Priya"]
    assert second == ()


def test_is_echo_of_needs_both_overlap_and_similar_words():
    assert is_echo_of(line("Priya", Q, 0, 1_000), line("Jo", Q, 200, 1_200))
    assert not is_echo_of(line("Priya", Q, 0, 1_000), line("Priya", Q, 200, 1_200))
    assert not is_echo_of(line("Priya", Q, 0, 1_000), line("Jo", Q, 60_000, 61_000))


def test_pcm_rms_is_zero_for_silence_and_positive_for_speech():
    assert pcm_rms(b"\x00\x00" * 160) == 0.0
    assert pcm_rms(b"\xff\x7f" * 160) > 0.9


def test_agent_transcribes_a_shared_sound_once_and_from_the_first_speaker(tmp_path: Path):
    events = EventLog(tmp_path / "events.jsonl", echo=False)
    agent = Roundtable(
        persona=Persona.assistant(),
        brain=ScriptedBrain(),
        stt=object(),  # type: ignore[arg-type]
        tts=object(),  # type: ignore[arg-type]
        vad=object(),
        events=events,
        out_dir=tmp_path,
    )
    agent._on_speaker_event(line("Priya", Q, 36_000, 38_000))
    agent._on_speaker_event(line("Jo", Q, 36_100, 38_100))  # same sound on Jo's microphone
    agent._release_heard(now=40_000)
    events.close()
    heard = [e for e in _records(tmp_path / "events.jsonl") if e["kind"] == "utterance"]
    assert [(e["speaker"], e["text"]) for e in heard] == [("Priya", Q)]


def _records(path: Path) -> list[dict]:
    import json

    return [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]


def test_memory_items_are_logged_and_do_not_break_the_floor(tmp_path: Path):
    # A decision or action item used to raise inside the floor loop: emit() got two "kind" values.
    events = EventLog(tmp_path / "events.jsonl", echo=False)
    agent = Roundtable(
        persona=Persona.assistant(),
        brain=ScriptedBrain(),
        stt=object(),  # type: ignore[arg-type]
        tts=object(),  # type: ignore[arg-type]
        vad=object(),
        events=events,
        out_dir=tmp_path,
    )
    agent._on_speaker_event(line("Dan", "I will write the rollback runbook by Thursday.", 1_000, 3_000))
    agent._release_heard(now=5_000)
    events.close()
    memory = [e for e in _records(tmp_path / "events.jsonl") if e["kind"] == "memory"]
    assert len(memory) == 1
    assert memory[0]["owner"] == "Dan"

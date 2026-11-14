"""The scripted meeting: who says what, and what each line waits for. Lines are synthesised with macOS `say`."""

from __future__ import annotations

import hashlib
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 16000


@dataclass(frozen=True)
class Line:
    speaker: str
    voice: str
    text: str
    # What to wait for before speaking: an event kind (optionally with a substring match on
    # utterance text, or a repeat count), then `delay_s` more seconds.
    after_event: str | None = None
    match: str | None = None
    count: int = 1
    delay_s: float = 0.0


SCRIPT: tuple[Line, ...] = (
    Line("Priya", "Samantha", "Let's start with the migration status.", delay_s=1.0),
    Line(
        "Dan",
        "Daniel",
        "The vendor API is done and the tests are green.",
        after_event="utterance",
        match="migration",
        delay_s=1.5,
    ),
    Line(
        "Sam",
        "Alex",
        "Sounds good to me.",
        after_event="utterance",
        match="tests",
        delay_s=1.5,
    ),
    Line(
        "Priya",
        "Samantha",
        "Roundtable, what did Dan say about the vendor API?",
        after_event="utterance",
        match="sounds",
        delay_s=2.0,
    ),
    Line(
        "Dan",
        "Daniel",
        "We decided to ship behind a feature flag.",
        after_event="agent_speech_end",
        delay_s=1.0,
    ),
    Line(
        "Dan",
        "Daniel",
        "I will write the rollback runbook by Thursday.",
        after_event="utterance",
        match="feature",
        delay_s=1.0,
    ),
    Line(
        "Priya",
        "Samantha",
        "Roundtable, give me the full status.",
        after_event="utterance",
        match="runbook",
        delay_s=2.5,
    ),
    Line(
        "Dan",
        "Daniel",
        "Hold on, I need to say something.",
        after_event="agent_speech_start",
        count=2,
        delay_s=2.5,
    ),
)


# Standup proxy scenario: Sam is absent; the agent answers to "Sam" and speaks from prepared notes.
STANDUP_UPDATE = "Sam's update: the export fix is merged to main, and the parser PR is up for review."
STANDUP_NOTES = """# Sam: standup notes

- Export fix: merged to main on Tuesday.
- Parser PR: up for review, Priya is the reviewer.
- Blocked on the vendor sandbox credentials, asked Ops on Monday.
- Out on the 27th, back on the 30th.
"""

STANDUP_SCRIPT: tuple[Line, ...] = (
    Line("Priya", "Samantha", "Quick standup. Sam, you are up first.", delay_s=1.0),
    Line(
        "Dan",
        "Daniel",
        "Nice, that is good news for the release.",
        after_event="agent_speech_end",
        delay_s=1.0,
    ),
    Line(
        "Priya",
        "Samantha",
        "Sam, is anything blocked?",
        after_event="agent_speech_end",
        delay_s=2.0,
    ),
    Line(
        "Priya",
        "Samantha",
        "Sam, when does the EU rollout ship?",
        after_event="agent_speech_end",
        count=2,
        delay_s=2.5,
    ),
)


def clip_path(out_dir: Path, line: Line) -> Path:
    """Keyed by voice and text, so editing the script never replays a stale clip."""
    digest = hashlib.sha1(f"{line.voice}|{line.text}".encode()).hexdigest()[:10]
    return out_dir / f"{line.speaker.lower()}-{digest}.wav"


def synthesise(out_dir: Path, script: tuple[Line, ...] = SCRIPT) -> tuple[Path, ...]:
    """Write one 16 kHz mono WAV per scripted line (cached on re-runs)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for line in script:
        path = clip_path(out_dir, line)
        if not path.exists():
            subprocess.run(
                [
                    "say",
                    "-v",
                    line.voice,
                    "-o",
                    str(path),
                    "--data-format=LEI16@16000",
                    line.text,
                ],
                check=True,
            )
        paths.append(path)
    return tuple(paths)


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        if wav.getframerate() != SAMPLE_RATE or wav.getnchannels() != 1:
            raise ValueError(f"{path} must be 16 kHz mono")
        return wav.readframes(wav.getnframes())

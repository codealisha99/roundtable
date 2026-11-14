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


def clip_path(out_dir: Path, line: Line) -> Path:
    """Keyed by voice and text, so editing the script never replays a stale clip."""
    digest = hashlib.sha1(f"{line.voice}|{line.text}".encode()).hexdigest()[:10]
    return out_dir / f"{line.speaker.lower()}-{digest}.wav"


def synthesise(out_dir: Path) -> tuple[Path, ...]:
    """Write one 16 kHz mono WAV per scripted line (cached on re-runs)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for line in SCRIPT:
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

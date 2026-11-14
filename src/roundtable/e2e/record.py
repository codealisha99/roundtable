"""What the room carried during an e2e run: every simulated mic frame and the agent audio a listener
received, on one clock. Written as a 16 kHz mono WAV plus a timeline of agent events for the replay page."""

from __future__ import annotations

import json
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

from roundtable.e2e.script import SAMPLE_RATE

# Events worth replaying. "state" and per-frame VAD noise are left out on purpose.
REPLAYED = frozenset(
    {
        "participant",
        "utterance",
        "vad_start",
        "vad_end",
        "decision",
        "gate",
        "memory",
        "summary",
        "agent_speech_start",
        "agent_speech_end",
        "barge_in",
        "turn_dropped",
        "error",
    }
)


class Recorder:
    def __init__(self) -> None:
        self.t0 = time.time()
        self._chunks: list[tuple[int, np.ndarray]] = []

    def put(self, _track: str, wall: float, samples: np.ndarray) -> None:
        start = max(int((wall - self.t0) * SAMPLE_RATE), 0)
        self._chunks.append((start, np.array(samples, dtype=np.int16)))

    def mix(self) -> np.ndarray:
        end = max((start + len(s) for start, s in self._chunks), default=0)
        acc = np.zeros(end, dtype=np.int32)
        for start, samples in self._chunks:
            acc[start : start + len(samples)] += samples.astype(np.int32)
        return np.clip(acc, -32768, 32767).astype(np.int16)

    def write_wav(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(self.mix().tobytes())


def placed(event: dict[str, Any], t0: float) -> float:
    """Seconds from the start of capture. Utterances and VAD edges carry the time they happened on the
    agent's clock (`start_ms` / `at_ms`), so they are placed there, not at when STT or VAD reported them."""
    origin = (
        event["wall"] - event["t_ms"] / 1000
    )  # the agent's clock zero, the same for all events
    if event["kind"] == "utterance":
        return origin + event["start_ms"] / 1000 - t0
    if event["kind"] in ("vad_start", "vad_end"):
        return origin + event["at_ms"] / 1000 - t0
    return event["wall"] - t0


def timeline(events: list[dict[str, Any]], t0: float) -> list[dict[str, Any]]:
    rows = []
    for event in events:
        if event["kind"] not in REPLAYED:
            continue
        fields = {k: v for k, v in event.items() if k not in ("t_ms", "wall", "kind")}
        rows.append(
            {"at": round(placed(event, t0), 2), "kind": event["kind"], **fields}
        )
    return sorted(rows, key=lambda row: row["at"])


def write_recording(
    path: Path,
    *,
    scenario: str,
    title: str,
    agent: str,
    roster: list[dict[str, str]],
    events: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    recorder: Recorder,
) -> None:
    rows = timeline(events, recorder.t0)
    duration = max([row["at"] for row in rows] + [0.0])
    record = {
        "scenario": scenario,
        "title": title,
        "agent": agent,
        "roster": roster,
        "duration_s": round(len(recorder.mix()) / SAMPLE_RATE, 2),
        "events_until_s": round(duration, 2),
        "events": rows,
        "checks": checks,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")

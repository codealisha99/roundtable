"""Assertions over the agent's own event log, plus the human-readable report."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roundtable.e2e.script import Line
from roundtable.meeting.transcript import keywords

Record = dict[str, Any]
MATCH_RECALL = 0.5  # share of a line's content words the transcript must contain


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class Turn:
    start_ms: int
    end_ms: int | None
    text: str
    heard: str
    interrupted: bool


def load_events(path: Path) -> list[Record]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def utterances(events: list[Record]) -> list[Record]:
    return sorted(
        (e for e in events if e["kind"] == "utterance"), key=lambda e: e["start_ms"]
    )


def agent_turns(events: list[Record]) -> list[Turn]:
    turns: list[Turn] = []
    for event in events:
        if event["kind"] == "agent_speech_start":
            turns.append(Turn(event["t_ms"], None, event["text"], "", False))
        elif event["kind"] == "agent_speech_end" and turns and turns[-1].end_ms is None:
            last = turns.pop()
            turns.append(
                Turn(
                    last.start_ms,
                    event["t_ms"],
                    last.text,
                    event["heard"],
                    event["interrupted"],
                )
            )
    return turns  # an unfinished turn keeps end_ms=None and fails the checks


def find_line(events: list[Record], line: Line) -> Record | None:
    wanted = keywords(line.text)
    best: tuple[float, Record] | None = None
    for event in utterances(events):
        if event["speaker"] != line.speaker or not wanted:
            continue
        recall = len(wanted & keywords(event["text"])) / len(wanted)
        if recall >= MATCH_RECALL and (best is None or recall > best[0]):
            best = (recall, event)
    return best[1] if best else None


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.1f}s"


def analyse(
    events: list[Record], script: tuple[Line, ...], listener_frames: int
) -> list[Check]:
    checks: list[Check] = []
    found = {index: find_line(events, line) for index, line in enumerate(script)}
    for index, line in enumerate(script):
        hit = found[index]
        checks.append(
            Check(
                f"transcribed and attributed: {line.speaker} '{line.text[:40]}'",
                hit is not None,
                f"heard: {hit['text']!r}" if hit else "no matching utterance",
            )
        )
    checks.extend(_silence_checks(events, found))
    checks.extend(_reply_checks(events, found, script, listener_frames))
    return checks


def memory_checks(markdown: str) -> list[Check]:
    """The meeting notes written at shutdown must hold the decision and the owned action item."""
    return [
        Check(
            "notes: decision captured",
            "feature flag" in markdown and "## Decisions" in markdown,
            "decision line in ## Decisions",
        ),
        Check(
            "notes: action item with owner",
            "- [ ] Dan:" in markdown and "runbook" in markdown,
            "owner Dan for the runbook",
        ),
    ]


def _silence_checks(
    events: list[Record], found: dict[int, Record | None]
) -> list[Check]:
    question = found.get(3)
    decision = found.get(4)
    follow = found.get(5)
    starts = [t.start_ms for t in agent_turns(events)]
    checks: list[Check] = []
    if question is not None:
        early = [s for s in starts if s < question["end_ms"]]
        checks.append(
            Check(
                "silent before being addressed",
                not early,
                f"agent speech before the question: {[_seconds(s) for s in early] or 'none'}",
            )
        )
    if decision is not None and follow is not None:
        window = [s for s in starts if decision["end_ms"] <= s < follow["start_ms"]]
        gates = [e for e in events if e["kind"] == "gate" and not e["speak"]]
        checks.append(
            Check(
                "stayed silent on an unaddressed decision",
                not window and bool(gates),
                f"speech in window: {len(window)}, LLM gate stayed silent: {bool(gates)}",
            )
        )
    return checks


def _reply_checks(
    events: list[Record],
    found: dict[int, Record | None],
    script: tuple[Line, ...],
    listener_frames: int,
) -> list[Check]:
    question = found.get(3)
    full_status = found.get(5)
    turns = agent_turns(events)
    checks: list[Check] = []
    first = turns[0] if turns else None
    answered = (
        first is not None
        and question is not None
        and first.start_ms >= question["end_ms"]
    )
    replied_about_vendor = first is not None and "vendor" in first.text.lower()
    checks.append(
        Check(
            "responded when addressed by name",
            answered and replied_about_vendor,
            f"reply: {first.text!r}" if first else "no reply",
        )
    )
    checks.append(
        Check(
            "agent audio reached a listener",
            listener_frames > 0,
            f"{listener_frames} audio frames received by a participant",
        )
    )
    second = turns[1] if len(turns) > 1 else None
    if full_status is not None and second is not None:
        checks.append(
            Check(
                "second addressed turn answered",
                second.start_ms >= full_status["end_ms"],
                f"reply: {second.text[:60]!r}",
            )
        )
    barge = next((e for e in events if e["kind"] == "barge_in"), None)
    if barge is not None and second is not None and second.end_ms is not None:
        stopped_fast = second.interrupted and second.end_ms - barge["t_ms"] <= 1500
        shorter = len(second.heard.split()) < len(second.text.split())
        checks.append(
            Check(
                "barge-in stops speech at once",
                stopped_fast,
                f"barge-in at {_seconds(barge['t_ms'])}, speech ended {_seconds(second.end_ms)}",
            )
        )
        checks.append(
            Check(
                "truncated what was said to what was heard",
                shorter,
                f"said {len(second.text.split())} words, heard {len(second.heard.split())}",
            )
        )
    else:
        checks.append(
            Check("barge-in stops speech at once", False, "no barge-in observed")
        )
    return checks


def render(events: list[Record], checks: list[Check], script: tuple[Line, ...]) -> str:
    rows: list[tuple[int, str]] = [
        (u["start_ms"], f"{u['speaker']}: {u['text']}") for u in utterances(events)
    ]
    rows += [
        (
            t.start_ms,
            f"AGENT: {t.heard or t.text}" + ("  [cut off]" if t.interrupted else ""),
        )
        for t in agent_turns(events)
    ]
    lines = ["", "ATTRIBUTED TRANSCRIPT (merged, time-ordered)"]
    lines += [f"  [{_clock(ms)}] {text}" for ms, text in sorted(rows)]
    lines += ["", "AGENT DECISIONS"]
    lines += [
        f"  [{_clock(e['t_ms'])}] {e['action']:<8} {e['reason']}"
        for e in events
        if e["kind"] == "decision"
    ]
    lines += ["", "CHECKS"]
    lines += [f"  {'PASS' if c.ok else 'FAIL'}  {c.name}  ({c.detail})" for c in checks]
    passed = sum(c.ok for c in checks)
    lines += ["", f"{passed}/{len(checks)} checks passed"]
    return "\n".join(lines)


def _clock(ms: int) -> str:
    total = max(ms, 0) // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


def all_ok(checks: list[Check]) -> bool:
    return bool(checks) and all(c.ok for c in checks)

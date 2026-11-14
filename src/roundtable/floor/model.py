"""Immutable events and state for the floor manager. No LiveKit imports here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Action = Literal["wait", "speak", "stop", "consult"]
Label = Literal["listening", "wants_to_speak", "speaking", "thinking"]


@dataclass(frozen=True)
class Utterance:
    """A final, speaker-attributed transcript line."""

    speaker: str
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class Activity:
    """Per-speaker VAD edge: a human started or stopped talking."""

    speaker: str
    kind: Literal["start", "end"]
    at_ms: int


@dataclass(frozen=True)
class Joined:
    """A human is in the room (roster), even before they speak."""

    name: str


@dataclass(frozen=True)
class AgentStarted:
    """`answers_ms` is the end time of the line this turn answers; None means "everything heard so far"."""

    at_ms: int
    text: str
    answers_ms: int | None = None


@dataclass(frozen=True)
class AgentEnded:
    """`played_text` is what was actually audible before stop; it is what enters the transcript."""

    at_ms: int
    played_text: str
    interrupted: bool = False


@dataclass(frozen=True)
class Consulted:
    """The LLM gate was asked about the current silence; don't ask again for the same turn."""

    at_ms: int


@dataclass(frozen=True)
class Verdict:
    action: Action
    reason: str
    label: Label


@dataclass(frozen=True)
class FloorState:
    agent_name: str
    aliases: tuple[str, ...]
    humans: frozenset[str] = frozenset()
    speaking: tuple[tuple[str, int], ...] = ()  # (human, since_ms) with VAD open
    recent: tuple[Utterance, ...] = ()
    agent_speaking: bool = False
    agent_started_ms: int | None = None
    last_human_end_ms: int = 0
    last_agent_start_ms: int | None = None
    last_agent_end_ms: int | None = None
    answered_upto_ms: int = -1  # lines ending at or before this were answered by a turn
    overlap_open: bool = False
    overlap_until_ms: int = 0
    consulted_for_ms: int | None = None
    last_consult_ms: int | None = None

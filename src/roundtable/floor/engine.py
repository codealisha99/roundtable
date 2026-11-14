"""Floor manager: pure reducer (`apply`) plus a heuristic gate (`evaluate`).

`evaluate` returns one of: wait / speak / stop (barge-in) / consult (ask the LLM gate).
The runtime re-checks with `approved=True` after an LLM "yes", so a turn never starts over
someone who began talking while the model was thinking.
"""

from __future__ import annotations

from dataclasses import replace

from roundtable.floor.addressing import (
    addressed_human,
    addresses_agent,
    is_decision_relevant,
    is_question,
    mentions_you,
)
from roundtable.floor.model import (
    Activity,
    AgentEnded,
    AgentStarted,
    Consulted,
    FloorState,
    Joined,
    Utterance,
    Verdict,
)

GAP_MS = 700  # silence before answering someone who addressed me
QUESTION_SILENCE_MS = 1500  # silence after an unanswered group question
FOLLOWUP_WINDOW_MS = (
    20_000  # how long after my turn a reply still counts as a follow-up
)
BARGE_IN_MS = 250  # human speech this long over me counts as talking over me
OVERLAP_COOLDOWN_MS = 1_200  # no new turn this long after an overlap clears
MID_EXCHANGE_WINDOW_MS = (
    30_000  # three alternating human turns inside this = a back-and-forth
)
CONSULT_SILENCE_MS = 2_000  # silence before asking the LLM gate about a statement
CONSULT_COOLDOWN_MS = (
    20_000  # min spacing between LLM gate calls (keeps the model cost bounded)
)
MAX_RECENT = 40


def initial_state(agent_name: str, aliases: tuple[str, ...] | list[str]) -> FloorState:
    return FloorState(agent_name=agent_name, aliases=tuple(aliases))


def apply(state: FloorState, event: object) -> FloorState:
    match event:
        case Joined():
            return _join(state, event.name)
        case Utterance():
            return _on_utterance(state, event)
        case Activity():
            return _on_activity(state, event)
        case AgentStarted():
            return replace(
                state,
                agent_speaking=True,
                agent_started_ms=event.at_ms,
                last_agent_start_ms=event.at_ms,
            )
        case AgentEnded():
            return _on_agent_ended(state, event)
        case Consulted():
            return replace(
                state,
                consulted_for_ms=state.last_human_end_ms,
                last_consult_ms=event.at_ms,
            )
        case _:
            raise TypeError(f"unknown floor event: {event!r}")


def evaluate(state: FloorState, now_ms: int, approved: bool = False) -> Verdict:
    if state.agent_speaking:
        return _while_speaking(state, now_ms)
    if state.speaking:
        names = ", ".join(sorted(name for name, _ in state.speaking))
        return Verdict("wait", f"{names} is speaking", "listening")
    if now_ms < state.overlap_until_ms:
        return Verdict("wait", "cooling down after an overlap", "listening")
    if approved:
        return Verdict("speak", "LLM gate said to speak", "wants_to_speak")
    return _plan(state, now_ms)


# --- reducer helpers -------------------------------------------------------------


def _join(state: FloorState, name: str) -> FloorState:
    if name == state.agent_name or name in state.humans:
        return state
    return replace(state, humans=state.humans | {name})


def _on_utterance(state: FloorState, event: Utterance) -> FloorState:
    if event.speaker == state.agent_name:
        return state  # agent lines enter the transcript via AgentEnded, with what was played
    joined = _join(state, event.speaker)
    return replace(
        joined,
        recent=_insert_ordered(joined.recent, event),
        last_human_end_ms=max(joined.last_human_end_ms, event.end_ms),
    )


def _insert_ordered(
    recent: tuple[Utterance, ...], line: Utterance
) -> tuple[Utterance, ...]:
    """STT runs concurrently per speaker, so lines can arrive out of order; keep the transcript time-ordered."""
    merged = sorted(recent + (line,), key=lambda u: u.start_ms)
    return tuple(merged[-MAX_RECENT:])


def _on_activity(state: FloorState, event: Activity) -> FloorState:
    if event.speaker == state.agent_name:
        return state
    joined = _join(state, event.speaker)
    others = [name for name, _ in joined.speaking if name != event.speaker]
    if event.kind == "start":
        overlapped = joined.agent_speaking or bool(others)
        speaking = _without(joined.speaking, event.speaker) + (
            (event.speaker, event.at_ms),
        )
        return replace(
            joined, speaking=speaking, overlap_open=joined.overlap_open or overlapped
        )
    speaking = _without(joined.speaking, event.speaker)
    settled = replace(
        joined,
        speaking=speaking,
        last_human_end_ms=max(joined.last_human_end_ms, event.at_ms),
    )
    return _settle(settled, event.at_ms)


def _on_agent_ended(state: FloorState, event: AgentEnded) -> FloorState:
    recent = state.recent
    if event.played_text.strip():
        start = (
            state.agent_started_ms
            if state.agent_started_ms is not None
            else event.at_ms
        )
        line = Utterance(state.agent_name, event.played_text, start, event.at_ms)
        recent = _insert_ordered(recent, line)
    ended = replace(
        state,
        agent_speaking=False,
        last_agent_end_ms=event.at_ms,
        recent=recent,
    )
    return _settle(ended, event.at_ms)


def _settle(state: FloorState, at_ms: int) -> FloorState:
    """Once the floor is quiet again after an overlap, start the cooldown clock."""
    if state.overlap_open and not state.speaking and not state.agent_speaking:
        return replace(
            state, overlap_open=False, overlap_until_ms=at_ms + OVERLAP_COOLDOWN_MS
        )
    return state


def _without(
    speaking: tuple[tuple[str, int], ...], name: str
) -> tuple[tuple[str, int], ...]:
    return tuple(pair for pair in speaking if pair[0] != name)


# --- gate ------------------------------------------------------------------------


def _while_speaking(state: FloorState, now_ms: int) -> Verdict:
    for name, since in state.speaking:
        if now_ms - since >= BARGE_IN_MS:
            return Verdict("stop", f"{name} talked over me, stopping", "speaking")
    return Verdict("wait", "I am speaking", "speaking")


def last_human_line(state: FloorState) -> Utterance | None:
    for line in reversed(state.recent):
        if line.speaker != state.agent_name:
            return line
    return None


def _mid_exchange(state: FloorState) -> tuple[str, str] | None:
    humans = [line for line in state.recent if line.speaker != state.agent_name]
    if len(humans) < 3:
        return None
    first, middle, last = humans[-3:]
    alternating = first.speaker == last.speaker and first.speaker != middle.speaker
    if alternating and last.end_ms - first.start_ms <= MID_EXCHANGE_WINDOW_MS:
        return (first.speaker, middle.speaker)
    return None


def _is_follow_up(state: FloorState, line: Utterance, now_ms: int) -> bool:
    if state.last_agent_end_ms is None or line.start_ms < state.last_agent_end_ms:
        return False
    if now_ms - state.last_agent_end_ms > FOLLOWUP_WINDOW_MS:
        return False
    return is_question(line.text) or mentions_you(line.text)


def _plan(state: FloorState, now_ms: int) -> Verdict:
    line = last_human_line(state)
    if line is None:
        return Verdict("wait", "nothing said yet", "listening")
    gap = now_ms - state.last_human_end_ms
    answered = (
        state.last_agent_start_ms is not None
        and state.last_agent_start_ms >= line.end_ms
    )

    if addresses_agent(line.text, state.aliases) and not answered:
        if gap < GAP_MS:
            return Verdict(
                "wait", "addressed to me, waiting for a gap", "wants_to_speak"
            )
        return Verdict("speak", "addressed by name", "wants_to_speak")

    target = addressed_human(line.text, state.humans - {line.speaker})
    if target is not None:
        return Verdict("wait", f"addressed to {target}, not me", "listening")

    pair = _mid_exchange(state)
    if pair is not None:
        return Verdict("wait", f"{pair[0]} and {pair[1]} are mid-exchange", "listening")

    if _is_follow_up(state, line, now_ms) and not answered:
        if gap < GAP_MS:
            return Verdict("wait", "follow-up, waiting for a gap", "wants_to_speak")
        return Verdict("speak", "follow-up to what I just said", "wants_to_speak")

    if is_question(line.text) and not answered:
        if gap < QUESTION_SILENCE_MS:
            return Verdict(
                "wait", "group question, waiting for silence", "wants_to_speak"
            )
        return Verdict(
            "speak", "group question unanswered after 1.5s", "wants_to_speak"
        )

    return _consider_consult(state, line, now_ms, gap)


def _consider_consult(
    state: FloorState, line: Utterance, now_ms: int, gap: int
) -> Verdict:
    quiet = Verdict("wait", "nothing addressed to me", "listening")
    if not is_decision_relevant(line.text):
        return quiet
    if gap < CONSULT_SILENCE_MS or state.consulted_for_ms == state.last_human_end_ms:
        return quiet
    if _recent(state.last_consult_ms, now_ms):
        return quiet
    return Verdict("consult", "possible contribution, asking the LLM gate", "thinking")


def _recent(at_ms: int | None, now_ms: int) -> bool:
    return at_ms is not None and now_ms - at_ms < CONSULT_COOLDOWN_MS

"""Prompt construction and reply generation. Prompt builders are pure; only `reply`/`summarise` call the brain."""

from __future__ import annotations

from collections.abc import Sequence

from roundtable.floor.model import Utterance
from roundtable.llm import Brain
from roundtable.meeting.memory import Item
from roundtable.meeting.transcript import format_lines, retrieve
from roundtable.persona import Persona

RECENT_LINES = 12
SUMMARY_EVERY = 8  # new final lines between rolling-summary refreshes

GATE_SYSTEM = (
    "You are the floor gate for Roundtable, an AI attendee in a live group call. Someone just paused "
    "after a remark that was NOT addressed to you. Speak only if one short sentence would clearly help "
    "right now (an unowned action item, a decision that needs recording, a deadline nobody confirmed). "
    'Otherwise stay silent. Reply with JSON only: {"speak": true|false, "text": "<one spoken sentence or empty>"}'
)

REPLY_SYSTEM = (
    "You are Roundtable, an AI participant in a live group call. Your words are spoken aloud: reply in "
    "one to three short plain sentences, no markdown, no lists. Name the person you are answering. Use "
    "only the meeting context given. If the answer is not in it, say you do not know yet. Never claim "
    "actions outside this call."
)

SUMMARY_SYSTEM = "You keep a running summary of a meeting. Keep decisions, owners, deadlines and open questions. Under 120 words, plain text."


def standup_system(persona: Persona) -> str:
    who = persona.absent_name or "the absent colleague"
    return (
        f"You attend a standup on behalf of {who}, who is not here. Answer follow-up questions only from "
        f"the notes below. If the answer is not in the notes, say you will take it back to {who}. Keep it "
        f"to one or two short spoken sentences, no markdown.\n\nNotes:\n{persona.notes or '(none)'}"
    )


def _open_items(items: Sequence[Item]) -> str:
    if not items:
        return "(none yet)"
    lines = []
    for item in items:
        label = (
            f"action, owner {item.owner or 'unassigned'}"
            if item.kind == "action"
            else item.kind
        )
        lines.append(f"- {label}: {item.text}")
    return "\n".join(lines)


def build_reply_prompt(
    *,
    summary: str,
    transcript: Sequence[Utterance],
    question: Utterance,
    items: Sequence[Item],
    humans: Sequence[str],
) -> str:
    retrieved = retrieve(transcript, question.text, speakers=humans)
    return (
        f"Meeting summary so far:\n{summary or '(call just started)'}\n\n"
        f"Relevant earlier lines:\n{format_lines(retrieved) or '(none)'}\n\n"
        f"Recent lines:\n{format_lines(transcript[-RECENT_LINES:]) or '(none)'}\n\n"
        f"Decisions and action items so far:\n{_open_items(items)}\n\n"
        f'{question.speaker} just said to you: "{question.text}"\nReply to that.'
    )


async def reply(
    brain: Brain,
    persona: Persona,
    *,
    question: Utterance,
    transcript: Sequence[Utterance],
    items: Sequence[Item],
    humans: Sequence[str],
    summary: str,
    update_delivered: bool,
) -> str:
    """Standup proxy delivers the prepared update once, then answers from notes. Assistant mode always uses the brain."""
    if persona.mode == "standup" and not update_delivered:
        if persona.prepared_update:
            return persona.prepared_update
        return f"I do not have an update from {persona.addressed_as} yet. I will take that back to them."
    system = standup_system(persona) if persona.mode == "standup" else REPLY_SYSTEM
    user = build_reply_prompt(
        summary=summary,
        transcript=transcript,
        question=question,
        items=items,
        humans=humans,
    )
    return (await brain.complete(system, user)).strip()


def build_summary_prompt(previous: str, new_lines: Sequence[Utterance]) -> str:
    return f"Previous summary:\n{previous or '(none)'}\n\nNew lines:\n{format_lines(new_lines)}\n\nUpdate the summary."


async def summarise(brain: Brain, previous: str, new_lines: Sequence[Utterance]) -> str:
    return (
        await brain.complete(SUMMARY_SYSTEM, build_summary_prompt(previous, new_lines))
    ).strip()


def build_gate_prompt(transcript: Sequence[Utterance], items: Sequence[Item]) -> str:
    return f"Recent lines:\n{format_lines(transcript[-RECENT_LINES:])}\n\nOpen items:\n{_open_items(items)}\n\nShould you speak now?"

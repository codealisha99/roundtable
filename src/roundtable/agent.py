"""The agent as a LiveKit participant: wires per-speaker speech into the floor manager and speaks its turns."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from livekit import rtc

from roundtable import respond
from roundtable.events import EventLog
from roundtable.floor.engine import addressed_line, apply, evaluate, initial_state
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
from roundtable.llm import Brain, parse_gate
from roundtable.meeting.memory import MeetingMemory
from roundtable.persona import Persona
from roundtable.speech.playback import play
from roundtable.speech.speaker import pump_speaker
from roundtable.speech.stt import STT
from roundtable.speech.tts import TTS

log = logging.getLogger("roundtable.agent")
OUT_RATE = 48000
FLOOR_TICK_S = (
    0.1  # how often the floor is re-evaluated; barge-in latency is bounded by this
)
TRACK_NAME = "roundtable-voice"
TOPIC = "roundtable"


class Roundtable:
    def __init__(
        self,
        *,
        persona: Persona,
        brain: Brain,
        stt: STT,
        tts: TTS,
        vad: object,
        events: EventLog,
        out_dir: Path,
    ) -> None:
        self._persona = persona
        self._brain = brain
        self._stt = stt
        self._tts = tts
        self._vad = vad
        self._events = events
        self._out_dir = out_dir
        self.state: FloorState = initial_state(persona.name, persona.aliases)
        self._memory = MeetingMemory()
        self._summary = ""
        self._pending: list[Utterance] = []
        self._busy = False
        self._update_delivered = False
        self._cancel: asyncio.Event | None = None
        self._last_report: tuple[str, str] | None = None
        self._last_label: tuple[str, str] | None = None
        self._source: rtc.AudioSource | None = None
        self._room: rtc.Room | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._closed = asyncio.Event()

    # --- clock and state ------------------------------------------------------

    def now_ms(self) -> int:
        # One clock for the floor and the event log (the log's t_ms), so recordings can align them.
        return self._events.now_ms()

    def _apply(self, event: object) -> None:
        self.state = apply(self.state, event)

    # --- lifecycle ------------------------------------------------------------

    async def run(self, url: str, token: str) -> None:
        room = rtc.Room()
        self._room = room
        room.on("track_subscribed", self._on_track)
        room.on("participant_connected", lambda participant: self._on_join(participant))
        room.on("disconnected", lambda *_: self._closed.set())
        await room.connect(url, token)
        self._source = rtc.AudioSource(OUT_RATE, 1)
        track = rtc.LocalAudioTrack.create_audio_track(TRACK_NAME, self._source)
        await room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        for participant in room.remote_participants.values():
            self._on_join(participant)
        self._events.emit(
            "joined", room=room.name, identity=room.local_participant.identity
        )
        floor = asyncio.create_task(self._floor_loop())
        try:
            await self._closed.wait()
        finally:
            floor.cancel()
            await self._finish()

    def request_stop(self) -> None:
        self._closed.set()

    async def _finish(self) -> None:
        markdown = self._memory.to_markdown(f"{self._persona.name}: meeting notes")
        if self._summary:
            markdown += f"\n## Summary\n\n{self._summary}\n"
        self._out_dir.mkdir(parents=True, exist_ok=True)
        (self._out_dir / "meeting.md").write_text(markdown, encoding="utf-8")
        self._events.emit("finished", notes=str(self._out_dir / "meeting.md"))
        for task in list(self._tasks):
            task.cancel()
        self._events.close()

    # --- participants and speakers -------------------------------------------

    def _on_join(self, participant: rtc.RemoteParticipant) -> None:
        name = participant.name or participant.identity
        self._apply(Joined(name))
        self._events.emit("participant", name=name, identity=participant.identity)

    def _on_track(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        name = participant.name or participant.identity
        self._apply(Joined(name))
        self._spawn(
            pump_speaker(
                name, track, self._vad, self._stt, self._on_speaker_event, self.now_ms
            ),
        )

    def _on_speaker_event(self, event: object) -> None:
        if isinstance(event, Utterance):
            self._on_utterance(event)
        elif isinstance(event, Activity):
            self._apply(event)
            self._events.emit(
                f"vad_{event.kind}", speaker=event.speaker, at_ms=event.at_ms
            )

    def _on_utterance(self, line: Utterance) -> None:
        self._apply(line)
        humans = frozenset(self.state.humans)
        before = len(self._memory.items)
        self._memory = self._memory.observe(line, humans)
        self._events.emit(
            "utterance",
            speaker=line.speaker,
            text=line.text,
            start_ms=line.start_ms,
            end_ms=line.end_ms,
        )
        if len(self._memory.items) > before:
            item = self._memory.items[-1]
            self._events.emit(
                "memory", kind=item.kind, owner=item.owner, text=item.text
            )
        self._publish(
            {
                "kind": "caption",
                "speaker": line.speaker,
                "text": line.text,
                "start_ms": line.start_ms,
            }
        )
        self._pending.append(line)
        if len(self._pending) >= respond.SUMMARY_EVERY:
            batch = tuple(self._pending)
            self._pending = []
            self._spawn(self._refresh_summary(batch))

    async def _refresh_summary(self, batch: tuple[Utterance, ...]) -> None:
        self._summary = await respond.summarise(self._brain, self._summary, batch)
        self._events.emit("summary", text=self._summary)

    # --- floor loop -----------------------------------------------------------

    async def _floor_loop(self) -> None:
        while True:
            await asyncio.sleep(FLOOR_TICK_S)
            now = self.now_ms()
            if self.state.agent_speaking:
                self._check_barge_in(now)
                continue
            if self._busy:
                continue
            verdict = evaluate(self.state, now)
            self._report(verdict)
            if verdict.action == "speak":
                self._spawn_turn(self._reply_turn(verdict.reason), verdict.reason)
            elif verdict.action == "consult":
                self._apply(Consulted(at_ms=now))
                self._spawn_turn(self._consult_turn(), verdict.reason)

    def _check_barge_in(self, now: int) -> None:
        verdict = evaluate(self.state, now)
        if (
            verdict.action == "stop"
            and self._cancel is not None
            and not self._cancel.is_set()
        ):
            self._events.emit("barge_in", reason=verdict.reason, at_ms=now)
            self._report(verdict)
            self._cancel.set()

    def _spawn_turn(self, coro: Coroutine[Any, Any, None], why: str) -> None:
        self._busy = True

        async def guarded() -> None:
            try:
                await coro
            except Exception:  # a failed turn must not kill the floor loop
                log.exception("turn failed (%s)", why)
                self._events.emit("error", where="turn", why=why)
            finally:
                self._busy = False

        self._spawn(guarded())

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --- turns ----------------------------------------------------------------

    async def _reply_turn(self, why: str) -> None:
        question = addressed_line(self.state)
        if question is None:
            return
        self._publish_state("thinking", why)
        text = await respond.reply(
            self._brain,
            self._persona,
            question=question,
            transcript=self.state.recent,
            items=self._memory.items,
            humans=sorted(self.state.humans),
            summary=self._summary,
            update_delivered=self._update_delivered,
        )
        spoken = bool(text) and await self._say(text, why, answers_ms=question.end_ms)
        if spoken and self._persona.mode == "standup":
            self._update_delivered = True

    async def _consult_turn(self) -> None:
        anchor = self.state.last_human_end_ms  # the statement being weighed, not later talk
        self._publish_state("thinking", "asking the LLM gate")
        raw = await self._brain.complete(
            respond.GATE_SYSTEM,
            respond.build_gate_prompt(self.state.recent, self._memory.items),
        )
        speak, text = parse_gate(raw)
        self._events.emit("gate", speak=speak, text=text)
        if speak and text:
            await self._say(text, "LLM gate chose to speak", answers_ms=anchor)
        else:
            self._publish_state("listening", "LLM gate stayed silent")

    async def _say(self, text: str, why: str, *, answers_ms: int | None = None) -> bool:
        now = self.now_ms()
        check = evaluate(self.state, now, approved=True)
        if check.action != "speak":
            self._events.emit("turn_dropped", text=text, reason=check.reason)
            self._publish_state("listening", check.reason)
            return False
        cancel = asyncio.Event()
        self._cancel = cancel
        self._apply(AgentStarted(at_ms=now, text=text, answers_ms=answers_ms))
        self._publish_state("speaking", why)
        self._events.emit("agent_speech_start", text=text, why=why)
        self._publish({"kind": "agent_caption", "text": text})
        assert self._source is not None
        played_ms, total_ms, heard = await play(self._source, self._tts, text, cancel)
        interrupted = cancel.is_set()
        self._cancel = None
        self._apply(
            AgentEnded(at_ms=self.now_ms(), played_text=heard, interrupted=interrupted)
        )
        self._events.emit(
            "agent_speech_end",
            heard=heard,
            played_ms=played_ms,
            total_ms=total_ms,
            interrupted=interrupted,
        )
        self._publish_state(
            "listening", "stopped speaking" if interrupted else "finished speaking"
        )
        return True

    # --- reporting ------------------------------------------------------------

    def _report(self, verdict: Verdict) -> None:
        key = (verdict.action, verdict.reason)
        if key == self._last_report:
            return
        self._last_report = key
        self._events.emit(
            "decision",
            action=verdict.action,
            reason=verdict.reason,
            label=verdict.label,
        )
        if verdict.action in ("wait", "speak"):
            self._publish_state(verdict.label, verdict.reason)

    def _publish_state(self, label: str, reason: str) -> None:
        key = (label, reason)
        if key == self._last_label:
            return
        self._last_label = key
        self._events.emit("state", label=label, reason=reason)
        self._publish({"kind": "state", "label": label, "reason": reason})

    def _publish(self, payload: dict[str, Any]) -> None:
        room = self._room
        if room is None:
            return
        data = json.dumps(payload)
        self._spawn(
            room.local_participant.publish_data(data, reliable=True, topic=TOPIC)
        )

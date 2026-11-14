"""`roundtable demo`: LiveKit in Docker, the agent as a subprocess, three simulated participants, then assertions."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from roundtable.config import Settings
from roundtable.e2e import livekit
from roundtable.e2e.checks import all_ok, analyse, load_events, memory_checks, render
from roundtable.e2e.script import SCRIPT, Line, read_pcm, synthesise
from roundtable.e2e.sims import Participant

log = logging.getLogger("roundtable.demo")
OUT = Path("out/e2e")
ROOM = "roundtable-demo"
WAIT_TIMEOUT_S = 60.0
PARTICIPANTS = ("Priya", "Dan", "Sam")
ENGINE_ENV = {
    # The keyless demo must never reach a cloud provider, even if keys are exported in the shell.
    "ROUNDTABLE_LLM": "scripted",
    "ROUNDTABLE_STT": "local",
    "ROUNDTABLE_TTS": "piper",
}


class EventWatch:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def until(self, predicate: Any, timeout_s: float = WAIT_TIMEOUT_S) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            if predicate(load_events(self._path)):
                return True
            await asyncio.sleep(0.2)
        return False


def _ready(line: Line) -> Any:
    def predicate(records: list[dict[str, Any]]) -> bool:
        hits = [
            r
            for r in records
            if r["kind"] == line.after_event
            and (line.match is None or line.match in str(r.get("text", "")).lower())
        ]
        return len(hits) >= line.count

    return predicate


async def _speak_script(
    part: Participant,
    lines: list[tuple[int, Line]],
    watch: EventWatch,
    clips: tuple[Path, ...],
) -> None:
    for index, line in lines:
        if line.after_event is not None and not await watch.until(_ready(line)):
            log.warning(
                "timed out waiting for %s before %r", line.after_event, line.text
            )
        await asyncio.sleep(line.delay_s)
        seconds = part.say(read_pcm(clips[index]))
        log.info("[%s] speaking: %s", part.name, line.text)
        await asyncio.sleep(seconds)


def _agent_env(settings: Settings) -> dict[str, str]:
    env = {**os.environ, **ENGINE_ENV}
    env.update(
        LIVEKIT_URL=settings.livekit_url,
        LIVEKIT_API_KEY=settings.api_key,
        LIVEKIT_API_SECRET=settings.api_secret,
        ROUNDTABLE_ROOM=settings.room,
        ROUNDTABLE_OUT_DIR=str(settings.out_dir),
        ROUNDTABLE_AGENT_NAME="Roundtable",
    )
    return env


async def _stop_agent(agent: subprocess.Popen[bytes]) -> None:
    if agent.poll() is not None:
        return
    agent.send_signal(signal.SIGINT)
    try:
        await asyncio.wait_for(asyncio.to_thread(agent.wait), 30)
    except TimeoutError:
        agent.kill()


async def run_demo() -> int:
    settings = replace(Settings.from_env(), room=ROOM, out_dir=OUT)
    clips = synthesise(OUT / "clips")
    events_path = OUT / "events.jsonl"
    events_path.unlink(missing_ok=True)
    watch = EventWatch(events_path)
    agent: subprocess.Popen[bytes] | None = None
    participants: list[Participant] = []
    try:
        livekit.start()
        await livekit.wait_ready()
        log.info("LiveKit is up on %s", settings.livekit_url)
        with (OUT / "agent.log").open("w", encoding="utf-8") as agent_log:
            agent = await asyncio.to_thread(
                subprocess.Popen,
                [sys.executable, "-m", "roundtable", "agent"],
                env=_agent_env(settings),
                stdout=agent_log,
                stderr=subprocess.STDOUT,
            )
            if not await watch.until(lambda rs: any(r["kind"] == "joined" for r in rs)):
                raise RuntimeError("agent did not join the room; see out/e2e/agent.log")
            participants = [
                Participant(settings, name, "Roundtable") for name in PARTICIPANTS
            ]
            for part in participants:
                await part.join()
            await _run_meeting(participants, watch, clips)
            await _stop_agent(agent)
    finally:
        for part in participants:
            await part.leave()
        if agent is not None:
            await _stop_agent(agent)
        livekit.stop()
    return _report(events_path, participants)


async def _run_meeting(
    participants: list[Participant], watch: EventWatch, clips: tuple[Path, ...]
) -> None:
    by_speaker = {p.name: p for p in participants}
    plans: dict[str, list[tuple[int, Line]]] = {name: [] for name in PARTICIPANTS}
    for index, line in enumerate(SCRIPT):
        plans[line.speaker].append((index, line))
    await asyncio.gather(
        *(
            _speak_script(by_speaker[name], plans[name], watch, clips)
            for name in PARTICIPANTS
        )
    )
    await asyncio.sleep(4)  # let the final turn and the notes settle


def _report(events_path: Path, participants: list[Participant]) -> int:
    events = load_events(events_path)
    listener = participants[0]
    notes = OUT / "meeting.md"
    markdown = notes.read_text(encoding="utf-8") if notes.exists() else ""
    checks = analyse(events, SCRIPT, len(listener.agent_frames)) + memory_checks(
        markdown
    )
    print(render(events, checks, SCRIPT))
    print(f"\nMeeting notes: {notes}")
    print(markdown)
    return 0 if all_ok(checks) else 1

"""`roundtable demo`: LiveKit in Docker, the agent as a subprocess per scenario, simulated participants, then assertions."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from roundtable.config import Settings
from roundtable.e2e import livekit
from roundtable.e2e.checks import (
    Check,
    all_ok,
    analyse,
    load_events,
    memory_checks,
    render,
    standup_checks,
)
from roundtable.e2e.record import Recorder, write_recording
from roundtable.e2e.script import (
    SCRIPT,
    STANDUP_NOTES,
    STANDUP_SCRIPT,
    STANDUP_UPDATE,
    Line,
    read_pcm,
    synthesise,
)
from roundtable.e2e.sims import Participant

log = logging.getLogger("roundtable.demo")
OUT = Path("out/e2e")
WAIT_TIMEOUT_S = 60.0
ENGINE_ENV = {
    # The keyless demo must never reach a cloud provider, even if keys are exported in the shell.
    "ROUNDTABLE_LLM": "scripted",
    "ROUNDTABLE_STT": "local",
    "ROUNDTABLE_TTS": "piper",
}


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    room: str
    script: tuple[Line, ...]
    speakers: tuple[str, ...]  # simulated humans, in join order; the first one listens
    agent_name: str  # the agent's name in the room
    agent_args: tuple[str, ...] = ()


ASSISTANT = Scenario(
    name="assistant",
    title="Assistant in a three-person call",
    room="roundtable-demo",
    script=SCRIPT,
    speakers=("Priya", "Dan", "Sam"),
    agent_name="Roundtable",
)
STANDUP = Scenario(
    name="standup",
    title="Standup proxy for an absent colleague (Sam)",
    room="roundtable-standup",
    script=STANDUP_SCRIPT,
    speakers=("Priya", "Dan"),
    agent_name="Sam (proxy)",
    agent_args=(
        "--mode",
        "standup",
        "--absent",
        "Sam",
        "--update",
        STANDUP_UPDATE,
        "--notes",
        str(OUT / "standup" / "notes.md"),
    ),
)


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


def _agent_env(settings: Settings, scenario: Scenario) -> dict[str, str]:
    env = {**os.environ, **ENGINE_ENV}
    env.update(
        LIVEKIT_URL=settings.livekit_url,
        LIVEKIT_API_KEY=settings.api_key,
        LIVEKIT_API_SECRET=settings.api_secret,
        ROUNDTABLE_ROOM=scenario.room,
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


async def run_scenario(
    scenario: Scenario, clips_dir: Path
) -> tuple[list[dict[str, Any]], list[Check], str, Recorder]:
    out = OUT / scenario.name
    out.mkdir(parents=True, exist_ok=True)
    settings = replace(Settings.from_env(), room=scenario.room, out_dir=out)
    if scenario.name == "standup":
        (out / "notes.md").write_text(STANDUP_NOTES, encoding="utf-8")
    clips = synthesise(clips_dir, scenario.script)
    events_path = out / "events.jsonl"
    events_path.unlink(missing_ok=True)
    watch = EventWatch(events_path)
    recorder = Recorder()
    agent: subprocess.Popen[bytes] | None = None
    participants: list[Participant] = []
    try:
        with (out / "agent.log").open("w", encoding="utf-8") as agent_log:
            agent = await asyncio.to_thread(
                subprocess.Popen,
                [sys.executable, "-m", "roundtable", "agent", *scenario.agent_args],
                env=_agent_env(settings, scenario),
                stdout=agent_log,
                stderr=subprocess.STDOUT,
            )
            if not await watch.until(lambda rs: any(r["kind"] == "joined" for r in rs)):
                raise RuntimeError(f"agent did not join; see {out / 'agent.log'}")
            participants = [
                Participant(
                    settings,
                    name,
                    scenario.agent_name,
                    recorder,
                    listens=index == 0,
                )
                for index, name in enumerate(scenario.speakers)
            ]
            for part in participants:
                await part.join()
            await _run_meeting(scenario, participants, watch, clips)
            await _stop_agent(agent)
    finally:
        for part in participants:
            await part.leave()
        if agent is not None:
            await _stop_agent(agent)
    events = load_events(events_path)
    listener_frames = len(participants[0].agent_frames) if participants else 0
    markdown = (
        (out / "meeting.md").read_text(encoding="utf-8")
        if (out / "meeting.md").exists()
        else ""
    )
    if scenario.name == "standup":
        checks = standup_checks(
            events, scenario.script, listener_frames, STANDUP_UPDATE
        )
    else:
        checks = analyse(events, scenario.script, listener_frames) + memory_checks(
            markdown
        )
    return events, checks, markdown, recorder


async def _run_meeting(
    scenario: Scenario,
    participants: list[Participant],
    watch: EventWatch,
    clips: tuple[Path, ...],
) -> None:
    by_speaker = {p.name: p for p in participants}
    plans: dict[str, list[tuple[int, Line]]] = {name: [] for name in scenario.speakers}
    for index, line in enumerate(scenario.script):
        plans[line.speaker].append((index, line))
    await asyncio.gather(
        *(
            _speak_script(by_speaker[name], plans[name], watch, clips)
            for name in scenario.speakers
        )
    )
    await asyncio.sleep(4)  # let the final turn and the notes settle


def _report(
    scenario: Scenario, events: list[dict[str, Any]], checks: list[Check], markdown: str
) -> None:
    print(f"\n=== {scenario.title} ===")
    print(render(events, checks, scenario.script))
    if markdown:
        print(f"\nMeeting notes: {OUT / scenario.name / 'meeting.md'}")
        print(markdown)


async def run_demo() -> int:
    clips_dir = OUT / "clips"
    results: list[tuple[Scenario, list[dict[str, Any]], list[Check], str]] = []
    try:
        livekit.start()
        await livekit.wait_ready()
        log.info("LiveKit is up")
        for scenario in (ASSISTANT, STANDUP):
            events, checks, markdown, recorder = await run_scenario(scenario, clips_dir)
            write_recording(
                OUT / scenario.name / "recording.json",
                scenario=scenario.name,
                title=scenario.title,
                agent=scenario.agent_name,
                roster=[{"name": n, "role": "human"} for n in scenario.speakers]
                + [{"name": scenario.agent_name, "role": "agent"}],
                events=events,
                checks=[
                    {"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks
                ],
                recorder=recorder,
            )
            recorder.write_wav(OUT / scenario.name / "mixed.wav")
            results.append((scenario, events, checks, markdown))
    finally:
        livekit.stop()
    for scenario, events, checks, markdown in results:
        _report(scenario, events, checks, markdown)
    total = sum(len(checks) for _, _, checks, _ in results)
    passed = sum(c.ok for _, _, checks, _ in results for c in checks)
    print(f"\nTOTAL: {passed}/{total} checks passed")
    return 0 if all(all_ok(checks) for _, _, checks, _ in results) else 1

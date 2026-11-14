"""`roundtable agent | serve | demo`. The agent joins the room; `serve` is the browser token API; `demo` is the keyless E2E."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from livekit.plugins import silero

from roundtable.agent import Roundtable
from roundtable.config import Settings
from roundtable.events import EventLog
from roundtable.llm import make_brain
from roundtable.persona import Persona
from roundtable.speech.stt import make_stt
from roundtable.speech.tts import make_tts
from roundtable.tokens import mint


def build_persona(args: argparse.Namespace, settings: Settings) -> Persona:
    if args.mode != "standup":
        return Persona.assistant(name=settings.agent_name)
    notes = Path(args.notes).read_text(encoding="utf-8") if args.notes else ""
    return Persona.standup(args.absent, args.update or "", notes)


async def run_agent(persona: Persona, settings: Settings) -> None:
    events = EventLog(settings.out_dir / "events.jsonl")
    roundtable = Roundtable(
        persona=persona,
        brain=make_brain(),
        stt=make_stt(),
        tts=make_tts(),
        vad=silero.VAD.load(),
        events=events,
        out_dir=settings.out_dir,
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, roundtable.request_stop)
    token = mint(
        settings,
        identity=f"{persona.name.lower().replace(' ', '-')}-agent",
        name=persona.name,
        room=settings.room,
    )
    await roundtable.run(settings.livekit_url, token)


def _agent(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    asyncio.run(run_agent(build_persona(args, settings), settings))
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from roundtable.server import make_app

    uvicorn.run(
        make_app(Settings.from_env()),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
    )
    return 0


def _demo(_: argparse.Namespace) -> int:
    from roundtable.e2e.run import run_demo

    return asyncio.run(run_demo())


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    parser = argparse.ArgumentParser(prog="roundtable")
    sub = parser.add_subparsers(dest="command", required=True)

    agent = sub.add_parser("agent", help="join the room as the agent")
    agent.add_argument("--mode", choices=["assistant", "standup"], default="assistant")
    agent.add_argument(
        "--absent", default="", help="standup: the absent person's first name"
    )
    agent.add_argument(
        "--update", default="", help="standup: the prepared update to deliver"
    )
    agent.add_argument(
        "--notes", default="", help="standup: a notes file for follow-up questions"
    )
    agent.set_defaults(func=_agent)

    serve = sub.add_parser("serve", help="token API for the browser client")
    serve.add_argument("--port", type=int, default=4501)
    serve.set_defaults(func=_serve)

    demo = sub.add_parser(
        "demo", help="keyless end-to-end run against a LiveKit container"
    )
    demo.set_defaults(func=_demo)

    args = parser.parse_args(argv)
    if args.command == "agent" and args.mode == "standup" and not args.absent:
        parser.error("--mode standup needs --absent NAME")
    return int(args.func(args))

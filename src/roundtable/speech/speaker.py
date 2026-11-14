"""One pipeline per human: their own audio stream -> Silero VAD -> STT. Emits floor events, never blocks on STT."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from livekit import rtc
from livekit.agents.vad import VADEventType

from roundtable.floor.model import Activity, Utterance
from roundtable.speech.audio import pcm_duration_ms
from roundtable.speech.stt import STT

SAMPLE_RATE = 16000
OnEvent = Callable[[object], None]
Clock = Callable[[], int]


async def pump_speaker(
    speaker: str,
    track: rtc.Track,
    vad: object,
    stt: STT,
    on_event: OnEvent,
    now_ms: Clock,
) -> None:
    """Consume one remote track until it ends. STT runs as its own task so barge-in is never delayed."""
    audio = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=1)
    vad_stream = vad.stream()  # type: ignore[attr-defined]
    pending: set[asyncio.Task[None]] = set()

    async def feed() -> None:
        async for event in audio:
            vad_stream.push_frame(event.frame)
        vad_stream.end_input()

    feeder = asyncio.create_task(feed())
    speech_started_at = 0
    try:
        async for vad_event in vad_stream:
            if vad_event.type == VADEventType.START_OF_SPEECH:
                speech_started_at = now_ms()
                on_event(Activity(speaker, "start", speech_started_at))
            elif vad_event.type == VADEventType.END_OF_SPEECH:
                end_ms = speech_started_at + int(vad_event.speech_duration * 1000)
                on_event(Activity(speaker, "end", end_ms))
                pcm = b"".join(bytes(frame.data) for frame in vad_event.frames)
                task = asyncio.create_task(
                    _transcribe(speaker, pcm, speech_started_at, end_ms, stt, on_event)
                )
                pending.add(task)
                task.add_done_callback(pending.discard)
    finally:
        feeder.cancel()
        for task in pending:
            task.cancel()


async def _transcribe(
    speaker: str,
    pcm: bytes,
    start_ms: int,
    end_ms: int,
    stt: STT,
    on_event: OnEvent,
) -> None:
    text = await stt.transcribe(pcm, SAMPLE_RATE)
    if not text:
        return
    duration = pcm_duration_ms(pcm, SAMPLE_RATE)
    on_event(Utterance(speaker, text, start_ms, max(end_ms, start_ms + duration)))

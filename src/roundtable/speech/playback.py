"""Paced playback of TTS audio into a LiveKit AudioSource, with barge-in that reports what was heard."""

from __future__ import annotations

import asyncio

from livekit import rtc

from roundtable.speech.audio import truncate_to_played
from roundtable.speech.tts import TTS


async def play(
    source: rtc.AudioSource,
    tts: TTS,
    text: str,
    cancel: asyncio.Event,
) -> tuple[int, int, str]:
    """Speak `text`. Returns (played_ms, total_ms, heard_text). Stops at once when `cancel` is set."""
    resampler = rtc.AudioResampler(tts.sample_rate, source.sample_rate, num_channels=1)
    pushed_ms = 0
    async for pcm in tts.synthesize(text):
        if cancel.is_set():
            break
        frame = rtc.AudioFrame(pcm, tts.sample_rate, 1, len(pcm) // 2)
        for out in resampler.push(frame):
            if cancel.is_set():
                break
            await source.capture_frame(out)
            pushed_ms += int(out.samples_per_channel * 1000 / out.sample_rate)
    for out in resampler.flush():
        pushed_ms += int(out.samples_per_channel * 1000 / out.sample_rate)
        if not cancel.is_set():
            await source.capture_frame(out)
    if cancel.is_set():
        # Audio still queued in the source has not been heard yet; drop it and count only what played.
        queued_ms = int(source.queued_duration * 1000)
        source.clear_queue()
        played_ms = max(pushed_ms - queued_ms, 0)
    else:
        await source.wait_for_playout()
        played_ms = pushed_ms
    return played_ms, pushed_ms, truncate_to_played(text, played_ms, pushed_ms)

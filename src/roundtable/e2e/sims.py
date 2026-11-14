"""Simulated human participants: real LiveKit clients that publish synthesised speech in real time."""

from __future__ import annotations

import asyncio
from collections import deque

import numpy as np
from livekit import rtc

from roundtable.config import Settings
from roundtable.e2e.script import SAMPLE_RATE
from roundtable.tokens import human_identity, mint

FRAME = SAMPLE_RATE // 100  # 10 ms
TAIL_SILENCE_S = 1.2  # long enough for the VAD to close the utterance


class Participant:
    def __init__(self, settings: Settings, name: str, agent_name: str) -> None:
        self.name = name
        self._settings = settings
        self._agent_name = agent_name
        self._room = rtc.Room()
        self._source = rtc.AudioSource(SAMPLE_RATE, 1)
        self._queue: deque[np.ndarray] = deque()
        self.agent_frames: list[
            int
        ] = []  # frame counts received from the agent, for the audio check
        self._tasks: list[asyncio.Task[None]] = []

    async def join(self) -> None:
        token = mint(
            self._settings,
            identity=human_identity(self.name),
            name=self.name,
            room=self._settings.room,
        )
        self._room.on("track_subscribed", self._on_track)
        await self._room.connect(self._settings.livekit_url, token)
        track = rtc.LocalAudioTrack.create_audio_track(f"{self.name}-mic", self._source)
        await self._room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        self._tasks.append(asyncio.create_task(self._feed()))

    async def leave(self) -> None:
        for task in self._tasks:
            task.cancel()
        await self._room.disconnect()

    def say(self, pcm: bytes) -> float:
        """Queue speech plus a trailing silence; returns how long that takes to play, in seconds."""
        samples = np.frombuffer(pcm, dtype="<i2")
        data = np.concatenate(
            [samples, np.zeros(int(TAIL_SILENCE_S * SAMPLE_RATE), dtype=np.int16)]
        )
        usable = len(data) - len(data) % FRAME
        self._queue.extend(data[i : i + FRAME] for i in range(0, usable, FRAME))
        return usable / SAMPLE_RATE

    async def _feed(self) -> None:
        """Real-time pacing: one 10 ms frame per tick, silence when nothing is queued."""
        silence = np.zeros(FRAME, dtype=np.int16)
        while True:
            chunk = self._queue.popleft() if self._queue else silence
            await self._source.capture_frame(self._frame(chunk))
            await asyncio.sleep(0.01)

    def _frame(self, chunk: np.ndarray) -> rtc.AudioFrame:
        return rtc.AudioFrame(chunk.tobytes(), SAMPLE_RATE, 1, FRAME)

    def _on_track(
        self, track: rtc.Track, _pub: object, participant: rtc.RemoteParticipant
    ) -> None:
        if (
            track.kind == rtc.TrackKind.KIND_AUDIO
            and participant.name == self._agent_name
        ):
            self._tasks.append(asyncio.create_task(self._count_agent_audio(track)))

    async def _count_agent_audio(self, track: rtc.Track) -> None:
        stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=1)
        async for _ in stream:
            self.agent_frames.append(1)

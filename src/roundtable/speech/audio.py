"""PCM helpers shared by the speech adapters. All audio here is mono 16-bit little-endian."""

from __future__ import annotations

import io
import wave

import numpy as np


def pcm16_to_float32(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def pcm_duration_ms(pcm: bytes, sample_rate: int) -> int:
    return int(len(pcm) / 2 * 1000 / sample_rate)


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def truncate_to_played(text: str, played_ms: int, total_ms: int) -> str:
    """What the listeners actually heard: the leading share of words matching the played share."""
    words = text.split()
    if total_ms <= 0 or played_ms >= total_ms:
        return " ".join(words)
    share = max(played_ms, 0) / total_ms
    return " ".join(words[: round(len(words) * share)])

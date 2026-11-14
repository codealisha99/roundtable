"""Copy the recorded e2e runs into site/replay/: timeline JSON plus the mixed room audio as MP3.

Run after `make demo`:  make replay   (uses `uv run --with lameenc`, so the encoder is not a project dependency)
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import lameenc

SRC = Path("out/e2e")
DEST = Path("site/replay")
SCENARIOS = ("assistant", "standup")
BITRATE_KBPS = 32  # speech at 16 kHz mono; keeps each run's audio well under 1 MB


def encode_mp3(wav_path: Path, mp3_path: Path) -> None:
    with wave.open(str(wav_path), "rb") as wav:
        rate, channels = wav.getframerate(), wav.getnchannels()
        pcm = wav.readframes(wav.getnframes())
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(BITRATE_KBPS)
    encoder.set_in_sample_rate(rate)
    encoder.set_channels(channels)
    encoder.set_quality(2)
    mp3_path.write_bytes(encoder.encode(pcm) + encoder.flush())


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    for name in SCENARIOS:
        run = SRC / name
        recording = json.loads((run / "recording.json").read_text(encoding="utf-8"))
        encode_mp3(run / "mixed.wav", DEST / f"{name}.mp3")
        recording["audio"] = f"replay/{name}.mp3"
        (DEST / f"{name}.json").write_text(
            json.dumps(recording, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"{name}: {(DEST / f'{name}.mp3').stat().st_size // 1024} KiB audio")
    return 0


if __name__ == "__main__":
    sys.exit(main())

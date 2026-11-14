"""Settings from the environment. Dev defaults match `livekit-server --dev`; override for anything else."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    livekit_url: str
    api_key: str
    api_secret: str
    room: str
    out_dir: Path
    agent_name: str = "Roundtable"

    @staticmethod
    def from_env() -> Settings:
        return Settings(
            livekit_url=os.environ.get("LIVEKIT_URL", "ws://localhost:7880"),
            api_key=os.environ.get("LIVEKIT_API_KEY", "devkey"),
            api_secret=os.environ.get("LIVEKIT_API_SECRET", "secret"),
            room=os.environ.get("ROUNDTABLE_ROOM", "roundtable"),
            out_dir=Path(os.environ.get("ROUNDTABLE_OUT_DIR", "out")),
            agent_name=os.environ.get("ROUNDTABLE_AGENT_NAME", "Roundtable"),
        )

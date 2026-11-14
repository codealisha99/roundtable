"""LiveKit server as a Docker container in dev mode. Container name is prefixed so we only ever remove our own."""

from __future__ import annotations

import asyncio
import subprocess
import time

import httpx

IMAGE = "livekit/livekit-server:latest"
CONTAINER = "roundtable-livekit"
HTTP_URL = "http://127.0.0.1:7880"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], check=check, capture_output=True, text=True
    )


def start() -> None:
    _docker("rm", "-f", CONTAINER, check=False)
    _docker(
        "run",
        "-d",
        "--name",
        CONTAINER,
        "-p",
        "7880:7880",
        "-p",
        "7881:7881",
        "-p",
        "7882:7882/udp",
        IMAGE,
        "--dev",
        "--bind",
        "0.0.0.0",
        "--node-ip",
        "127.0.0.1",
    )


def stop() -> None:
    _docker("rm", "-f", CONTAINER, check=False)


async def wait_ready(timeout_s: float = 60) -> None:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(timeout=2) as client:
        while time.monotonic() < deadline:
            try:
                if (await client.get(HTTP_URL)).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise TimeoutError("LiveKit did not become ready on port 7880")

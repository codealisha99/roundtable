"""Token server for the browser client. Humans get a join token for a room; secrets stay here."""

from __future__ import annotations

import json

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from roundtable.config import Settings
from roundtable.tokens import TokenRequestError, human_identity, mint, validate_request

# A token request is {"name": <=40 chars, "room": <=40 chars}; anything bigger is not for us.
MAX_BODY_BYTES = 2048


async def read_capped(request: Request, limit: int = MAX_BODY_BYTES) -> bytes | None:
    """The body, or None if it exceeds `limit`. Stops reading as soon as the limit is passed."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def make_app(settings: Settings) -> Starlette:
    async def token(request: Request) -> Response:
        raw = await read_capped(request)
        if raw is None:
            return JSONResponse(
                {"error": f"body must be at most {MAX_BODY_BYTES} bytes"},
                status_code=413,
            )
        try:
            body = json.loads(raw)
        except ValueError:
            return JSONResponse({"error": "body must be JSON"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be an object"}, status_code=400)
        try:
            name, room = validate_request(
                body.get("name"), body.get("room", settings.room)
            )
        except TokenRequestError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        identity = human_identity(name)
        return JSONResponse(
            {
                "token": mint(settings, identity=identity, name=name, room=room),
                "url": settings.livekit_url,
                "room": room,
                "identity": identity,
                "agent": settings.agent_name,
            }
        )

    async def health(_: Request) -> Response:
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/api/token", token, methods=["POST"]),
            Route("/api/health", health),
        ]
    )

"""Token server for the browser client. Humans get a join token for a room; secrets stay here."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from roundtable.config import Settings
from roundtable.tokens import TokenRequestError, human_identity, mint, validate_request


def make_app(settings: Settings) -> Starlette:
    async def token(request: Request) -> Response:
        try:
            body = await request.json()
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

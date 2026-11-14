"""Access tokens for humans (browser) and the agent. Minted server-side; secrets never reach the client."""

from __future__ import annotations

import re
import secrets

from livekit import api

from roundtable.config import Settings

ROOM_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
NAME_MAX = 40


class TokenRequestError(ValueError):
    pass


def validate_request(name: object, room: object) -> tuple[str, str]:
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > NAME_MAX:
        raise TokenRequestError(f"name must be 1-{NAME_MAX} characters")
    if not isinstance(room, str) or not ROOM_RE.match(room):
        raise TokenRequestError("room must be 1-40 lowercase letters, digits or dashes")
    return name.strip(), room


def mint(settings: Settings, *, identity: str, name: str, room: str) -> str:
    grants = api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )
    token = (
        api.AccessToken(settings.api_key, settings.api_secret)
        .with_identity(identity)
        .with_name(name)
        .with_grants(grants)
    )
    return token.to_jwt()


def human_identity(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "guest"
    return f"{slug}-{secrets.token_hex(3)}"

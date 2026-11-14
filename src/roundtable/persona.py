"""Who the agent is in the call: an assistant, or a standup proxy for someone who is absent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Mode = Literal["assistant", "standup"]


@dataclass(frozen=True)
class Persona:
    name: str  # roster display name
    aliases: tuple[str, ...]  # what people say to address it
    mode: Mode = "assistant"
    absent_name: str | None = None
    prepared_update: str | None = None
    notes: str | None = None

    @staticmethod
    def assistant(
        name: str = "Roundtable",
        aliases: tuple[str, ...] = ("roundtable", "round table"),
    ) -> Persona:
        return Persona(name=name, aliases=aliases)

    @staticmethod
    def standup(absent_name: str, prepared_update: str, notes: str) -> Persona:
        """Attends for `absent_name`: answers to their name, delivers the update, answers from notes."""
        return Persona(
            name=f"{absent_name} (proxy)",
            aliases=(absent_name.lower(),),
            mode="standup",
            absent_name=absent_name,
            prepared_update=prepared_update,
            notes=notes,
        )

    @property
    def addressed_as(self) -> str:
        return self.absent_name or "Roundtable"

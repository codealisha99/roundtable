"""Append-only JSONL event log. This file is the agent's audit trail and what the e2e test asserts on."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, TextIO

log = logging.getLogger("roundtable.events")
ECHO_KINDS = frozenset(
    {"utterance", "decision", "agent_speech_start", "barge_in", "gate", "finished"}
)


class EventLog:
    def __init__(self, path: Path, echo: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO | None = path.open("w", encoding="utf-8")
        self._t0 = time.monotonic()
        self._echo = echo

    def emit(self, kind: str, **fields: Any) -> None:
        t_ms = int((time.monotonic() - self._t0) * 1000)
        record = {"t_ms": t_ms, "kind": kind, **fields}
        if self._file is not None:
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._file.flush()
        if self._echo and kind in ECHO_KINDS:
            log.info("%s", _describe(record))

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def _describe(record: dict[str, Any]) -> str:
    kind = record["kind"]
    if kind == "utterance":
        return f"[{record['t_ms'] / 1000:6.1f}s] {record['speaker']}: {record['text']}"
    if kind == "decision":
        return f"           -> {record['action']}: {record['reason']}"
    if kind == "agent_speech_start":
        return f"           AGENT says: {record['text']}"
    return f"           {kind} {json.dumps({k: v for k, v in record.items() if k not in ('t_ms', 'kind')})}"

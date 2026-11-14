"""Unit tests for the pure helpers: addressing, prompts, gate parsing, playback truncation, token API."""

import asyncio

from starlette.testclient import TestClient

from roundtable.config import Settings
from roundtable.floor.addressing import (
    addressed_human,
    addresses_agent,
    is_decision_relevant,
    is_question,
    mentioned_human,
)
from roundtable.floor.model import Utterance
from roundtable.llm import ScriptedBrain, parse_gate
from roundtable.persona import Persona
from roundtable.respond import build_reply_prompt, reply
from roundtable.server import make_app
from roundtable.speech.audio import truncate_to_played, wav_bytes
from roundtable.tokens import TokenRequestError, human_identity, validate_request

SETTINGS = Settings(
    livekit_url="ws://localhost:7880",
    api_key="devkey",
    api_secret="secret-secret-secret-secret-secret-32",
    room="roundtable",
    out_dir=__import__("pathlib").Path("out/test"),
)


def test_addresses_agent_by_alias_and_at_mention():
    assert addresses_agent("hey Round Table, status?", ("roundtable", "round table"))
    assert addresses_agent("@roundtable status", ("roundtable",))
    assert not addresses_agent("the roundtables were long", ("roundtable",))


def test_addressed_human_checks_opening_words_only():
    assert addressed_human("Dan, can you look?", {"Dan", "Priya"}) == "Dan"
    assert addressed_human("I think Dan is right", {"Dan"}) is None
    assert mentioned_human("can you look, Dan?", {"Dan"}) == "Dan"


def test_question_and_decision_cues():
    assert is_question("Any blockers?")
    assert is_question("Can we move it")
    assert not is_question("Sounds good")
    assert is_decision_relevant("The deadline is Friday")
    assert not is_decision_relevant("Sounds good")


def test_parse_gate_fails_closed():
    assert parse_gate('noise {"speak": true, "text": "Owner missing."} trailing') == (
        True,
        "Owner missing.",
    )
    assert parse_gate('{"speak": false, "text": ""}') == (False, "")
    assert parse_gate("not json at all") == (False, "")
    assert parse_gate('{"speak": "yes"}') == (False, "")


def test_truncate_to_played_keeps_the_heard_share_of_words():
    text = "one two three four"
    assert truncate_to_played(text, 500, 1000) == "one two"
    assert truncate_to_played(text, 1000, 1000) == text
    assert truncate_to_played(text, 0, 1000) == ""


def test_wav_bytes_has_header():
    assert wav_bytes(b"\x00\x00" * 160, 16000)[:4] == b"RIFF"


def test_reply_prompt_carries_speaker_and_retrieved_lines():
    transcript = (
        Utterance("Priya", "The deadline is Friday.", 0, 1000),
        Utterance("Dan", "Vendor API is done.", 2000, 3000),
    )
    question = Utterance(
        "Priya", "Roundtable, what did Dan say about the vendor?", 4000, 5000
    )
    prompt = build_reply_prompt(
        summary="",
        transcript=transcript,
        question=question,
        items=(),
        humans=["Priya", "Dan"],
    )
    assert "Dan: Vendor API is done." in prompt
    assert "Priya just said to you" in prompt


def test_standup_delivers_prepared_update_once_then_answers_from_notes():
    persona = Persona.standup(
        "Sam", "Shipped the parser; PR up for review.", "Blocked on the vendor sandbox."
    )
    question = Utterance("Priya", "Sam, you're up.", 0, 1000)
    brain = ScriptedBrain(
        rules=(("Blocked on the vendor", "The vendor sandbox is the blocker."),),
        default="I will take that back to Sam.",
    )

    async def run() -> tuple[str, str, str]:
        first = await reply(
            brain,
            persona,
            question=question,
            transcript=(question,),
            items=(),
            humans=["Priya"],
            summary="",
            update_delivered=False,
        )
        follow = await reply(
            brain,
            persona,
            question=question,
            transcript=(question,),
            items=(),
            humans=["Priya"],
            summary="",
            update_delivered=True,
        )
        unknown = await reply(
            ScriptedBrain(default="I will take that back to Sam."),
            persona,
            question=question,
            transcript=(question,),
            items=(),
            humans=["Priya"],
            summary="",
            update_delivered=True,
        )
        return first, follow, unknown

    first, follow, unknown = asyncio.run(run())
    assert first == "Shipped the parser; PR up for review."
    assert follow == "The vendor sandbox is the blocker."
    assert "take that back to Sam" in unknown


def test_standup_without_prepared_update_says_so():
    persona = Persona.standup("Sam", "", "")
    question = Utterance("Priya", "Sam, you're up.", 0, 1000)
    text = asyncio.run(
        reply(
            ScriptedBrain(),
            persona,
            question=question,
            transcript=(question,),
            items=(),
            humans=[],
            summary="",
            update_delivered=False,
        )
    )
    assert "take that back" in text


def test_validate_request_rejects_bad_input():
    assert validate_request("  Priya ", "roundtable") == ("Priya", "roundtable")
    for bad in [
        ("", "roundtable"),
        ("x" * 41, "roundtable"),
        ("Priya", "Bad Room!"),
        (None, "roundtable"),
    ]:
        try:
            validate_request(*bad)
        except TokenRequestError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_human_identity_is_slugged_and_unique():
    first, second = human_identity("Priya Shah"), human_identity("Priya Shah")
    assert first.startswith("priya-shah-") and first != second


def test_token_api_mints_a_join_token_and_validates_input():
    client = TestClient(make_app(SETTINGS))
    ok = client.post("/api/token", json={"name": "Priya", "room": "roundtable"})
    assert ok.status_code == 200
    body = ok.json()
    assert (
        body["url"] == "ws://localhost:7880"
        and body["room"] == "roundtable"
        and body["token"].count(".") == 2
    )
    assert (
        client.post("/api/token", json={"name": "", "room": "roundtable"}).status_code
        == 400
    )
    assert client.post("/api/token", content=b"not json").status_code == 400
    assert client.post("/api/token", json=["list"]).status_code == 400
    assert client.get("/api/health").json() == {"ok": True}

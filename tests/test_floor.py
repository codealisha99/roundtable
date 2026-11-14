"""Scripted multi-speaker timelines for the floor manager (no LiveKit, no models)."""

from roundtable.floor.engine import apply, evaluate, initial_state
from roundtable.floor.model import (
    Activity,
    AgentEnded,
    AgentStarted,
    Consulted,
    Joined,
    Utterance,
)

AGENT = "Roundtable"
ALIASES = ("roundtable", "round table")


def start(speaker, at):
    return Activity(speaker=speaker, kind="start", at_ms=at)


def end(speaker, at):
    return Activity(speaker=speaker, kind="end", at_ms=at)


def say(speaker, text, start_ms, end_ms):
    return Utterance(speaker=speaker, text=text, start_ms=start_ms, end_ms=end_ms)


def play(state, events):
    for event in events:
        state = apply(state, event)
    return state


def fresh(aliases=ALIASES):
    return initial_state(agent_name=AGENT, aliases=aliases)


def speak_turn(state, text, start_ms, end_ms, played=None):
    """Agent speaks `text` between start_ms and end_ms and it lands in the transcript."""
    state = apply(state, AgentStarted(at_ms=start_ms, text=text))
    return apply(
        state,
        AgentEnded(at_ms=end_ms, played_text=played if played is not None else text),
    )


# --- addressed vs not addressed -------------------------------------------------


def test_addressed_by_name_waits_for_a_real_gap_then_speaks():
    state = play(
        fresh(),
        [
            start("Priya", 0),
            say("Priya", "Roundtable, what is the deadline?", 0, 2000),
            end("Priya", 2000),
        ],
    )
    assert evaluate(state, 2100).action == "wait"
    verdict = evaluate(state, 2800)
    assert verdict.action == "speak"
    assert "addressed" in verdict.reason


def test_addressed_by_multi_word_alias():
    state = play(
        fresh(), [say("Priya", "Hey round table, status?", 0, 1000), end("Priya", 1000)]
    )
    assert evaluate(state, 2000).action == "speak"


def test_statement_not_addressed_to_agent_stays_silent():
    state = play(
        fresh(),
        [
            say("Priya", "Sounds good, let's keep going", 0, 1500),
            end("Priya", 1500),
            say("Dan", "Agreed with that", 2000, 3000),
            end("Dan", 3000),
        ],
    )
    assert evaluate(state, 9000).action == "wait"


def test_addressed_to_another_human_is_not_the_agents_turn():
    state = play(
        fresh(),
        [
            Joined("Dan"),
            say("Priya", "Dan, can you check the build?", 0, 2000),
            end("Priya", 2000),
        ],
    )
    verdict = evaluate(state, 9000)
    assert verdict.action == "wait"
    assert "Dan" in verdict.reason


# --- never start while someone is speaking ---------------------------------------


def test_never_starts_while_a_human_is_speaking_even_if_addressed():
    state = play(
        fresh(), [start("Priya", 0), say("Priya", "Roundtable, status?", 0, 900)]
    )
    verdict = evaluate(state, 5000)
    assert verdict.action == "wait"
    assert "speaking" in verdict.reason


# --- group question followed by silence -----------------------------------------


def test_group_question_gets_answered_after_silence():
    state = play(
        fresh(),
        [say("Priya", "Any blockers on the migration?", 0, 3000), end("Priya", 3000)],
    )
    assert evaluate(state, 3000 + 1400).action == "wait"
    verdict = evaluate(state, 3000 + 1600)
    assert verdict.action == "speak"
    assert "group question" in verdict.reason


def test_group_question_answered_by_a_human_is_not_repeated():
    state = play(
        fresh(),
        [
            say("Priya", "Any blockers on the migration?", 0, 3000),
            end("Priya", 3000),
            say("Dan", "Blocked on the vendor", 3500, 5000),
            end("Dan", 5000),
        ],
    )
    assert evaluate(state, 9000).action != "speak"


# --- two humans mid-exchange ----------------------------------------------------


def test_backs_off_when_two_humans_are_mid_exchange():
    state = play(
        fresh(),
        [
            say("Priya", "Dan, can you check the build?", 0, 1000),
            end("Priya", 1000),
            say("Dan", "Sure", 1500, 2000),
            end("Dan", 2000),
            say("Priya", "Thanks, and anyone else?", 2500, 3500),
            end("Priya", 3500),
        ],
    )
    verdict = evaluate(state, 6000)
    assert verdict.action == "wait"
    assert "mid-exchange" in verdict.reason


def test_addressing_the_agent_overrides_mid_exchange():
    state = play(
        fresh(),
        [
            say("Priya", "Dan, can you check the build?", 0, 1000),
            end("Priya", 1000),
            say("Dan", "Sure", 1500, 2000),
            end("Dan", 2000),
            say("Priya", "Roundtable, did the build pass?", 2500, 3500),
            end("Priya", 3500),
        ],
    )
    assert evaluate(state, 3500 + 900).action == "speak"


# --- follow-up to what the agent just said --------------------------------------


def test_direct_follow_up_to_agent_turn_is_answered():
    state = speak_turn(fresh(), "Ship it on Friday.", 0, 3000)
    state = play(
        state, [say("Priya", "Can you explain that?", 4000, 5000), end("Priya", 5000)]
    )
    verdict = evaluate(state, 5700)
    assert verdict.action == "speak"
    assert "follow-up" in verdict.reason


def test_follow_up_window_expires():
    state = speak_turn(fresh(), "Ship it on Friday.", 0, 3000)
    state = play(
        state,
        [say("Priya", "Can you explain that?", 60000, 61000), end("Priya", 61000)],
    )
    # Still a question to the group, so the group-question rule applies, not follow-up.
    assert "follow-up" not in evaluate(state, 65000).reason


# --- barge-in --------------------------------------------------------------------


def test_barge_in_stops_only_after_debounce():
    state = fresh()
    state = apply(
        state,
        AgentStarted(at_ms=0, text="Here is a long answer about the rollout plan"),
    )
    state = apply(state, start("Priya", 1000))
    assert evaluate(state, 1100).action == "wait"
    verdict = evaluate(state, 1300)
    assert verdict.action == "stop"
    assert "Priya" in verdict.reason


def test_agent_speech_truncated_to_what_was_played_enters_transcript():
    state = fresh()
    state = apply(
        state,
        AgentStarted(at_ms=0, text="Here is a long answer about the rollout plan"),
    )
    state = apply(state, start("Priya", 1000))
    state = apply(
        state, AgentEnded(at_ms=1000, played_text="Here is a long", interrupted=True)
    )
    assert state.recent[-1].speaker == AGENT
    assert state.recent[-1].text == "Here is a long"
    assert state.agent_speaking is False


# --- overlap cooldown ------------------------------------------------------------


def test_no_talking_over_participants_for_cooldown_after_overlap():
    state = play(
        fresh(),
        [
            start("Priya", 0),
            start("Dan", 500),
            end("Dan", 2000),
            end("Priya", 2500),
            say("Dan", "Roundtable, status?", 2600, 3000),
            end("Dan", 3000),
        ],
    )
    assert evaluate(state, 3600).action == "wait"
    assert evaluate(state, 2500 + 1200 + 1000).action == "speak"


# --- consult (LLM) path ---------------------------------------------------------


def test_relevant_statement_triggers_one_consult_then_waits():
    state = play(
        fresh(), [say("Priya", "The deadline is Friday", 0, 2000), end("Priya", 2000)]
    )
    verdict = evaluate(state, 4500)
    assert verdict.action == "consult"
    state = apply(state, Consulted(at_ms=4500))
    assert evaluate(state, 5000).action == "wait"


def test_model_approval_speaks_only_if_floor_is_still_free():
    state = play(
        fresh(), [say("Priya", "The deadline is Friday", 0, 2000), end("Priya", 2000)]
    )
    assert evaluate(state, 4500, approved=True).action == "speak"
    state = apply(state, start("Dan", 4600))
    assert evaluate(state, 4700, approved=True).action == "wait"


# --- standup proxy: the absent person's name is the alias ----------------------


def test_standup_proxy_turn_comes_when_absent_person_is_called():
    state = fresh(aliases=("sam",))
    state = play(
        state, [say("Priya", "Sam, you're up for updates", 0, 2000), end("Priya", 2000)]
    )
    assert evaluate(state, 3000).action == "speak"


def test_transcript_stays_time_ordered_when_stt_finishes_out_of_order():
    state = play(
        fresh(),
        [
            say("Dan", "Later line", 5000, 6000),
            say("Priya", "Earlier line", 1000, 2000),
        ],
    )
    assert [u.text for u in state.recent] == ["Earlier line", "Later line"]


# --- addressed lines are not lost to later chatter ------------------------------


def test_addressed_question_is_not_hidden_by_a_filler_from_someone_else():
    state = play(
        fresh(),
        [
            start("Dan", 0),
            say("Dan", "Roundtable, what is the vendor status?", 0, 2000),
            end("Dan", 2000),
            start("Priya", 2200),
            say("Priya", "yeah", 2200, 2500),
            end("Priya", 2500),
        ],
    )
    assert evaluate(state, 3500).action == "speak"


def test_question_asked_while_agent_was_thinking_is_still_answered():
    state = play(
        fresh(),
        [
            start("Priya", 0),
            say("Priya", "Roundtable, what's the status?", 0, 2000),
            end("Priya", 2000),
            start("Dan", 3500),
            say("Dan", "Roundtable, and the risks?", 3500, 4800),
            end("Dan", 4800),
        ],
    )
    state = apply(state, AgentStarted(at_ms=5700, text="Status is green.", answers_ms=2000))
    state = apply(state, AgentEnded(at_ms=9000, played_text="Status is green."))
    assert evaluate(state, 9500).action == "speak"

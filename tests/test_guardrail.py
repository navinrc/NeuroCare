from datetime import timedelta

import pytest
from conftest import NOW, USER

from alexa_mcp_server.llm.fake import FakeEmbedder, FakeGuard
from alexa_mcp_server.pillars import guardrail, memory, overrides, sense_of_time, translator
from alexa_mcp_server.refine import Deps, ThreadRefiner
from alexa_mcp_server.safety import crisis
from alexa_mcp_server.store.base import user_pk

PK = user_pk(USER)
WORRY = "the presentation tomorrow"


def items(store, prefix=""):
    return store.query(PK, prefix)


def state(store):
    return store.get(PK, "STATE") or {}


# --- crisis precheck -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["I can't go on", "i CAN’T go on!!", "Sometimes I want to die.", "thinking about suicide", "I might hurt myself"],
)
def test_phrase_list_matches_case_and_punctuation(text):
    assert crisis.phrase_hit(text)


@pytest.mark.parametrize("text", ["The report is overdue", "This deadline is killing me", "I'm dying to see it"])
def test_phrase_list_ignores_ordinary_text(text):
    assert not crisis.phrase_hit(text)


def test_remember_short_circuits_and_stores_nothing(seeded):
    before = len(items(seeded))
    result = memory.remember(seeded, USER, "I can't go on like this", NOW)
    assert result["crisis"] is True
    assert result["resources"][0]["contact"] == "Call or text 988"
    assert "988" in result["speak"]
    assert set(result) == {"crisis", "resources", "speak"}
    assert len(items(seeded)) == before  # the seed already has STATE; the event goes there
    assert not any("go on" in str(i) for i in items(seeded))
    assert state(seeded)["crisis_events"] == 1


def test_decode_short_circuits_and_stores_nothing(seeded):
    result = translator.decode(seeded, USER, NOW, message="Honestly I want to die, this week is too much")
    assert result["crisis"] is True
    assert items(seeded, "INBOX#") == []


def test_forwarded_item_is_checked_on_decode_and_deleted(seeded):
    translator.add_inbox_item(seeded, USER, "I feel like ending my life", NOW)
    assert translator.decode(seeded, USER, NOW)["crisis"] is True
    assert items(seeded, "INBOX#") == []


def test_triage_returns_crisis_first(seeded):
    translator.add_inbox_item(seeded, USER, "Can you send the deck? Thanks, Priya", NOW)
    translator.add_inbox_item(seeded, USER, "i'm better off dead", NOW)
    result = translator.triage_inbox(seeded, USER, NOW)
    assert result["crisis"] is True
    assert [i["text"] for i in items(seeded, "INBOX#")] == ["Can you send the deck? Thanks, Priya"]


def test_log_topic_short_circuits_and_stores_nothing(seeded):
    result = guardrail.log_topic(seeded, USER, "I keep thinking about killing myself", NOW)
    assert result["crisis"] is True
    assert items(seeded, "TOPIC#") == []


@pytest.mark.parametrize(
    ("locale", "first", "speak"),
    [
        ("en-GB", "Samaritans", "116 123"),
        ("en-IN", "Tele-MANAS", "14416"),
        ("fr-FR", "Emergency services", "local emergency number"),
    ],
)
def test_resources_follow_profile_locale(seeded, locale, first, speak):
    memory.set_preference(seeded, USER, "locale", locale, NOW)
    result = memory.remember(seeded, USER, "I want to end it all", NOW)
    assert result["resources"][0]["name"] == first
    assert speak in result["speak"]


def test_guard_hit_triggers_crisis(seeded):
    guard = FakeGuard("no way out")
    result = memory.remember(seeded, USER, "There is no way out for me", NOW, guard=guard)
    assert result["crisis"] is True
    assert guard.calls == ["There is no way out for me"]


def test_guard_failure_does_not_block(seeded):
    result = memory.remember(seeded, USER, "Bring snacks", NOW, guard=FakeGuard(fail=True))
    assert result["id"].startswith("MEM#")


def test_phrase_hit_skips_the_guard(seeded):
    guard = FakeGuard()
    memory.remember(seeded, USER, "I want to die", NOW, guard=guard)
    assert guard.calls == []


def _slow_guard_refiner(store, *flag):
    guard = FakeGuard(*flag, delay=0.5)  # over the 250 ms budget
    deps = Deps(store=store, llm=None, embedder=None, clock=lambda: NOW, guard=guard)
    return guard, ThreadRefiner(deps, workers=1)


def test_guard_timeout_rechecks_async_and_flags_next_call(seeded):
    guard, refiner = _slow_guard_refiner(seeded, "no way out")
    result = memory.remember(seeded, USER, "There is no way out", NOW, guard=guard, refiner=refiner)
    assert result["id"].startswith("MEM#")  # the tool goes on while the guard is slow
    refiner.wait(timeout=10)
    assert seeded.get(PK, result["id"]) is None  # stored text deleted
    assert state(seeded)["crisis_flag_at"]
    assert not any(i.get("text") == "There is no way out" for i in items(seeded))
    flagged = crisis.pending_flag(seeded, USER, NOW)
    assert flagged["crisis"] is True
    assert crisis.pending_flag(seeded, USER, NOW) is None  # delivered once


def test_guard_timeout_then_clear_keeps_item(seeded):
    guard, refiner = _slow_guard_refiner(seeded, "no way out")
    result = memory.remember(seeded, USER, "Bring snacks", NOW, guard=guard, refiner=refiner)
    refiner.wait(timeout=10)
    assert seeded.get(PK, result["id"])["text"] == "Bring snacks"
    assert items(seeded, "CHECK#") == []
    assert crisis.pending_flag(seeded, USER, NOW) is None


def test_guard_timeout_on_decode_deletes_inbox_item(seeded):
    guard, refiner = _slow_guard_refiner(seeded, "no way out")
    result = translator.decode(seeded, USER, NOW, message="I see no way out", guard=guard, refiner=refiner)
    assert result["source"] == "baseline"
    refiner.wait(timeout=10)
    assert items(seeded, "INBOX#") == []
    assert crisis.pending_flag(seeded, USER, NOW)["crisis"] is True


def test_crisis_ignores_overrides(seeded):
    for token in overrides.TOKENS:
        overrides.override(seeded, USER, token, NOW)
    assert guardrail.log_topic(seeded, USER, "I'm thinking about suicide", NOW)["crisis"] is True


# --- rumination ----------------------------------------------------------------------------


def test_third_similar_topic_inside_window_detects(seeded):
    first = guardrail.log_topic(seeded, USER, WORRY, NOW)
    second = guardrail.log_topic(seeded, USER, "worried about the presentation tomorrow", NOW + timedelta(minutes=20))
    third = guardrail.log_topic(seeded, USER, WORRY, NOW + timedelta(minutes=40))
    assert (first["detected"], first["count"]) == (False, 1)
    assert (second["detected"], second["count"]) == (False, 2)
    assert (third["detected"], third["count"]) == (True, 3)
    assert third["redirect"] and third["override_options"] == list(overrides.TOKENS)
    assert third["speak"].startswith("This is the third time in 40 minutes that we've come back to")
    assert third["speak"].endswith("?")


def test_topics_outside_window_or_unrelated_do_not_count(seeded):
    guardrail.log_topic(seeded, USER, WORRY, NOW - timedelta(minutes=120))  # window is 90 min
    guardrail.log_topic(seeded, USER, "the dentist bill", NOW)
    result = guardrail.log_topic(seeded, USER, WORRY, NOW + timedelta(minutes=1))
    assert (result["detected"], result["count"]) == (False, 1)


def test_rumination_by_embedding_cosine(seeded):
    phrasings = ["the presentation tomorrow", "giving my talk to the team", "standing up in front of everyone"]
    embedder = FakeEmbedder(similar=[phrasings])
    results = [
        guardrail.log_topic(seeded, USER, text, NOW + timedelta(minutes=i), embedder=embedder)
        for i, text in enumerate(phrasings)
    ]
    assert [r["count"] for r in results] == [1, 2, 3]  # no shared words; matched on cosine
    assert results[-1]["detected"] is True


def test_rumination_without_embedding_consent_uses_words_only(seeded):
    memory.set_preference(seeded, USER, "consent.embeddings", False, NOW)
    phrasings = ["the presentation tomorrow", "giving my talk to the team", "standing up in front of everyone"]
    embedder = FakeEmbedder(similar=[phrasings])
    results = [guardrail.log_topic(seeded, USER, t, NOW, embedder=embedder) for t in phrasings]
    assert results[-1]["count"] == 1
    assert embedder.calls == []


def test_log_topic_rejects_empty(seeded):
    assert guardrail.log_topic(seeded, USER, "  ", NOW)["error"]["code"] == "INVALID_ARGUMENT"


# --- overrides -----------------------------------------------------------------------------


def _ruminate(store, times, start=NOW):
    return [guardrail.log_topic(store, USER, WORRY, start + timedelta(minutes=i)) for i in range(times)][-1]


def test_keep_going_once_suppresses_one_prompt(seeded):
    assert _ruminate(seeded, 3)["detected"] is True
    assert overrides.override(seeded, USER, "keep_going_once", NOW)["speak"]
    fourth = guardrail.log_topic(seeded, USER, WORRY, NOW + timedelta(minutes=5))
    assert fourth["detected"] is False and fourth["suppressed"] is True
    fifth = guardrail.log_topic(seeded, USER, WORRY, NOW + timedelta(minutes=6))
    assert fifth["detected"] is True


def test_snooze_15m_suppresses_check_in_then_expires(seeded):
    sense_of_time.start_block(seeded, USER, "the slides", NOW - timedelta(minutes=70))
    assert sense_of_time.check_in(seeded, USER, NOW)["level"] == "gentle"
    snooze = overrides.override(seeded, USER, "snooze_15m", NOW)
    assert snooze["active_until"]
    quiet = sense_of_time.check_in(seeded, USER, NOW + timedelta(minutes=10))
    assert quiet["level"] == "gentle" and quiet["suppressed"] is True and quiet["override_options"] == []
    later = sense_of_time.check_in(seeded, USER, NOW + timedelta(minutes=16))
    assert "suppressed" not in later


def test_pause_for_session_ends_with_block(seeded):
    sense_of_time.start_block(seeded, USER, "the slides", NOW - timedelta(minutes=95))
    overrides.override(seeded, USER, "pause_for_session", NOW)
    assert sense_of_time.check_in(seeded, USER, NOW)["suppressed"] is True
    sense_of_time.end_block(seeded, USER, NOW)
    sense_of_time.start_block(seeded, USER, "email", NOW - timedelta(minutes=0))
    assert "suppressed" not in sense_of_time.check_in(seeded, USER, NOW + timedelta(minutes=95))


def test_lower_sensitivity_raises_rumination_threshold(seeded):
    _ruminate(seeded, 3)
    result = overrides.override(seeded, USER, "lower_sensitivity", NOW)
    assert (result["key"], result["old_value"], result["new_value"]) == ("guardrail.rumination_threshold", 3, 4)
    assert memory.load_profile(seeded, USER)["guardrail"]["rumination_threshold"] == 4


def test_lower_sensitivity_after_check_in_moves_thresholds(seeded):
    sense_of_time.start_block(seeded, USER, "the slides", NOW - timedelta(minutes=70))
    sense_of_time.check_in(seeded, USER, NOW)
    result = overrides.override(seeded, USER, "lower_sensitivity", NOW)
    assert result["new_value"] == {"gentle": 75, "nudge": 105, "hard": 135}


def test_override_rejects_unknown_token(seeded):
    assert overrides.override(seeded, USER, "stop_forever", NOW)["error"]["code"] == "INVALID_ARGUMENT"


def test_overrides_are_logged(seeded):
    overrides.override(seeded, USER, "snooze_15m", NOW)
    logged = items(seeded, "OVERRIDE#")
    assert [(o["token"], o["created_at"][:19]) for o in logged] == [("snooze_15m", "2026-10-05T18:10:00")]


# --- hyperfocus and needs -----------------------------------------------------------------


def test_check_hyperfocus_flags_unmet_needs(seeded):
    sense_of_time.start_block(seeded, USER, "the slides", NOW - timedelta(minutes=130))
    guardrail.log_need(seeded, USER, "food", NOW - timedelta(minutes=60))
    result = guardrail.check_hyperfocus(seeded, USER, NOW)
    assert result["level"] == "hard"
    assert [n["kind"] for n in result["unmet_needs"]] == ["water", "break"]
    assert "No water logged" in result["speak"]
    assert result["speak"].endswith("Want a 5-minute break, or keep going?")


def test_log_need_clears_it(seeded):
    sense_of_time.start_block(seeded, USER, "the slides", NOW - timedelta(minutes=100))
    assert [n["kind"] for n in guardrail.check_hyperfocus(seeded, USER, NOW)["unmet_needs"]] == ["break"]
    logged = guardrail.log_need(seeded, USER, "break", NOW)
    assert logged["speak"] == "Noted: a break at 2:10 PM."
    assert guardrail.check_hyperfocus(seeded, USER, NOW)["unmet_needs"] == []


def test_log_need_rejects_unknown_kind(seeded):
    assert guardrail.log_need(seeded, USER, "coffee", NOW)["error"]["code"] == "INVALID_ARGUMENT"

import time
from datetime import timedelta

import pytest
from conftest import NOW, USER

from alexa_mcp_server.llm import LLMError
from alexa_mcp_server.llm.fake import FakeGuard, FakeLLM
from alexa_mcp_server.pillars import memory, plan, sense_of_time, tasks, translator
from alexa_mcp_server.refine import Deps, InlineRefiner, ThreadRefiner
from alexa_mcp_server.store.base import user_pk

DUMP = "Brain dump: renew passport, mom's birthday Sunday, salt and pepper for the party"
REFINED = {
    "items": [
        {"text": "renew passport", "tag": "admin", "bucket": "should", "due_at": None},
        {"text": "mom's birthday", "tag": "personal", "bucket": "must", "due_at": "2026-10-11T09:00"},
        {"text": "salt and pepper for the party", "tag": "life", "bucket": "could", "due_at": None},
    ]
}


def inline(store, llm):
    return InlineRefiner(Deps(store=store, llm=llm, embedder=None, clock=lambda: NOW))


def items(store):
    return store.query(user_pk(USER), "ITEM#")


# --- brain_dump -----------------------------------------------------------------------------


def test_baseline_split():
    assert plan.split_baseline("dump: a, b and c\nd; e.") == ["a", "b", "c", "d", "e"]
    assert plan.split_baseline("Renew passport") == ["Renew passport"]


def test_brain_dump_baseline_without_llm(store):
    result = plan.brain_dump(store, USER, DUMP, NOW, refiner=inline(store, None))
    assert result["source"] == "baseline" and result["refine"] == "failed"
    assert [i["text"] for i in result["items"]] == [
        "renew passport",
        "mom's birthday Sunday",
        "salt",
        "pepper for the party",
    ]
    assert {i["bucket"] for i in result["items"]} == {"should"} and {i["tag"] for i in result["items"]} == {None}
    assert result["speak"] == "Saved four."


def test_brain_dump_refine_fixes_split_tags_and_due(store):
    result = plan.brain_dump(store, USER, DUMP, NOW, refiner=inline(store, FakeLLM(REFINED)))
    assert result["source"] == "llm" and result["refine"] == "done"
    assert [(i["text"], i["tag"], i["bucket"]) for i in result["items"]] == [
        ("renew passport", "admin", "should"),
        ("mom's birthday", "personal", "must"),
        ("salt and pepper for the party", "life", "could"),
    ]
    assert result["items"][1]["due_at"] == "2026-10-11T09:00:00-04:00"  # local time read in the profile tz
    assert result["speak"] == "Saved three. Mom's birthday marked for Sunday."
    assert len(items(store)) == 3  # the 4th baseline item was removed


def test_brain_dump_is_fast_first_then_replaced(store):
    refiner = ThreadRefiner(Deps(store=store, llm=FakeLLM(REFINED, delay=3), embedder=None, clock=lambda: NOW))
    start = time.perf_counter()
    result = plan.brain_dump(store, USER, DUMP, NOW, refiner=refiner)
    assert time.perf_counter() - start < 0.3
    assert result["refine"] == "pending" and len(result["items"]) == 4
    baseline_ids = [i["id"] for i in result["items"]]
    refiner.wait(5)
    after = items(store)
    assert [i["text"] for i in after] == [i["text"] for i in REFINED["items"]]
    assert [i["sk"] for i in after] == baseline_ids[:3]  # ids reused, so a plan made meanwhile still points at them


@pytest.mark.parametrize("reply", [LLMError("down"), {"items": [{"text": "x", "tag": "chores", "bucket": "must"}]}])
def test_brain_dump_keeps_baseline_on_refine_failure(store, reply):
    result = plan.brain_dump(store, USER, DUMP, NOW, refiner=inline(store, FakeLLM(reply)))
    assert result["refine"] == "failed" and len(items(store)) == 4
    assert {i["refine"] for i in items(store)} == {"failed"}


def test_brain_dump_short_circuits_on_crisis(store):
    result = plan.brain_dump(store, USER, "groceries, I want to die, laundry", NOW, refiner=inline(store, None))
    assert result["crisis"] is True
    assert store.query(user_pk(USER)) == [store.get(user_pk(USER), "STATE")]  # only the event counter


def test_brain_dump_async_crisis_deletes_items(store):
    deps = Deps(store=store, llm=None, embedder=None, clock=lambda: NOW, guard=FakeGuard("no point", delay=0.4))
    refiner = ThreadRefiner(deps)
    result = plan.brain_dump(store, USER, "laundry, no point in anything", NOW, refiner=refiner, guard=deps.guard)
    assert "crisis" not in result
    refiner.wait(5)
    assert items(store) == [] and store.query(user_pk(USER), "DUMP#") == []
    assert store.get(user_pk(USER), "STATE")["crisis_flag_at"]


def test_brain_dump_rejects_empty(store):
    assert plan.brain_dump(store, USER, "  ", NOW)["error"]["code"] == "INVALID_ARGUMENT"
    assert plan.brain_dump(store, USER, ", and ,", NOW)["error"]["code"] == "INVALID_ARGUMENT"


# --- plan_today -----------------------------------------------------------------------------


@pytest.fixture
def busy(seeded):
    """Seed (3 open loops) + 4 dumped items + one decoded message."""
    plan.brain_dump(seeded, USER, "fix the slides, renew passport, water the plants, call mom", NOW)
    translator.decode(seeded, USER, NOW, message="Can you send the deck today? Thanks, Priya")
    return seeded


@pytest.mark.parametrize(("energy", "count"), [(None, 3), (5, 3), (4, 3), (3, 2), (2, 1), (1, 1)])
def test_plan_today_respects_energy(busy, energy, count):
    result = plan.plan_today(busy, USER, NOW, energy=energy)
    assert len(result["priorities"]) == count
    assert result["open_count"] == 8


@pytest.mark.parametrize("cap", [1, 2, 3])
def test_plan_today_never_exceeds_max_priorities(busy, cap):
    memory.set_preference(busy, USER, "plan.max_priorities", cap, NOW)
    for energy in (None, 1, 3, 5):
        assert len(plan.plan_today(busy, USER, NOW, energy=energy)["priorities"]) <= cap


def test_plan_today_ranking_is_deterministic(busy):
    result = plan.plan_today(busy, USER, NOW)
    # due date first (the seeded Q3 deck commitment), then bucket (the "must" message), then age.
    assert [p["text"] for p in result["priorities"]] == [
        "Send Priya the Q3 deck",
        "reply to Priya",
        "Book the dentist",
    ]
    assert result["priorities"][0]["due_at"]
    assert result["speak"] == (
        "Eight things open. I suggest three: Send Priya the Q3 deck, reply to Priya, and Book the dentist. "
        "Start with Send Priya the Q3 deck?"
    )
    assert busy.get(user_pk(USER), "PLAN#2026-10-05")["priorities"] == [p["id"] for p in result["priorities"]]


def test_plan_today_replaces_earlier_plan_and_skips_wait(store):
    plan.brain_dump(store, USER, "file the receipts", NOW, refiner=inline(store, None))
    first = plan.plan_today(store, USER, NOW)
    item = items(store)[0]
    store.put(user_pk(USER), item["sk"], {**item, "bucket": "wait"})
    second = plan.plan_today(store, USER, NOW)
    assert len(first["priorities"]) == 1 and second["priorities"] == []
    assert second["speak"] == "Nothing is open. Your day is clear."
    assert len(store.query(user_pk(USER), "PLAN#")) == 1


def test_low_energy_caps_active_task_steps(store):
    tasks.decompose(store, USER, "do my taxes", NOW)
    result = plan.plan_today(store, USER, NOW, energy=2)
    assert result["max_step_minutes"] == 10
    assert tasks.active_task(store, USER)["max_step_minutes"] == 10
    other = tasks.decompose(store, USER, "clean the kitchen", NOW)
    assert store.get(user_pk(USER), other["task_id"])["max_step_minutes"] == 10  # same day, same cap


def test_plan_today_rejects_bad_energy(store):
    assert plan.plan_today(store, USER, NOW, energy=9)["error"]["code"] == "INVALID_ARGUMENT"


# --- wrap_up --------------------------------------------------------------------------------


def test_wrap_up_reports_done_and_rolls_unfinished(busy):
    planned = plan.plan_today(busy, USER, NOW)
    memory.close_loop(busy, USER, "the Q3 deck", NOW)
    sense_of_time.start_block(busy, USER, "the slides", NOW - timedelta(minutes=30))
    result = plan.wrap_up(busy, USER, NOW)
    assert [d["text"] for d in result["done"]] == ["Send Priya the Q3 deck"]
    assert [r["text"] for r in result["rolled_over"]] == ["reply to Priya", "Book the dentist"]
    assert result["closed_block"]["task"] == "the slides"
    assert result["speak"] == (
        "Send Priya the Q3 deck done. Reply to Priya and Book the dentist moved to tomorrow. "
        "Stopped the slides after about 30 minutes."
    )
    assert busy.get(user_pk(USER), "PLAN#2026-10-05")["wrapped_at"]
    tomorrow = busy.get(user_pk(USER), "PLAN#2026-10-06")
    assert tomorrow["carried"] == [p["id"] for p in planned["priorities"][1:]]

    # Next day: carried items come first, ahead of anything due.
    next_day = plan.plan_today(busy, USER, NOW + timedelta(days=1))
    assert [p["text"] for p in next_day["priorities"][:2]] == ["reply to Priya", "Book the dentist"]


def test_wrap_up_without_rollover_leaves_items_open(busy):
    memory.set_preference(busy, USER, "plan.rollover", False, NOW)
    plan.plan_today(busy, USER, NOW, energy=1)
    result = plan.wrap_up(busy, USER, NOW)
    assert result["rolled_over"] == []
    assert result["speak"].startswith("Send Priya the Q3 deck is still open.")
    assert busy.get(user_pk(USER), "PLAN#2026-10-06") is None


def test_close_loop_marks_dumped_item_done_for_wrap_up(store):
    plan.brain_dump(store, USER, "renew passport", NOW, refiner=inline(store, None))
    plan.plan_today(store, USER, NOW)
    assert memory.close_loop(store, USER, "passport", NOW)["closed"]["text"] == "renew passport"
    assert plan.wrap_up(store, USER, NOW)["speak"] == "Renew passport done."


def test_wrap_up_without_plan(store):
    assert plan.wrap_up(store, USER, NOW) == {"done": [], "rolled_over": [], "speak": "There was no plan for today."}

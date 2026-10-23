# Phase 5 — verification steps

Checks phase 5 of `docs/spec.md` §11: task breakdown and daily plan. Covers `decompose`, `next_step`,
`done_step`, `split_step`, `skip_step`, `brain_dump`, `plan_today`, and `wrap_up`.
**Done when:**
- Steps are validated: count, minutes, verb-first, step 1 ≤ 5 minutes.
- `next_step` / `done_step` walk the list; `split_step` replaces only the current step; `skip_step`
  moves it to the end.
- LLM failure falls back (`fallback_hint`; the baseline step stays).
- Fast first: `decompose`, `split_step`, and `brain_dump` return their baseline without waiting on the
  LLM, then the refine replaces it.
- `brain_dump` splits multi-item text and is short-circuited by the crisis precheck (so is `decompose`).
- `plan_today` never exceeds `plan.max_priorities` and respects energy; `wrap_up` rolls unfinished items.

Branch `feat/phase-5-tasks-plan`, based on `main` (PR #11 merged). Takes about
20 minutes, plus 5 for the live Bedrock step (5).

> The seed uses times relative to when it is loaded. **Re-seed (step 2) just before the Inspector steps.**

---

## 0. Setup

```bash
cd ~/dev/devpost_hackathon
git fetch && git checkout feat/phase-5-tasks-plan && git pull
uv sync
```

## 1. Automated checks (acceptance)

```bash
uv run pytest -q                       # expect: 256 passed, 7 skipped (the live Bedrock tests)
# live (optional): 7 passed. Prints the model's steps and dump items.
BEDROCK_LIVE=1 AWS_PROFILE=neurocare-admin BEDROCK_GUARDRAIL_ID=7dnkm5nfui1e BEDROCK_GUARDRAIL_VERSION=1 \
  uv run pytest -m live -s
uv run ruff check . && uv run ruff format --check .
```

| Acceptance item (spec §11) | Test (`tests/test_tasks.py` unless noted) |
|---|---|
| Steps validated: verb-first | `test_verb_first` (8 cases) |
| … count (3–12; split 2–4), minutes (step 1 ≤ 5, others ≤ cap), verb-first | `test_validate_steps_rejects`, `test_split_count_is_two_to_four`, `test_short_later_step_is_rounded_up_to_five` |
| `next_step` / `done_step` walk the list | `test_next_and_done_walk_the_list`, `test_done_step_reports_next` |
| `split_step` replaces only the current step | `test_split_replaces_only_the_current_step` |
| `skip_step` moves it to the end; only step left stays | `test_skip_moves_current_step_to_end`, `test_skip_only_remaining_step_returns_it_unchanged` |
| Fallback on LLM failure (no LLM, error, invalid steps) | `test_decompose_fallback_on_llm_failure` (3 cases), `test_split_is_fast_first_and_keeps_instant_step_on_failure` |
| Fast first: `decompose` with a 3 s fake LLM returns < 300 ms, refine lands after | `test_decompose_is_fast_first_with_slow_llm`, `test_refine_after_baseline_step_done_inserts_after_it` |
| … `split_step` | `test_split_is_fast_first_and_keeps_instant_step_on_failure` |
| … `brain_dump` (ids reused when the refine lands) | `test_plan.py::test_brain_dump_is_fast_first_then_replaced` |
| `brain_dump` splits multi-item text; refine fixes split, tags, buckets, due | `test_plan.py::test_baseline_split`, `test_brain_dump_baseline_without_llm`, `test_brain_dump_refine_fixes_split_tags_and_due` |
| Crisis precheck short-circuits `decompose` and `brain_dump` (FINDINGS #27) | `test_decompose_short_circuits_on_crisis`, `test_plan.py::test_brain_dump_short_circuits_on_crisis`, `test_plan.py::test_brain_dump_async_crisis_deletes_items`, `test_server.py::test_crisis_short_circuits_over_mcp` |
| `plan_today` never exceeds `plan.max_priorities` | `test_plan.py::test_plan_today_never_exceeds_max_priorities` (caps 1–3 × 4 energies) |
| … respects energy (1–2 → 1, 3 → 2, else max; low energy caps steps at 10 min) | `test_plan.py::test_plan_today_respects_energy`, `test_low_energy_caps_active_task_steps` |
| … ranking deterministic | `test_plan.py::test_plan_today_ranking_is_deterministic` |
| `wrap_up` rolls unfinished items; carried items lead tomorrow's plan | `test_plan.py::test_wrap_up_reports_done_and_rolls_unfinished`, `test_wrap_up_without_rollover_leaves_items_open` |
| Over MCP: all 8 tools, schema bounds | `test_server.py::test_task_and_plan_tools_over_mcp` |
| Live Bedrock: decompose + split, brain dump | `test_bedrock_live.py::test_live_decompose_and_split`, `test_live_brain_dump` |

## 2. Seed demo data

```bash
uv run alexa-mcp-seed --reset
```

## 3. Start the server with a token

```bash
ALLOW_STATIC_TOKEN=true AUTH_TOKEN=devtoken uv run alexa-mcp-server
```

Leave `LLM_PROVIDER` unset for step 4: every refine fails at once, so you see the baselines and the
fallback. Step 5 runs the same tools with Bedrock.

## 4. Inspector

```bash
npx @modelcontextprotocol/inspector
```

Connect as before: Streamable HTTP, `http://127.0.0.1:8000/mcp`, header `Authorization: Bearer devtoken`.
**List Tools → expect 29**: phase 4's 21 plus `decompose`, `next_step`, `done_step`, `split_step`,
`skip_step`, `brain_dump`, `plan_today`, `wrap_up`.

### 4.1 Task breakdown, no LLM (baseline + fallback)

| # | Tool + arguments | Expected |
|---|---|---|
| a | `decompose` goal=`I don't know where to start with my taxes` | One step "Spend 5 minutes writing down what done looks like for your taxes" (5 min), `source: baseline`. `refine` is `pending` or `failed` (the background job fails at once without an LLM) |
| b | `next_step` | Same step, `remaining: 1`, and `fallback_hint` ("Break the goal into 3 to 5 short steps yourself… remember(kind=commitment)") |
| c | `split_step` | One step "Write one line about what done looks like for your taxes" (2 min) |
| d | `skip_step` | `skipped: null`, speak "This is the last one: …" |
| e | `done_step` | `remaining: 0`, speak "Done. That was the last step for your taxes." |
| f | `next_step` | "All steps are done for your taxes." |
| g | `decompose` goal=`I want to kill myself` | Crisis result only; `export_all` shows no new `TASK#` |

### 4.2 Brain dump, plan, wrap up

| # | Tool + arguments | Expected |
|---|---|---|
| h | `brain_dump` text=`Brain dump: renew passport, fix the slides and call the dentist` | 3 items, `bucket: should`, `tag: null`, `source: baseline`; speak "Saved three." |
| i | `brain_dump` text=`laundry, I want to end my life` | Crisis result; no `ITEM#` "laundry" in `export_all` |
| j | `plan_today` | `open_count: 6` (3 seeded commitments + 3 items); 3 priorities, first "Send Priya the Q3 deck" (only one with a due date); speak "Six things open. I suggest three: … Start with Send Priya the Q3 deck?" |
| k | `plan_today` energy=`3` | 2 priorities |
| l | `plan_today` energy=`1` | 1 priority; speak "… I suggest one: … Want to start with that?" |
| m | `plan_today` energy=`7` | Schema validation error (max 5) |
| n | `plan_today` (no energy), then `close_loop` text=`the Q3 deck` | Closed |
| o | `close_loop` text=`passport` | Closes the dumped item "renew passport" |
| p | `start_block` task=`the slides`, then `wrap_up` | `done`: Q3 deck; `rolled_over`: the other two; `closed_block` the slides; speak "Send Priya the Q3 deck done. … moved to tomorrow. Stopped the slides after …" |
| q | `export_all` | `PLAN#<tomorrow>` with `carried` = the two rolled ids |
| r | `set_preference` key=`plan.max_priorities` value=`1`, then `plan_today` energy=`5` | 1 priority. Set it back to `3`. (Carried items leading the next day's plan is covered by `test_wrap_up_reports_done_and_rolls_unfinished`.) |

### 4.3 Steps with a work block

| # | Tool + arguments | Expected |
|---|---|---|
| s | `decompose` goal=`clean the kitchen`, then `split_step` | Instant "Write one line about what done looks like for clean the kitchen" (the baseline step is already short) |
| t | `start_block` task=`kitchen`, then `done_step` | `export_all`: the `kitchen` block is ended. No new block, since the task has no next step |

## 5. Live Bedrock (needs `aws login --profile neurocare-admin`)

### 5.1 Live tests

```bash
BEDROCK_LIVE=1 AWS_PROFILE=neurocare-admin uv run pytest -m live -s -k "decompose or brain_dump"
```

Expect **2 passed**. The output prints the model's steps (3–12, step 1 ≤ 5 min), the split (2–4), and the
dump items. Last run (2026-10-23): decompose refine 3.3 s, 9 steps; split 4 steps; dump
`renew passport` / `mom's birthday` (due Sunday 9 AM) / `salt and pepper for the party`, speak
"Saved three. Mom's birthday marked for Sunday."

### 5.2 Over the server

```bash
uv run alexa-mcp-seed --reset
LLM_PROVIDER=bedrock AWS_PROFILE=neurocare-admin ALLOW_STATIC_TOKEN=true AUTH_TOKEN=devtoken uv run alexa-mcp-server
```

| # | Tool + arguments | Expected |
|---|---|---|
| z1 | `decompose` goal=`do my taxes` | Returns at once with the baseline step and `refine: pending` |
| z2 | wait ~5 s, `next_step` | A model step (verb first, ≤ 5 min), `refine: done`, `remaining` 3–12 |
| z3 | `done_step`, then `split_step` | Instant step at once; ~5 s later `next_step` shows the first of 2–4 smaller steps |
| z4 | `brain_dump` text=`renew passport, mom's birthday Sunday, salt and pepper for the party` | "Saved four." at once (baseline splits "salt and pepper") |
| z5 | wait ~5 s, `export_all` | 3 `ITEM#` rows with tags and buckets; "mom's birthday" has `due_at` Sunday 9 AM |

## Decisions to review

1. **Short later steps rounded up to 5 minutes** (FINDINGS #33). Live Haiku gave a 2-minute step 2;
   rejecting the whole plan for that throws away a good breakdown. Steps over the cap still fail.
2. **Verb-first is a heuristic** (`tasks.verb_first`): the first word is not a determiner, pronoun,
   filler ("maybe", "then", "step"), or "-ing" word, and the step isn't a question. No verb list.
3. **Overwhelm lead-ins are dropped from the goal** in speech ("I don't know where to start with my
   taxes" → "your taxes"). The stored `goal` keeps the user's words (FINDINGS #34).
4. **Instant split step**: "Do just the first 5 minutes of …" per spec, but a step already ≤ 5 minutes
   gets "first 2 minutes", and the decompose baseline gets "Write one line about what done looks
   like for …" (FINDINGS #34).
5. **One refine per task**: `split_step` while the `decompose` refine is pending returns the current
   step with "Still planning the steps" (FINDINGS #40).
6. **A refine that lands after the baseline step is done** inserts its steps after the done one,
   rather than replacing it.
7. **`done_step` and blocks**: if a block is open it is closed, and a new one opens for the next step
   with `planned_minutes`. With no open block, none is started. `check_in` levels are unchanged
   (FINDINGS #37).
8. **`brain_dump` baseline splits** on commas, semicolons, "and", and new lines (spec §5.6), not one
   item as §11 says (FINDINGS #32). The raw text lives in a `DUMP#` record (1-day TTL) for the
   refine, which reuses the baseline ids in order (FINDINGS #36).
9. **`plan_today` candidates**: open `ITEM#`s, open commitments, and decoded messages not handled yet.
   `wait` items are never picked. Items carried by `wrap_up` rank first the next day (FINDINGS #35).
10. **`close_loop` now closes dumped items** too, so `wrap_up` can report them done (FINDINGS #39).
11. **`speech.join_spoken`** said "a, and b" for two items; now "a and b" (FINDINGS #38).

## Known gaps

- `plan_today` ranking follows the spec literally: anything with a due date outranks a `must`
  message with a reply-by time (FINDINGS #41).
- Pinned Today message in Telegram: phase 6b.
- `next_step` does not wait for a pending refine (unlike `decode`); it says "Still planning the rest".

## Sign-off

- [x] 1 tests + lint
- [x] 4.1 task breakdown, no LLM (a–g)
- [x] 4.2 brain dump, plan, wrap up (h–r)
- [x] 4.3 steps with a work block (s–t)
- [x] 5.1 live tests (2 passed)
- [x] 5.2 live over the server (z1–z5)

---

## Proof (automated live run)

Reproduce: `scripts/prove.sh scripts/smoke/phase5.yaml`. No LLM configured (baselines + fallback).

_Run at 2026-10-23 00:43 IST against http://127.0.0.1:8765/mcp (fresh seed)._

Unauthenticated POST /mcp → HTTP 401 (expect 401)

### 1. tools/list

29 tools: brain_dump, check_hyperfocus, check_in, close_loop, decode, decode_result, decompose, delete_all, done_step, end_block, export_all, get_profile, log_need, log_topic, next_step, now_context, open_loops, override, ping, plan_today, recall, remember, set_preference, skip_step, split_step, start_block, triage_inbox, what_was_i_doing, wrap_up

### 2. `decompose({"goal": "I don't know where to start with my taxes"})` — 26 ms ✅

```json
{
  "task_id": "TASK#01M5JGFXAB2MW49XFA5EEMAFXS",
  "steps": [
    {
      "n": 1,
      "text": "Spend 5 minutes writing down what done looks like for your taxes",
      "minutes": 5
    }
  ],
  "source": "baseline",
  "refine": "failed",
  "speak": "First step: Spend 5 minutes writing down what done looks like for your taxes. About 5 minutes."
}
```

### 3. `next_step()` — 2 ms ✅

```json
{
  "n": 1,
  "text": "Spend 5 minutes writing down what done looks like for your taxes",
  "minutes": 5,
  "remaining": 1,
  "fallback_hint": "Planning failed. Break the goal into 3 to 5 short steps yourself, verb first, starting with a 5-minute physical one, and save each with remember(kind=commitment).",
  "refine": "failed",
  "speak": "Next: Spend 5 minutes writing down what done looks like for your taxes. About 5 minutes."
}
```

### 4. `split_step()` — 3 ms ✅

```json
{
  "steps": [
    {
      "n": 1,
      "text": "Write one line about what done looks like for your taxes",
      "minutes": 2
    }
  ],
  "remaining": 1,
  "refine": "pending",
  "speak": "Smaller step: Write one line about what done looks like for your taxes. About 2 minutes."
}
```

### 5. `skip_step()` — 2 ms ✅

```json
{
  "skipped": null,
  "next": {
    "n": 1,
    "text": "Write one line about what done looks like for your taxes",
    "minutes": 2
  },
  "remaining": 1,
  "speak": "This is the last one: Write one line about what done looks like for your taxes. About 2 minutes."
}
```

### 6. `done_step()` — 3 ms ✅

```json
{
  "completed": {
    "n": 1,
    "text": "Write one line about what done looks like for your taxes",
    "minutes": 2
  },
  "remaining": 0,
  "speak": "Done. That was the last step for your taxes."
}
```

### 7. `next_step()` — 1 ms ✅

```json
{
  "n": null,
  "remaining": 0,
  "speak": "All steps are done for your taxes."
}
```

### 8. `decompose({"goal": "I want to kill myself"})` — 3 ms ✅

```json
{
  "crisis": true,
  "resources": [
    {
      "name": "988 Suicide & Crisis Lifeline",
      "contact": "Call or text 988"
    },
    {
      "name": "Emergency services",
      "contact": "Call 911"
    }
  ],
  "speak": "You can call or text 988 any time to talk to someone right now. If you're in danger, call 911."
}
```

### 9. `brain_dump({"text": "Brain dump: renew passport, fix the slides and call the dentist"})` — 4 ms ✅

```json
{
  "items": [
    {
      "id": "ITEM#01M5JGFXBHG36NV846NK932WZT",
      "text": "renew passport",
      "tag": null,
      "bucket": "should"
    },
    {
      "id": "ITEM#01M5JGFXBHG36NV846NK932WZV",
      "text": "fix the slides",
      "tag": null,
      "bucket": "should"
    },
    {
      "id": "ITEM#01M5JGFXBJABGM1KCR12RQGTVM",
      "text": "call the dentist",
      "tag": null,
      "bucket": "should"
    }
  ],
  "source": "baseline",
  "refine": "pending",
  "speak": "Saved three."
}
```

### 10. `brain_dump({"text": "laundry, I want to end my life"})` — 2 ms ✅

```json
{
  "crisis": true,
  "resources": [
    {
      "name": "988 Suicide & Crisis Lifeline",
      "contact": "Call or text 988"
    },
    {
      "name": "Emergency services",
      "contact": "Call 911"
    }
  ],
  "speak": "You can call or text 988 any time to talk to someone right now. If you're in danger, call 911."
}
```

### 11. `plan_today()` — 2 ms ✅

```json
{
  "date": "2026-10-22",
  "open_count": 6,
  "priorities": [
    {
      "id": "MEM#01M5JGFWCDAAWVP8CYT16N1FCM",
      "text": "Send Priya the Q3 deck",
      "due_at": "2026-10-23T15:13:01-04:00"
    },
    {
      "id": "MEM#01M5JGFWCDAAWVP8CYT16N1FCP",
      "text": "Book the dentist"
    },
    {
      "id": "MEM#01M5JGFWCDAAWVP8CYT16N1FCN",
      "text": "Reply to Jordan about the venue"
    }
  ],
  "speak": "Six things open. I suggest three: Send Priya the Q3 deck, Book the dentist, and Reply to Jordan about the venue. Start with Send Priya the Q3 deck?"
}
```

### 12. `plan_today({"energy": 2})` — 3 ms ✅

```json
{
  "date": "2026-10-22",
  "open_count": 6,
  "max_step_minutes": 10,
  "priorities": [
    {
      "id": "MEM#01M5JGFWCDAAWVP8CYT16N1FCM",
      "text": "Send Priya the Q3 deck",
      "due_at": "2026-10-23T15:13:01-04:00"
    }
  ],
  "speak": "Six things open. I suggest one: Send Priya the Q3 deck. Want to start with that?"
}
```

### 13. `close_loop({"text": "the Q3 deck"})` — 3 ms ✅

```json
{
  "closed": {
    "id": "MEM#01M5JGFWCDAAWVP8CYT16N1FCM",
    "text": "Send Priya the Q3 deck"
  },
  "speak": "Done. I closed Send Priya the Q3 deck."
}
```

### 14. `wrap_up()` — 2 ms ✅

```json
{
  "done": [
    {
      "id": "MEM#01M5JGFWCDAAWVP8CYT16N1FCM",
      "text": "Send Priya the Q3 deck"
    }
  ],
  "rolled_over": [],
  "speak": "Send Priya the Q3 deck done."
}
```

**14 steps, 0 failed**

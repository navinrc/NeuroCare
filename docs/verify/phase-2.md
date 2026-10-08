# Phase 2 — verification steps

Checks phase 2 of `docs/spec.md` §11: sense of time (`now_context`, `start_block`, `end_block`, `check_in`).
**Done when:** `check_in` level boundaries are tested at 59/60/89/90/119/120 min and after end of day,
and `now_context` gives the right leave-by time.

Merged to `main` (PR #5). Takes about 15 minutes.

> The seed uses times relative to when it is loaded. Expected text such as "about 40 minutes"
> only holds right after seeding, so **re-seed (step 2) just before the Inspector steps**.

---

## 0. Setup

```bash
cd ~/dev/devpost_hackathon
git checkout main && git pull
uv sync
```

## 1. Automated checks (acceptance)

```bash
uv run pytest -q                       # expect: 93 passed
uv run ruff check src tests            # expect: All checks passed!
uv run ruff format --check src tests   # expect: all files already formatted
```

The acceptance criteria are covered by these tests in `tests/test_sense_of_time.py`:

| Test | Checks |
|---|---|
| `test_check_in_levels_during_the_day` | 0/59 → none, 60/89 → gentle, 90/119 → nudge, 120 → hard |
| `test_check_in_levels_after_end_of_day` | at 7 PM with end of day 18:00: 0/59 → gentle, 60/89 → nudge, 90/119/120 → hard |
| `test_after_end_of_day_wraps_past_midnight` | 18:00–04:59 counts as after end of day; 05:00–17:59 doesn't; no `end_of_day` → never |
| `test_now_context_with_leave_by` | due 3:00 PM − travel 20 − buffer 15 → `leave_by` 2:25 PM |
| `test_now_context_leave_by_uses_profile_buffer_and_past_time` | buffer from the profile; a passed leave-by says "You planned to leave by …" |

`ruff check .` (whole repo) is clean too; the old import-order issue in `docs/diagrams` is fixed.

## 2. Seed demo data

```bash
uv run alexa-mcp-seed --reset
# expect: Seeded 'demo': 2 people, 5 memories, 1 blocks
```

## 3. Start the server with a token

```bash
ALLOW_STATIC_TOKEN=true AUTH_TOKEN=devtoken uv run alexa-mcp-server
# expect: Uvicorn running on http://127.0.0.1:8000, and NO "Auth disabled" warning
```

## 4. Inspector (web UI)

```bash
npx @modelcontextprotocol/inspector
```

1. Transport Type: **Streamable HTTP**. URL: `http://127.0.0.1:8000/mcp`.
2. Authentication: header `Authorization` = `Bearer devtoken`. **Connect**.
3. **Tools → List Tools**. Expect 14: the 10 from phase 1 plus `now_context`, `start_block`,
   `end_block`, `check_in`.

Run these in order. Every result must have a `speak` field. `<now>` is your local time.

| # | Tool + arguments | Expected |
|---|---|---|
| a | `now_context` | `now` = local time with offset, `day_of_week` = today, `energy_zone` matches the hour (e.g. 14:00–17:00 → `afternoon_dip`). `current_block.task` "the budget email", `elapsed_minutes` ≈ 40. `next_commitment.text` "Send Priya the Q3 deck", due tomorrow, no `leave_by`. speak: "It's `<now>` on `<day>`. You've been on the budget email for about 40 minutes. Next: Send Priya the Q3 deck, tomorrow at `<time>`." |
| b | `check_in` | `level: "none"`, `elapsed_minutes` ≈ 40, `override_options: []`. speak: "You started the budget email about 40 minutes ago." |
| c | `set_preference` key=`time.checkin_thresholds.gentle`, value=`15`; then `.nudge`=`30`; then `.hard`=`45` | each saved (set gentle first; the thresholds must go up in order) |
| d | `check_in` | `level: "nudge"` (40 ≥ 30), 4 `override_options`, no `suggest_reminder_minutes`. speak ends "Want a 5-minute break, or keep going?" |
| e | `set_preference` key=`time.end_of_day`, value = an `HH:MM` earlier today than `<now>` and after 05:00 | saved |
| f | `check_in` | `level: "hard"` (one step up after end of day). speak includes "It's after your end of day." |
| g | `set_preference` key=`time.end_of_day`, value=`null`; then set thresholds back: `.hard`=`120`, `.nudge`=`90`, `.gentle`=`60` | saved (set hard first this time) |
| h | `start_block` task=`the slides` | `auto_closed` = {task "the budget email", minutes ≈ 40}. speak: "Started the slides. I stopped the budget email after about 40 minutes." |
| i | `start_block` task=`The Slides` | `already_open: true`, same `block_id` as h. speak: "You're already on The Slides. You started less than a minute ago." |
| j | `check_in` | `level: "none"`, task "the slides" |
| k | `end_block` summary=`outline done` | `task` "the slides". speak: "Stopped the slides after less than a minute." |
| l | `end_block` | `error.code: NOT_FOUND`, speak "Nothing is running right now." |
| m | `check_in` | `level: "none"`, `task: null`, speak "Nothing is running right now." |
| n | `what_was_i_doing` | `last_block.task` "the slides"; no `current_block` |
| o | `remember` text=`Call Alex`, kind=`commitment`, due_at = 30 min from now, e.g. `2026-10-07T15:30` | saved |
| p | `now_context` | `next_commitment.text` "Call Alex", `minutes_until` ≈ 30, no `leave_by`. speak ends "That's in about 30 minutes." |

`leave_by` needs `travel_minutes` on the commitment, and `remember` can't set that yet. So `leave_by`
is checked by the unit tests in step 1, not here.

### Optional: Inspector CLI

```bash
npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --transport http \
  --header "Authorization: Bearer devtoken" --method tools/call --tool-name now_context

npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --transport http \
  --header "Authorization: Bearer devtoken" --method tools/call --tool-name start_block --tool-arg "task=the slides"
```

## 5. Cleanup

- Stop the server (Ctrl-C) and re-seed: `uv run alexa-mcp-seed --reset`.

---

## Decisions to review

1. **"One step earlier" after end of day:** every level moves up one. `gentle` starts at once,
   `nudge` at the gentle threshold, `hard` at the nudge threshold.
2. **When "after end of day" stops:** at 05:00 local (`DAY_START` constant), so 1 AM still counts.
3. **`leave_by`** appears only when `travel_minutes` is known; otherwise speak says "That's in about N minutes"
   (for commitments due within 3 hours).
4. **One offer per check-in:** gentle offers a reminder at the next level's start; nudge and hard offer
   the 5-minute break.
5. **`start_block` with the task already running** keeps the timer (`already_open: true`) instead of restarting it.
6. **`check_in` with nothing running** returns `level: none`, not an error.

## Known gaps (not blockers for phase 2)

- No voice path for `travel_minutes` (`remember` doesn't take it; spec §5.1 contract).
- `override_options` lists the four tokens, but the `override` tool arrives in phase 4.
- Phase 1 rough edges still open: leading capital mid-sentence in `speak`, `.env.example` vars.

## Sign-off

- [ ] 1 tests + lint (acceptance)
- [ ] 2 seed
- [ ] 4a `now_context` returns time, zone, block, next commitment
- [ ] 4b–g `check_in` levels, thresholds, end of day
- [ ] 4h–n block start, auto-close, same-task, end, NOT_FOUND
- [ ] 4o–p next commitment countdown

---

## Proof (automated live run)

Reproduce: `scripts/prove.sh scripts/smoke/phase2.yaml` (own temp DB and port 8765; your `.data/` is untouched).

_Run at 2026-10-08 16:48 IST against http://127.0.0.1:8765/mcp (fresh seed)._

Unauthenticated POST /mcp → HTTP 401 (expect 401)

### 1. tools/list

14 tools: check_in, close_loop, delete_all, end_block, export_all, get_profile, now_context, open_loops, ping, recall, remember, set_preference, start_block, what_was_i_doing

### 2. `now_context()` — 21 ms ✅

```json
{
  "now": "2026-10-08T07:18:43-04:00",
  "day_of_week": "Thursday",
  "energy_zone": "early",
  "current_block": {
    "task": "the budget email",
    "started_at": "2026-10-08T06:38:42-04:00",
    "elapsed_minutes": 40
  },
  "next_commitment": {
    "text": "Send Priya the Q3 deck",
    "due_at": "2026-10-09T07:18:42-04:00",
    "minutes_until": 1440
  },
  "speak": "It's 7:18 AM on Thursday. You've been on the budget email for about 40 minutes. Next: Send Priya the Q3 deck, tomorrow at 7:18 AM."
}
```

### 3. `check_in()` — 2 ms ✅

```json
{
  "level": "none",
  "elapsed_minutes": 40,
  "task": "the budget email",
  "override_options": [],
  "speak": "You started the budget email about 40 minutes ago."
}
```

### 4. `set_preference({"key": "time.checkin_thresholds.gentle", "value": 15})` — 3 ms ✅

```json
{
  "key": "time.checkin_thresholds.gentle",
  "old_value": 60,
  "new_value": 15,
  "speak": "Done. Gentle is now 15."
}
```

### 5. `set_preference({"key": "time.checkin_thresholds.nudge", "value": 30})` — 2 ms ✅

```json
{
  "key": "time.checkin_thresholds.nudge",
  "old_value": 90,
  "new_value": 30,
  "speak": "Done. Nudge is now 30."
}
```

### 6. `set_preference({"key": "time.checkin_thresholds.hard", "value": 45})` — 2 ms ✅

```json
{
  "key": "time.checkin_thresholds.hard",
  "old_value": 120,
  "new_value": 45,
  "speak": "Done. Hard is now 45."
}
```

### 7. `check_in()` — 1 ms ✅

```json
{
  "level": "nudge",
  "elapsed_minutes": 40,
  "task": "the budget email",
  "override_options": [
    "snooze_15m",
    "keep_going_once",
    "pause_for_session",
    "lower_sensitivity"
  ],
  "speak": "You started the budget email about 40 minutes ago. Want a 5-minute break, or keep going?"
}
```

### 8. `set_preference({"key": "time.checkin_thresholds.hard", "value": 120})` — 2 ms ✅

```json
{
  "key": "time.checkin_thresholds.hard",
  "old_value": 45,
  "new_value": 120,
  "speak": "Done. Hard is now 120."
}
```

### 9. `set_preference({"key": "time.checkin_thresholds.nudge", "value": 90})` — 2 ms ✅

```json
{
  "key": "time.checkin_thresholds.nudge",
  "old_value": 30,
  "new_value": 90,
  "speak": "Done. Nudge is now 90."
}
```

### 10. `set_preference({"key": "time.checkin_thresholds.gentle", "value": 60})` — 2 ms ✅

```json
{
  "key": "time.checkin_thresholds.gentle",
  "old_value": 15,
  "new_value": 60,
  "speak": "Done. Gentle is now 60."
}
```

### 11. `start_block({"task": "the slides"})` — 3 ms ✅

```json
{
  "block_id": "BLOCK#01M4DKSBB5CP3PP87NDCAP6BKB",
  "started_at": "2026-10-08T07:18:43-04:00",
  "auto_closed": {
    "task": "the budget email",
    "minutes": 40
  },
  "speak": "Started the slides. I stopped the budget email after about 40 minutes."
}
```

### 12. `start_block({"task": "The Slides"})` — 2 ms ✅

```json
{
  "block_id": "BLOCK#01M4DKSBB5CP3PP87NDCAP6BKB",
  "started_at": "2026-10-08T07:18:43-04:00",
  "already_open": true,
  "speak": "You're already on The Slides. You started less than a minute ago."
}
```

### 13. `check_in()` — 1 ms ✅

```json
{
  "level": "none",
  "elapsed_minutes": 0,
  "task": "the slides",
  "override_options": [],
  "speak": "You started the slides less than a minute ago."
}
```

### 14. `end_block({"summary": "outline done"})` — 3 ms ✅

```json
{
  "task": "the slides",
  "minutes": 0,
  "speak": "Stopped the slides after less than a minute."
}
```

### 15. `end_block()` — 1 ms ✅

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "no block is open"
  },
  "speak": "Nothing is running right now."
}
```

### 16. `check_in()` — 1 ms ✅

```json
{
  "level": "none",
  "elapsed_minutes": null,
  "task": null,
  "override_options": [],
  "speak": "Nothing is running right now."
}
```

### 17. `what_was_i_doing()` — 2 ms ✅

```json
{
  "recent_memories": [
    {
      "id": "MEM#01M4DKSAEJZVWM1AF5H2D4AFWC",
      "text": "I prefer written instructions over calls",
      "kind": "preference",
      "subject": null,
      "created_at": "2026-10-07T07:18:42-04:00"
    },
    {
      "id": "MEM#01M4DKSAEJZVWM1AF5H2D4AFWB",
      "text": "The quarterly report is due Friday",
      "kind": "fact",
      "subject": "quarterly report",
      "created_at": "2026-10-06T07:18:42-04:00"
    }
  ],
  "open_loops": [
    {
      "id": "MEM#01M4DKSAEJZVWM1AF5H2D4AFWD",
      "text": "Send Priya the Q3 deck",
      "due_at": "2026-10-09T07:18:42-04:00"
    },
    {
      "id": "MEM#01M4DKSAEKYTGH2NC999HJBAGG",
      "text": "Book the dentist"
    },
    {
      "id": "MEM#01M4DKSAEKYTGH2NC999HJBAGF",
      "text": "Reply to Jordan about the venue"
    }
  ],
  "last_block": {
    "id": "BLOCK#01M4DKSBB5CP3PP87NDCAP6BKB",
    "task": "the slides",
    "started_at": "2026-10-08T07:18:43-04:00",
    "ended_at": "2026-10-08T07:18:43-04:00"
  },
  "speak": "The last thing you worked on was the slides. You stopped less than a minute ago. Three things are still open: Send Priya the Q3 deck, Book the dentist, and Reply to Jordan about the venue."
}
```

**17 steps, 0 failed**

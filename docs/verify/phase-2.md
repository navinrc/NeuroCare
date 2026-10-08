
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

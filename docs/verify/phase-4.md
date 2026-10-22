# Phase 4 — verification steps

Checks phase 4 of `docs/spec.md` §11: guardrail. Covers the crisis precheck, rumination
(`log_topic`), hyperfocus (`check_hyperfocus`, `log_need`), and `override`.
**Done when:**
- The crisis precheck short-circuits `remember`, `decode` and `log_topic` (and `triage_inbox`).
  `decompose` arrives in phase 5.
- An `ApplyGuardrail` timeout re-runs the check in the background, and a hit there makes the
  next call return crisis first.
- The 3rd similar `log_topic` inside the window is detected.
- An override suppresses the prompt.
- Crisis ignores overrides.

Branch `feat/phase-4-guardrail`. Takes about 20 minutes, plus 10 for the optional Bedrock Guardrails step.

> The seed uses times relative to when it is loaded. **Re-seed (step 2) just before the Inspector steps.**

---

## 0. Setup

```bash
cd ~/dev/devpost_hackathon
git fetch && git checkout feat/phase-4-guardrail && git pull
uv sync
```

## 1. Automated checks (acceptance)

```bash
uv run pytest -q                       # expect: 180 passed, 5 skipped (the live Bedrock tests)
# live (optional): 5 passed. Prints guardrail latency and Titan cosines.
BEDROCK_LIVE=1 AWS_PROFILE=neurocare-admin BEDROCK_GUARDRAIL_ID=7dnkm5nfui1e BEDROCK_GUARDRAIL_VERSION=1 \
  uv run pytest -m live -s
uv run ruff check . && uv run ruff format --check .
```

| Acceptance item (spec §11) | Test |
|---|---|
| Crisis precheck short-circuits `remember` | `test_guardrail.py::test_remember_short_circuits_and_stores_nothing` |
| … `decode` (spoken and forwarded) | `test_decode_short_circuits_and_stores_nothing`, `test_forwarded_item_is_checked_on_decode_and_deleted` |
| … `log_topic` | `test_log_topic_short_circuits_and_stores_nothing` |
| … `triage_inbox` (not in spec list; forwarded items are checked on decode) | `test_triage_returns_crisis_first` |
| … over MCP; result has only `crisis`, `resources`, `speak` | `test_server.py::test_crisis_short_circuits_over_mcp` |
| … `decompose` | phase 5 (tool doesn't exist yet) |
| Phrase list: case- and punctuation-insensitive; ordinary text passes | `test_phrase_list_matches_case_and_punctuation`, `test_phrase_list_ignores_ordinary_text` |
| `ApplyGuardrail` hit → crisis; failure doesn't block; phrase hit skips the guard | `test_guard_hit_triggers_crisis`, `test_guard_failure_does_not_block`, `test_phrase_hit_skips_the_guard` |
| `ApplyGuardrail` timeout → async re-run; hit deletes stored text and flags the next call | `test_guard_timeout_rechecks_async_and_flags_next_call`, `test_guard_timeout_on_decode_deletes_inbox_item`, `test_guard_timeout_then_clear_keeps_item` |
| Next call of **any** tool returns crisis first, once | `test_server.py::test_pending_crisis_flag_comes_first_on_any_tool` |
| Resources by profile locale (US, GB, IN, fallback) | `test_resources_follow_profile_locale` |
| 3rd similar `log_topic` inside the window detects | `test_third_similar_topic_inside_window_detects`, `test_topics_outside_window_or_unrelated_do_not_count` |
| Rumination with `FakeEmbedder` (carried from phase 3, FINDINGS #16) | `test_rumination_by_embedding_cosine`, `test_rumination_without_embedding_consent_uses_words_only` |
| Override suppresses | `test_keep_going_once_suppresses_one_prompt`, `test_snooze_15m_suppresses_check_in_then_expires`, `test_pause_for_session_ends_with_block`, `test_lower_sensitivity_*`, `test_overrides_are_logged` |
| Crisis ignores override | `test_crisis_ignores_overrides` (all four tokens active) |
| `check_hyperfocus` / `log_need` | `test_check_hyperfocus_flags_unmet_needs`, `test_log_need_clears_it` |

## 2. Seed demo data

```bash
uv run alexa-mcp-seed --reset
```

## 3. Start the server with a token

```bash
ALLOW_STATIC_TOKEN=true AUTH_TOKEN=devtoken uv run alexa-mcp-server
```

Leave `LLM_PROVIDER` unset for steps 4–5: crisis must work with no network.

## 4. Inspector

```bash
npx @modelcontextprotocol/inspector
```

Connect as in phase 2: Streamable HTTP, `http://127.0.0.1:8000/mcp`, header `Authorization: Bearer devtoken`.
**List Tools → expect 21**: phase 3's 17 plus `log_topic`, `check_hyperfocus`, `log_need`, `override`.

### 4.1 Crisis path

| # | Tool + arguments | Expected |
|---|---|---|
| a | `remember` text=`I can't go on like this` | Only 3 keys: `crisis: true`, `resources` (988 Lifeline, 911), `speak` "You can call or text 988 any time to talk to someone right now. If you're in danger, call 911." |
| b | `decode` message=`Honestly I want to die, this week is too much` | Same crisis result |
| c | `log_topic` topic=`thinking about suicide` | Same crisis result |
| d | `export_all` | **None** of the three texts appear anywhere. `STATE` shows `crisis_events: 3` and `last_crisis_at` |
| e | `set_preference` key=`locale` value=`en-GB`; then `remember` text=`I want to end it all` | `resources[0]` Samaritans 116 123; speak mentions 116 123 and 999. Set `locale` back to `en-US` |
| f | `remember` text=`This deadline is killing me` | **Not** a crisis: a normal "Got it…" save (ordinary figure of speech) |

### 4.2 Rumination + overrides

| # | Tool + arguments | Expected |
|---|---|---|
| g | `log_topic` topic=`the presentation tomorrow` | `detected: false`, `count: 1`, `window_minutes: 90`, speak "Okay. I've noted that the presentation tomorrow is on your mind." |
| h | `log_topic` topic=`worried about the presentation tomorrow` | `count: 2`, `detected: false` |
| i | `log_topic` topic=`the presentation tomorrow` | `detected: true`, `count: 3`, a `redirect`, 4 `override_options`. speak "This is the third time in … that we've come back to the presentation tomorrow. Want to …?" |
| j | `override` token=`keep_going_once` | speak "Okay. I'll skip the next check-in." |
| k | `log_topic` topic=`the presentation tomorrow` | `detected: false`, `suppressed: true`, plain acknowledgement |
| l | `log_topic` topic=`the presentation tomorrow` | `detected: true` again (the once-override was used up), a different `redirect` |
| m | `log_topic` topic=`the dentist bill` | `count: 1`: an unrelated worry doesn't count |
| n | `override` token=`lower_sensitivity` | `key: guardrail.rumination_threshold`, `old_value: 3`, `new_value: 4`. `get_profile` shows 4. Set it back: `set_preference` key=`guardrail.rumination_threshold` value=`3` |
| o | `override` token=`stop_forever` | Rejected by the schema (enum): the Inspector shows a validation error |

### 4.3 Hyperfocus, needs, and crisis vs override (seed block "the budget email" ≈ 40 min)

| # | Tool + arguments | Expected |
|---|---|---|
| p | `check_hyperfocus` | `level: none`, `elapsed_minutes` ≈ 40, `unmet_needs: []`, speak "You've been on the budget email for about 40 minutes." |
| q | `set_preference` key=`guardrail.need_intervals.water` value=`15`; then `check_hyperfocus` | `unmet_needs` = water (since `null`). speak adds "No water logged today. Want to get some water?" |
| r | `log_need` kind=`water` | speak "Noted: water at `<time>`." |
| s | `check_hyperfocus` | `unmet_needs: []` again. Set `guardrail.need_intervals.water` back to `120` |
| t | `set_preference` `time.checkin_thresholds.gentle`=`15`, `.nudge`=`30`, `.hard`=`45`; then `check_in` | `level: nudge` (`hard` once the block passes 45 min), speak ends "Want a 5-minute break, or keep going?" |
| u | `override` token=`snooze_15m`; then `check_in` | Still `level: nudge`, but `suppressed: true`, `override_options: []`, and speak has no question |
| v | With the snooze still active: `log_topic` topic=`I want to end it all` | Crisis result. **The override does not hide it.** Reset thresholds: `.hard`=`120`, `.nudge`=`90`, `.gentle`=`60` |

### 4.4 Pending crisis flag (async hit) — simulated

A real async hit needs a slow Bedrock guardrail, so simulate the flag the background check sets:

```bash
sqlite3 .data/neurocare.sqlite3 \
  "update items set doc = json_set(doc, '$.crisis_flag_at', '2026-10-21T00:00:00+00:00') where pk='USER#demo' and sk='STATE'"
```

| # | Tool | Expected |
|---|---|---|
| w | `now_context` (any tool except `ping`) | Crisis result instead of the time |
| x | `now_context` again | Normal result: the flag is delivered once |

## 5. Optional: live Bedrock Guardrails (needs your AWS login)

Bedrock content filters have no self-harm category, so the self-harm check is a **denied topic**.

Already created by CLI (FINDINGS #31): id `7dnkm5nfui1e`, version 1. Steps 1–4 are for reference; skip to 5.

1. Bedrock console → Guardrails → **Create guardrail** `neurocare-crisis`, us-east-1.
2. **Denied topics**: add `Self-harm` with definition "Statements about wanting to hurt or kill
   oneself, suicide, or not wanting to be alive." Add 3 sample phrases.
3. **Content filters**: Violence, input strength **High**. Skip the output filters (only input is checked).
4. Blocked message: anything (not used). **Create**, then **Create version** and note the id and version.
5. Run:
   ```bash
   aws login --profile neurocare-admin
   LLM_PROVIDER=bedrock AWS_PROFILE=neurocare-admin BEDROCK_GUARDRAIL_ID=7dnkm5nfui1e BEDROCK_GUARDRAIL_VERSION=1 \
     ALLOW_STATIC_TOKEN=true AUTH_TOKEN=devtoken uv run alexa-mcp-server
   ```
6. `remember` text=`Lately I feel like there's no point in being here at all`. It isn't on the phrase list, so
   the guard must catch it: crisis result now, **or** a normal save followed by crisis on the next
   tool call if the guard took > 250 ms (expected from a laptop: FINDINGS #30) (the saved memory is deleted; check with `export_all`).
7. `remember` text=`Bring snacks to the offsite`: normal save, still there after a few seconds.

## Decisions to review

1. **Crisis-first wrapper on every tool except `ping`** (`server.tool()`). The spec says "the next tool
   call" gets the pending flag, so read-only tools (`now_context`, `get_profile`…) deliver it too.
2. **`triage_inbox` runs the precheck** on each item it decodes, since forwarded items are checked
   on decode, not on ingest (spec §5.3). A hit returns the crisis result and deletes that item only.
3. **Phrase list** (`safety/crisis.py`): 30 phrases, matched on word boundaries after removing
   apostrophes and punctuation. Figures of speech like "killing me" and "dying to" are deliberately left out.
   "overdose" is in, so "caffeine overdose" will trigger it. Erring safe.
4. **Resources by profile `locale` region**: US, CA, GB, AU, IN. Anything else gets the fallback:
   local emergency number plus findahelpline.com. **Please check the numbers** (FINDINGS #28).
5. **Overrides suppress the prompt, not the level**: `check_in` and `check_hyperfocus` still report the level, with
   `suppressed: true`. `keep_going_once` is used up by the next prompt that would have shown.
   `lower_sensitivity` changes whichever guardrail prompted last (rumination +1, or check-in thresholds +15 min).
6. **Need fallback**: without a log, a need counts from the start of the open block, else 05:00 local.
7. **Redirects rotate** through `guardrail.preferred_redirects` on each further detection.

## Known gaps

- `decompose` / `brain_dump` precheck: phase 5.
- Telegram resources message on an async hit: phase 6b.
- Tiny race left in the async re-check (FINDINGS #23); closes with DynamoDB conditional writes in phase 6.

## Sign-off

- [ ] 1 tests + lint
- [ ] 4.1 crisis path (a–f)
- [ ] 4.2 rumination + overrides (g–o)
- [ ] 4.3 hyperfocus, needs, crisis vs override (p–v)
- [ ] 4.4 pending crisis flag (w–x)
- [ ] 5 live Bedrock Guardrails (optional)

---

## Proof (automated live run)

Reproduce: `scripts/prove.sh scripts/smoke/phase4.yaml`. Phrase list only (no Bedrock guardrail).

_Run at 2026-10-21 23:12 IST against http://127.0.0.1:8766/mcp (fresh seed)._

Unauthenticated POST /mcp → HTTP 401 (expect 401)

### 1. tools/list

21 tools: check_hyperfocus, check_in, close_loop, decode, decode_result, delete_all, end_block, export_all, get_profile, log_need, log_topic, now_context, open_loops, override, ping, recall, remember, set_preference, start_block, triage_inbox, what_was_i_doing

### 2. `remember({"text": "I can't go on like this"})` — 22 ms ✅

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

### 3. `decode({"message": "Honestly I want to die, this week is too much"})` — 3 ms ✅

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

### 4. `log_topic({"topic": "thinking about suicide"})` — 2 ms ✅

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

### 5. `export_all()` — 2 ms ✅

```json
{
  "items": [
    {
      "task": "the budget email",
      "started_at": "2026-10-21T17:02:55+00:00",
      "ended_at": null,
      "summary": null,
      "pk": "USER#demo",
      "sk": "BLOCK#01M5FRY62RHMPHXKMV77ETZ0PN"
    },
    {
      "kind": "fact",
      "text": "The quarterly report is due Friday",
      "subject": "quarterly report",
      "due_at": null,
      "travel_minutes": null,
      "status": null,
      "embedding": null,
      "created_at": "2026-10-19T17:42:55+00:00",
      "updated_at": "2026-10-19T17:42:55+00:00",
      "pk": "USER#demo",
      "sk": "MEM#01M5FRY62NDF12QEPKT9SM2Z53"
    },
    {
      "kind": "preference",
      "text": "I prefer written instructions over calls",
      "subject": null,
      "due_at": null,
      "travel_minutes": null,
      "status": null,
      "embedding": null,
      "created_at": "2026-10-20T17:42:55+00:00",
      "updated_at": "2026-10-20T17:42:55+00:00",
      "pk": "USER#demo",
      "sk": "MEM#01M5FRY62PZVKR6W4R85DD44AS"
    },
    {
      "kind": "commitment",
      "text": "Send Priya the Q3 deck",
      "subject": "Priya",
      "due_at": "2026-10-22T17:42:55+00:00",
      "travel_minutes": null,
      "status": "open",
      "embedding": null,
      "created_at": "2026-10-20T16:42:55+00:00",
      "updated_at": "2026-10-20T16:42:55+00:00",
      "pk": "USER#demo",
      "sk": "MEM#01M5FRY62QC4XEYGJAZ20R634V"
    },
    {
      "kind": "commitment",
      "text": "Reply to Jordan about the venue",
      "subject": "Jordan",
      "due_at": null,
      "travel_minutes": null,
      "status": "open",
      "embedding": null,
      "created_at": "2026-10-21T12:42:55+00:00",
      "updated_at": "2026-10-21T12:42:55+00:00",
      "pk": "USER#demo",
      "sk": "MEM#01M5FRY62QC4XEYGJAZ20R634W"
    },
    {
      "kind": "commitment",
      "text": "Book the dentist",
      "subject": null,
      "due_at": null,
      "travel_minutes": null,
      "status": "open",
      "embedding": null,
      "created_at": "2026-10-18T23:02:55+00:00",
      "updated_at": "2026-10-18T23:02:55+00:00",
      "pk": "USER#demo",
      "sk": "MEM#01M5FRY62RHMPHXKMV77ETZ0PM"
    },
    {
      "name": "Jordan",
      "role": "teammate",
      "notes": [
        "Owns the Q3 deck design."
      ],
      "aliases": [
        "Jordy"
      ],
      "created_at": "2026-10-21T17:42:55+00:00",
      "updated_at": "2026-10-21T17:42:55+00:00",
      "pk": "USER#demo",
      "sk": "PERSON#jordan"
    },
    {
      "name": "Priya",
      "role": "manager",
      "notes": [
        "Tends to be blunt in writing; short messages are normal, not anger."
      ],
      "aliases": [
        "P",
        "my boss"
      ],
      "created_at": "2026-10-21T17:42:55+00:00",
      "updated_at": "2026-10-21T17:42:55+00:00",
      "pk": "USER#demo",
      "sk": "PERSON#priya"
    },
    {
      "doc": {
        "display_name": "Sam",
        "timezone": "America/New_York",
        "style": {
          "register": "plain"
        },
        "time": {
          "end_of_day": "18:00"
        }
      },
      "updated_at": "2026-10-21T17:42:55+00:00",
      "pk": "USER#demo",
      "sk": "PROFILE"
    },
    {
      "open_block_id": "BLOCK#01M5FRY62RHMPHXKMV77ETZ0PN",
      "crisis_events": 3,
      "last_crisis_at": "2026-10-21T17:42:57+00:00",
      "pk": "USER#demo",
      "sk": "STATE"
    }
  ],
  "count": 10,
  "speak": "Exported 10 items."
}
```

### 6. `log_topic({"topic": "the presentation tomorrow"})` — 2 ms ✅

```json
{
  "detected": false,
  "count": 1,
  "window_minutes": 90,
  "override_options": [],
  "speak": "Okay. I've noted that the presentation tomorrow is on your mind."
}
```

### 7. `log_topic({"topic": "worried about the presentation tomorrow"})` — 2 ms ✅

```json
{
  "detected": false,
  "count": 2,
  "window_minutes": 90,
  "override_options": [],
  "speak": "Okay. I've noted that worried about the presentation tomorrow is on your mind."
}
```

### 8. `log_topic({"topic": "the presentation tomorrow"})` — 2 ms ✅

```json
{
  "detected": true,
  "count": 3,
  "window_minutes": 90,
  "override_options": [
    "snooze_15m",
    "keep_going_once",
    "pause_for_session",
    "lower_sensitivity"
  ],
  "redirect": "Write down the one thing you're worried about and set it aside until tomorrow",
  "speak": "This is the third time in less than a minute that we've come back to the presentation tomorrow. Want to write down the one thing you're worried about and set it aside until tomorrow?"
}
```

### 9. `override({"token": "keep_going_once"})` — 2 ms ✅

```json
{
  "token": "keep_going_once",
  "speak": "Okay. I'll skip the next check-in."
}
```

### 10. `log_topic({"topic": "the presentation tomorrow"})` — 3 ms ✅

```json
{
  "detected": false,
  "count": 4,
  "window_minutes": 90,
  "override_options": [],
  "suppressed": true,
  "speak": "Okay. I've noted that the presentation tomorrow is on your mind."
}
```

### 11. `log_topic({"topic": "the presentation tomorrow"})` — 3 ms ✅

```json
{
  "detected": true,
  "count": 5,
  "window_minutes": 90,
  "override_options": [
    "snooze_15m",
    "keep_going_once",
    "pause_for_session",
    "lower_sensitivity"
  ],
  "redirect": "Switch to something else on purpose for 15 minutes",
  "speak": "This is the fifth time in less than a minute that we've come back to the presentation tomorrow. Want to switch to something else on purpose for 15 minutes?"
}
```

### 12. `override({"token": "snooze_15m"})` — 2 ms ✅

```json
{
  "token": "snooze_15m",
  "active_until": "2026-10-21T13:57:57-04:00",
  "speak": "Okay. No check-ins for 15 minutes."
}
```

### 13. `log_topic({"topic": "I want to end it all"})` — 2 ms ✅

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

### 14. `check_hyperfocus()` — 2 ms ✅

```json
{
  "level": "none",
  "elapsed_minutes": 40,
  "task": "the budget email",
  "unmet_needs": [],
  "override_options": [],
  "speak": "You've been on the budget email for about 40 minutes."
}
```

### 15. `log_need({"kind": "water"})` — 2 ms ✅

```json
{
  "kind": "water",
  "logged_at": "2026-10-21T13:42:57-04:00",
  "speak": "Noted: water at 1:42 PM."
}
```

### 16. `check_hyperfocus()` — 1 ms ✅

```json
{
  "level": "none",
  "elapsed_minutes": 40,
  "task": "the budget email",
  "unmet_needs": [],
  "override_options": [],
  "speak": "You've been on the budget email for about 40 minutes."
}
```

### 17. `override({"token": "lower_sensitivity"})` — 2 ms ✅

```json
{
  "token": "lower_sensitivity",
  "key": "guardrail.rumination_threshold",
  "old_value": 3,
  "new_value": 4,
  "speak": "Okay. I'll mention a repeated worry only after 4 times."
}
```

**17 steps, 0 failed**

# Phase 3 — verification steps

Checks phase 3 of `docs/spec.md` §11: translator (`decode`, `decode_result`, `triage_inbox`,
`POST /inbox`), the Bedrock wrapper, fast-first refine, and the embedding tier.

Branch `feat/phase-3-translator`, merged to `main`. About 15 minutes (plus 2 for the live Bedrock test).

## 0. Setup

```bash
cd ~/dev/devpost_hackathon && git checkout main && git pull && uv sync
```

## 1. Automated checks (acceptance)

```bash
uv run pytest -q                       # expect: 135 passed, 2 skipped (the live Bedrock tests)
uv run ruff check . && uv run ruff format --check .
```

| Acceptance item (spec §11) | Test |
|---|---|
| Baseline-only path with fake LLM failure | `test_translator.py::test_refine_failure_keeps_baseline` (timeout, bad enum, confidences > 1, missing fields, `reply_by` without offset) and `test_no_llm_configured_marks_failed` |
| Schema-validated LLM path with fake LLM | `test_llm_refine_validated_and_stored` (also checks the prompt wraps the message in `<message>` tags) |
| One live Bedrock smoke test | `test_bedrock_live.py` — **needs you**, see step 2 |
| Fast first: fake LLM with a 3 s delay, `decode` returns in < 300 ms; async refine stores `done` / `failed` | `test_fast_first_returns_before_slow_llm`, `test_fast_first_async_failure` |
| Embedding tier with `FakeEmbedder`; null embeddings backfilled | `test_semantic.py` (recall, close_loop, consent off, embedder down, 200 ms budget, embed-on-write job) |
| Rumination with `FakeEmbedder` | arrives with `log_topic` in phase 4 (see FINDINGS) |
| `POST /inbox` → `decode()` with no message decodes newest; `NOT_FOUND` when empty | `test_inbox.py::test_post_inbox_then_decode`, `test_translator.py::test_decode_without_message_uses_newest_inbox_item` |
| Triage fields present: `related` from seeded commitments, `cues` from baseline | `test_baseline_triage_fields_and_related` |
| Injected instructions → normal result, no side effects | `test_injected_instructions_have_no_side_effects` (store unchanged except the new item; extra model keys dropped; `</message>` inside the text defused) |
| Sender tiers 1–4 (header, unambiguous signature, ambiguous → none) | `test_sender_tiers` |
| `triage_inbox` orders priority → reply_by → age, decodes ≤ 3 per call | `test_triage_orders_and_limits_decodes` |

## 2. Live Bedrock smoke test (needs your AWS login)

```bash
aws sso login --profile neurocare-admin
BEDROCK_LIVE=1 AWS_PROFILE=neurocare-admin uv run pytest -m live -s
# expect: 2 passed. Prints the refined decode and two cosine scores (related > unrelated).
```

If it fails with `ValidationException` on the model id, copy the Haiku 4.5 inference-profile id
from the Bedrock console into `BEDROCK_MODEL_ID` and re-run. To run the server with Bedrock:
`LLM_PROVIDER=bedrock AWS_PROFILE=neurocare-admin uv run alexa-mcp-server`.

## 3. Inspector (manual)

```bash
uv run alexa-mcp-seed --reset
ALLOW_STATIC_TOKEN=true AUTH_TOKEN=devtoken uv run alexa-mcp-server
uv run alexa-mcp-inbox-token     # in another terminal; copy the token
```

Connect the Inspector as in phase 2. Expect **17 tools** (phase 2's 14 + `decode`, `decode_result`, `triage_inbox`).

| # | Action | Expected |
|---|---|---|
| a | `decode` (no args) | `error.code: NOT_FOUND` |
| b | `decode` message=`Per my last email, can you send the Q3 deck by today? Thanks, Priya` | `priority: must`, `temperature: tense`, `sender_source: signature`, `related` = "Send Priya the Q3 deck", `cues` include "per my last email". speak starts "Most likely Priya is waiting on something…" and ends "Want a reminder before then?" |
| c | `decode_result` | without Bedrock: `refine: failed`, speak "I couldn't get more detail…". With `LLM_PROVIDER=bedrock`: first "Still working on the details…", a few seconds later the summary and a suggested reply |
| d | `curl -X POST http://127.0.0.1:8000/inbox -H "Authorization: Bearer <inbox token>" -H 'Content-Type: application/json' -d '{"text":"Could you review the venue contract by Friday?","sender":"Jordy"}'` | HTTP 201 `{"id":"INBOX#…"}` |
| e | same curl without the header | HTTP 401 |
| f | `decode` (no args) | decodes the forwarded message: `sender_source: channel`, sender resolved from alias "Jordy" to Jordan |
| g | `triage_inbox` | items ranked must → should → …; speak reads at most 3 |
| h | `close_loop` text=`the message from Priya` | "Done. I marked the message from Priya as handled."; `triage_inbox` no longer lists it |

## Decisions to review

1. **Bedrock Converse via boto3**, not the Anthropic SDK: the spec locks Converse so Nova can be swapped
   in, and boto3 is needed anyway for Titan embeddings and Guardrails.
2. **`LLM_PROVIDER` env var** (default `off`): without it, every language task stays on its baseline and the
   refine marks `failed` at once. Not in the spec's env list; added so local dev never needs AWS.
3. **Refine runner:** a thread pool locally (`ThreadRefiner`); the Lambda self-invoke runner comes with phase 6.
4. **Embeddings on write run as a background `embed` job**, not inline, to keep `remember` fast. Missed
   ones are backfilled when the embedding tier scans them, inside its 200 ms budget.
5. **Embedding threshold 0.5 cosine** (`semantic.EMBED_THRESHOLD`). Needs a check against real Titan
   scores (live test prints two).
6. **Deadlines:** "today"/"EOD" → 5 PM today (or +1 h if past 5), "tomorrow" → 5 PM tomorrow, "by Friday" →
   5 PM that day (today if it is Friday), "ASAP"/"urgent" → +2 h. Reminder offered 30 min before, minimum 5.
7. **One offer per decode:** reminder when `reply_by` is known, else breakdown when `needs_work`, else
   "Who's it from?" (voice, no sender), else "I don't know X yet".
8. **Upset messages count as reply needed.**
9. **`close_loop` also matches open messages** ("that's handled") and resolves them; a commitment
   with `inbox_id` resolves its message when closed (used by the Telegram button in 6b).
10. **TTL clock is injectable** in `SQLiteStore` so tests don't start failing a week after the fixed test date.

## Known gaps

- Crisis precheck on `decode` arrives with phase 4.
- `sender_source: "asked"` (picking a sender after the fact) arrives with Telegram in 6b.
- Telegram card edit when a refine lands: 6b.

## Sign-off

- [ ] 1 tests + lint
- [ ] 2 live Bedrock test (needs AWS login)
- [ ] 3a–c decode + decode_result
- [ ] 3d–f POST /inbox → decode
- [ ] 3g–h triage + handled

---

## Proof (automated live run)

Reproduce: `scripts/prove.sh scripts/smoke/phase3.yaml`. Runs with `LLM_PROVIDER` off, so refines are `failed` by design.

_Run at 2026-10-08 17:00 IST against http://127.0.0.1:8765/mcp (fresh seed)._

Unauthenticated POST /mcp → HTTP 401 (expect 401)

### 1. tools/list

17 tools: check_in, close_loop, decode, decode_result, delete_all, end_block, export_all, get_profile, now_context, open_loops, ping, recall, remember, set_preference, start_block, triage_inbox, what_was_i_doing

### 2. `decode()` — 31 ms ✅

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "no undecoded inbox item"
  },
  "speak": "I don't have a new message from you to read."
}
```

### 3. `decode({"message": "Per my last email, can you send the Q3 deck by today? Thanks, Priya"})` — 5 ms ✅

```json
{
  "id": "INBOX#01M4DMEN95F77WXSPPJHAS7AFG",
  "summary": "",
  "literal": "",
  "likely_intents": [
    {
      "reading": "Priya is waiting on something from you and wants it moving",
      "confidence": 0.5
    }
  ],
  "temperature": "tense",
  "priority": "must",
  "reply_needed": true,
  "actions": [],
  "related": [
    {
      "id": "MEM#01M4DMEKYGZ1BP0VW04MDZ7047",
      "text": "Send Priya the Q3 deck"
    }
  ],
  "cues": [
    {
      "phrase": "Per my last email",
      "meaning": "I already asked once"
    },
    {
      "phrase": "by today",
      "meaning": "They want it today"
    },
    {
      "phrase": "Thanks",
      "meaning": "Friendly"
    },
    {
      "phrase": "can you",
      "meaning": "They are asking you to do something"
    },
    {
      "phrase": "a question",
      "meaning": "They want an answer"
    }
  ],
  "needs_work": true,
  "sender_context_used": true,
  "sender_source": "signature",
  "source": "baseline",
  "refine": "failed",
  "reply_by": "2026-10-08T17:00:00-04:00",
  "suggest_reminder_minutes": 540,
  "speak": "Most likely Priya is waiting on something from you and wants it moving. Priya is your manager. It's urgent. Reply today at 5 PM. Related: you have Send Priya the Q3 deck open. Want a reminder before then?"
}
```

### 4. `decode_result()` — 2 ms ✅

```json
{
  "id": "INBOX#01M4DMEN95F77WXSPPJHAS7AFG",
  "summary": "",
  "actions": [],
  "refine": "failed",
  "speak": "I couldn't get more detail on that one. Most likely Priya is waiting on something from you and wants it moving."
}
```

### 5. `POST /inbox {"text": "Hi! Could you review the venue contract by Thursday?", "sender": "Jordy"}` → HTTP 201 ✅

```json
{
  "id": "INBOX#01M4DMEN9RS8A125D8A300F03R"
}
```

### 6. `POST /inbox {"text": "From: Jordan <jordan@example.com>\n\nFYI the parking garage is closed Monday."}` → HTTP 201 ✅

```json
{
  "id": "INBOX#01M4DMEN9S651GB5R681KAJ938"
}
```

### 7. `POST /inbox {"text": ""}` → HTTP 400 ✅

```json
{
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "text must be 1 to 4000 characters"
  }
}
```

### 8. `decode()` — 3 ms ✅

```json
{
  "id": "INBOX#01M4DMEN9S651GB5R681KAJ938",
  "summary": "",
  "literal": "",
  "likely_intents": [
    {
      "reading": "Jordan is letting you know; no action needed",
      "confidence": 0.5
    }
  ],
  "temperature": "neutral",
  "priority": "wait",
  "reply_needed": false,
  "actions": [],
  "related": [
    {
      "id": "MEM#01M4DMEKYGZ1BP0VW04MDZ7048",
      "text": "Reply to Jordan about the venue"
    }
  ],
  "cues": [
    {
      "phrase": "FYI",
      "meaning": "For information; no reply needed"
    }
  ],
  "needs_work": false,
  "sender_context_used": true,
  "sender_source": "header",
  "source": "baseline",
  "refine": "pending",
  "speak": "Most likely Jordan is letting you know; no action needed. Jordan is your teammate. No reply needed. Related: you have Reply to Jordan about the venue open."
}
```

### 9. `triage_inbox()` — 3 ms ✅

```json
{
  "items": [
    {
      "id": "INBOX#01M4DMEN95F77WXSPPJHAS7AFG",
      "sender": "Priya",
      "summary": "",
      "priority": "must",
      "reply_by": "2026-10-08T17:00:00-04:00"
    },
    {
      "id": "INBOX#01M4DMEN9RS8A125D8A300F03R",
      "sender": "Jordan",
      "summary": "",
      "priority": "must",
      "reply_by": "2026-10-08T17:00:00-04:00"
    },
    {
      "id": "INBOX#01M4DMEN9S651GB5R681KAJ938",
      "sender": "Jordan",
      "summary": "",
      "priority": "wait"
    }
  ],
  "pending": 0,
  "speak": "Two things need you. Priya is waiting on something, today. Jordan is asking you to do something, today. Jordan sent an update. It can wait."
}
```

### 10. `close_loop({"text": "the message from Priya"})` — 2 ms ✅

```json
{
  "closed": {
    "id": "INBOX#01M4DMEN95F77WXSPPJHAS7AFG",
    "text": "the message from Priya"
  },
  "speak": "Done. I marked the message from Priya as handled."
}
```

### 11. `triage_inbox()` — 1 ms ✅

```json
{
  "items": [
    {
      "id": "INBOX#01M4DMEN9RS8A125D8A300F03R",
      "sender": "Jordan",
      "summary": "",
      "priority": "must",
      "reply_by": "2026-10-08T17:00:00-04:00"
    },
    {
      "id": "INBOX#01M4DMEN9S651GB5R681KAJ938",
      "sender": "Jordan",
      "summary": "",
      "priority": "wait"
    }
  ],
  "pending": 0,
  "speak": "One thing needs you. Jordan is asking you to do something, today. Jordan sent an update. It can wait."
}
```

### 12. `recall({"query": "Q3 deck"})` — 2 ms ✅

```json
{
  "matches": [
    {
      "id": "PERSON#jordan",
      "text": "Jordan: teammate. Owns the Q3 deck design.",
      "kind": "person",
      "subject": "Jordan",
      "created_at": "2026-10-08T07:30:20-04:00",
      "resolution": "exact"
    },
    {
      "id": "MEM#01M4DMEKYGZ1BP0VW04MDZ7047",
      "text": "Send Priya the Q3 deck",
      "kind": "commitment",
      "subject": "Priya",
      "created_at": "2026-10-07T06:30:20-04:00",
      "due_at": "2026-10-09T07:30:20-04:00",
      "status": "open",
      "resolution": "exact"
    }
  ],
  "speak": "Jordan is your teammate. Owns the Q3 deck design. I have one more thing about that too."
}
```

**12 steps, 0 failed**

# Findings and bugs (running log)

Everything found while building and verifying the phases: bugs (fixed or open), spec gaps, and
decisions made without asking. Newest phase at the bottom. Status: **fixed** · **open** · **decision**
(made a call; review it) · **needs you** (blocked on access, money, or a choice only you can make).

## Phase 1–2 (found while verifying phase 2)

| # | Status | Finding |
|---|---|---|
| 1 | open | `speak` keeps the user's leading capital mid-sentence: "Three things are still open: Send Priya the Q3 deck, Book the dentist". Lower-casing blindly breaks names ("Priya called"), so it needs a proper-noun check against `PERSON#` names. Cosmetic; Alexa reads it the same. |
| 2 | open | `set_preference` speak uses only the last path segment: "Gentle is now 15." Fine for unique leaves, vague for `time.checkin_thresholds.*` (no unit) and `telegram.pushes.*`. |
| 3 | fixed | `ruff check .` flagged import order in `docs/diagrams/aws_architecture.py` (pre-existing). Fixed with `ruff --fix`. |
| 4 | decision | Verification proofs are produced by `scripts/prove.sh <steps.yaml>`: fresh temp DB, server on port 8765 with a static token, steps run over real Streamable HTTP, Markdown output. Your `.data/` DB is never touched. |

## Phase 3 — translator + Bedrock wrapper

| # | Status | Finding |
|---|---|---|
| 5 | fixed | **Tests would have broken on 2026-10-12.** `SQLiteStore` hid TTL'd items by wall-clock time while tests use a fixed clock (2026-10-05); 7-day `INBOX#` items would vanish once real time passed the TTL. The store now takes an injectable clock. |
| 6 | fixed | `SQLiteStore.get/query` don't return the TTL, so updating an `INBOX#` item would drop its expiry. The TTL is now also kept on the document and passed back on every update. |
| 7 | fixed | Inline refine (Telegram path) returned `refine: "pending"` inside `result` after a failure; the failed state is now written into both the item and its `result`. |
| 8 | fixed | Sign-offs on the same line as the message ("…today? Thanks, Priya") weren't detected as a signature; now searched at the end of the last lines. |
| 9 | fixed | A model reply with `reply_by` lacking a UTC offset would have mixed naive/aware times in triage sorting; validation now rejects it (refine → `failed`) and sorting compares datetimes. |
| 10 | open | `recall("Q3 deck")` ranks the person note "Jordan … Owns the Q3 deck design" above the commitment "Send Priya the Q3 deck": both hit the exact tier and ties go to the newest item (seed creates people last). Pre-existing phase-1 ordering. |
| 11 | open | `decode` relates every open commitment about the sender, so an FYI from Jordan mentions "Reply to Jordan about the venue". Matches the spec ("match sender or topic"); may be noisy. |
| 12 | open | Cosine is pure Python. Fine for a demo corpus; at the spec's ~2,000 × 1024 vectors it is ~0.3 s, over the 200 ms tier budget. Add numpy (spec §8 assumes it) before real use. |
| 13 | decision | Kept boto3 **Converse** (spec-locked, Nova-swappable) rather than the Anthropic SDK's Bedrock client. |
| 14 | fixed | Live Bedrock smoke test passes (2026-10-20, `aws login` profile `neurocare-admin`): `BEDROCK_LIVE=1 AWS_PROFILE=neurocare-admin uv run pytest -m live -s`. `BEDROCK_MODEL_ID` `us.anthropic.claude-haiku-4-5-20251001-v1:0` confirmed. See #19, #20. |
| 15 | needs you | I can't read or edit `.env.example` (blocked by permissions). Add `LLM_PROVIDER`, `BEDROCK_MODEL_ID`, `BEDROCK_EMBED_MODEL_ID`, `AWS_REGION` (documented in README "Environment"). |
| 16 | open | Rumination with `FakeEmbedder` is listed under phase 3 acceptance but `log_topic` is phase 4; tested there. |

## Phase 2 — manual Inspector re-run (2026-10-15)

| # | Status | Finding |
|---|---|---|
| 17 | open — **must fix** | `remember(due_at=...)` accepts only ISO 8601 (`memory.py:174`), so the voice model has to turn "in 30 minutes" into an absolute local time on its own. It doesn't know the profile time zone (seed is `America/New_York`; the user is in IST), so a wrong guess saves silently at the wrong time. Fix: add `due_in_minutes: int` to `remember`, resolved with the server clock; reject passing both. Also update the `due_at` description to "local ISO 8601 in the user's time zone; call `now_context` if unsure". Tests: relative due → `now + N`, both set → `INVALID_ARGUMENT`. |
| 18 | open | **No source for the user's time zone.** Every time calculation uses profile `timezone` (seed default `America/New_York`), but Alexa+ MCP `tools/call` carries only tool name + arguments; no documented device or time zone field, and the ASK Settings API needs a skill-request device ID. The server's own clock is useless in AWS. Plan: (a) log headers and `_meta` on one live Alexa+ call to see what arrives; (b) phase 6: capture `Intl.DateTimeFormat().resolvedOptions().timeZone` on the account-linking login page and save to the profile; (c) server instructions: if time zone never confirmed, ask "What city are you in?" then `set_preference key=timezone`; (d) `now_context` speak already states the local time, so the user can correct it. Don't rely on the voice model to infer it (same weakness as #17). |

## AWS setup + live Bedrock run (2026-10-20)

| # | Status | Finding |
|---|---|---|
| 19 | fixed | Credentials from `aws login` need `botocore[crt]`; without it boto3 raises `MissingDependencyException`. Dependency is now `boto3[crt]`. |
| 20 | fixed | **Live decode refine always failed.** Haiku 4.5 read the prose schema "likely_intents (1-3 of {reading, confidence})" as one object (`{"reading": 0.7, "confidence": 0.3}`); validation rejected it, so `refine: failed` and only the baseline was ever served. The system prompt now gives the exact JSON shape. Live test passed 3/3 after. Haiku latency ~3 s, inside the 5 s `LLM_TIMEOUT`. Follow-up idea: Converse `toolConfig` with a forced tool whose `inputSchema` is `DecodeRefine.model_json_schema()` would enforce shape server-side. |
| 21 | decision | Identity Center dropped from `docs/aws-setup.md`: it needs AWS Organizations, which moves a free-plan account to the paid plan and expires credits. Now an IAM user + `aws login` (short-lived, no keys on disk); `neurocare-agent` is an IAM role assumed from `neurocare-admin`. |

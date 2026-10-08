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
| 14 | needs you | Live Bedrock smoke test needs your AWS login: `BEDROCK_LIVE=1 AWS_PROFILE=neurocare-admin uv run pytest -m live -s`. Confirm `BEDROCK_MODEL_ID` (`us.anthropic.claude-haiku-4-5-20251001-v1:0`) matches your console. |
| 15 | needs you | I can't read or edit `.env.example` (blocked by permissions). Add `LLM_PROVIDER`, `BEDROCK_MODEL_ID`, `BEDROCK_EMBED_MODEL_ID`, `AWS_REGION` (documented in README "Environment"). |
| 16 | open | Rumination with `FakeEmbedder` is listed under phase 3 acceptance but `log_topic` is phase 4; tested there. |

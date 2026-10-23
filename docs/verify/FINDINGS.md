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
| 17 | fixed | `remember(due_at=...)` accepts only ISO 8601 (`memory.py:174`), so the voice model has to turn "in 30 minutes" into an absolute local time on its own. It doesn't know the profile time zone (seed is `America/New_York`; the user is in IST), so a wrong guess saves silently at the wrong time. Fix: add `due_in_minutes: int` to `remember`, resolved with the server clock; reject passing both. Also update the `due_at` description to "local ISO 8601 in the user's time zone; call `now_context` if unsure". Tests: relative due → `now + N`, both set → `INVALID_ARGUMENT`. | **Fixed:** `due_in_minutes` (1–43200) added, resolved as `now + N` with the server clock; both set, or set on a non-commitment → `INVALID_ARGUMENT`. `due_at` description sharpened; server instructions tell the model to pass relative times as `due_in_minutes`. Tests: `test_commitment_due_in_minutes_uses_server_clock`, `test_due_in_minutes_rejects_bad_input`, `test_remember_due_in_minutes_over_mcp`. #18 (time zone source) still open: `due_at` and bare dates still depend on the profile time zone.
| 18 | open | **No source for the user's time zone.** Every time calculation uses profile `timezone` (seed default `America/New_York`), but Alexa+ MCP `tools/call` carries only tool name + arguments; no documented device or time zone field, and the ASK Settings API needs a skill-request device ID. The server's own clock is useless in AWS. Plan: (a) log headers and `_meta` on one live Alexa+ call to see what arrives; (b) phase 6: capture `Intl.DateTimeFormat().resolvedOptions().timeZone` on the account-linking login page and save to the profile; (c) server instructions: if time zone never confirmed, ask "What city are you in?" then `set_preference key=timezone`; (d) `now_context` speak already states the local time, so the user can correct it. Don't rely on the voice model to infer it (same weakness as #17). |

## AWS setup + live Bedrock run (2026-10-20)

| # | Status | Finding |
|---|---|---|
| 19 | fixed | Credentials from `aws login` need `botocore[crt]`; without it boto3 raises `MissingDependencyException`. Dependency is now `boto3[crt]`. |
| 20 | fixed | **Live decode refine always failed.** Haiku 4.5 read the prose schema "likely_intents (1-3 of {reading, confidence})" as one object (`{"reading": 0.7, "confidence": 0.3}`); validation rejected it, so `refine: failed` and only the baseline was ever served. The system prompt now gives the exact JSON shape. Live test passed 3/3 after. Haiku latency ~3 s, inside the 5 s `LLM_TIMEOUT`. Follow-up idea: Converse `toolConfig` with a forced tool whose `inputSchema` is `DecodeRefine.model_json_schema()` would enforce shape server-side. |
| 21 | decision | Identity Center dropped from `docs/aws-setup.md`: it needs AWS Organizations, which moves a free-plan account to the paid plan and expires credits. Now an IAM user + `aws login` (short-lived, no keys on disk); `neurocare-agent` is an IAM role assumed from `neurocare-admin`. |

## Phase 4 — guardrail (2026-10-21)

| # | Status | Finding |
|---|---|---|
| 16 | fixed | Rumination with `FakeEmbedder` now tested (`test_rumination_by_embedding_cosine`). |
| 22 | fixed | **Async crisis re-check left the stored text in place.** `crisis.recheck` read the list of linked items *before* calling the guard; the tool attached its item while the guard was running, and the recheck then deleted from the stale empty list and overwrote the record. Now re-reads after the guard returns. Caught by `test_guard_timeout_rechecks_async_and_flags_next_call`. |
| 23 | open | A smaller window remains: an `attach` landing between that re-read and the hit marker write is lost (no conditional write in SQLite here). Close with a DynamoDB conditional update in phase 6. |
| 24 | open | Bedrock Guardrails content filters have no self-harm category (Hate, Insults, Sexual, Violence, Misconduct, Prompt attack). Spec §6 says "self-harm/violence filters"; use a **denied topic** for self-harm plus the Violence filter. Setup in `phase-4.md` step 5. |
| 25 | open | `speak` wording: `log_topic` echoes the topic verbatim ("I've noted that worried about the presentation tomorrow is on your mind"), and `remember` capitalisation ("I'll remember This deadline…") is the same open item from phase 3. |
| 26 | decision | `keep_going_once` / `snooze_15m` speak says "check-in" but also quiets rumination prompts. Kept short for voice. |
| 27 | fixed | Spec §11 lists `decompose` under phase 4 acceptance; the tool is phase 5. Its precheck (and `brain_dump`'s) lands there. **Fixed in phase 5:** both run the precheck first; tested directly, over MCP, and (brain dump) with an async guard hit that deletes the items. |
| 28 | needs you | Check the helpline numbers in `safety/crisis.py` (US/CA 988, GB 116 123, AU 13 11 14, IN 14416 Tele-MANAS) before the demo. |
| 29 | fixed | **Semantic rumination never fired on real Titan v2 vectors.** `COSINE_MIN = 0.80` was only exercised by `FakeEmbedder` (cosine ≈ 0.99 by construction). Live, the same worry reworded scored 0.44–0.70 ("the presentation tomorrow" / "is my presentation going to be ok" / "what if my presentation goes badly"); unrelated topics ≤ 0.22. Lowered to 0.40; spec §5 updated; the fake tests now use these phrasings. `test_live_rumination_by_embedding` detects on the 3rd (counts 1, 2, 3). |
| 30 | fixed | **Bedrock latency from a laptop in India exceeds both budgets.** *Re-measured from Lambda in us-east-1 (phase 6): `log_topic` with guard + embed runs in 330–380 ms server time (FINDINGS #57).* `ApplyGuardrail` ~900 ms cold / ~400–450 ms warm (budget 250 ms); Titan embed ~1200 ms cold / ~350 ms warm (budget 200 ms). Locally the guard always takes the async re-check path and `log_topic` falls back to Jaccard for the new topic. Mostly network round trip; re-measure from Lambda in us-east-1 in phase 6. If still over, consider a warm-up call on cold start. |
| 31 | decision | Live guardrail `neurocare-crisis` created by CLI in us-east-1: id `7dnkm5nfui1e`, version 1. Denied topic `Self-harm` (3 examples) + Violence input filter High; no output filters. "no point in being here at all" (not on the phrase list) → intervened; "Bring snacks to the offsite" → clear. Covered by `test_live_guard_intervenes_on_self_harm_only` and `test_live_remember_precheck_catches_self_harm`. |

## Phase 5 — task breakdown + daily plan (2026-10-23)

| # | Status | Finding |
|---|---|---|
| 32 | decision | Spec §11 says the `brain_dump` "baseline stores one item"; §5.6 says the baseline splits on commas, "and", and new lines. Followed §5.6 (plus semicolons). Over-splits ("salt and pepper") are fixed by the refine. |
| 33 | decision | **Live Haiku returned a 2-minute step 2** in a split (spec: 5–90). Rejecting the whole plan threw away a good breakdown, so a later step under 5 minutes is rounded up to 5. Steps over the cap, step 1 over 5, wrong counts, and non-verb starts still fail. |
| 34 | fixed | **Baseline `speak` read badly over HTTP.** (a) An overwhelm phrase passed as the goal gave "…what done looks like for you don't know where to start with your taxes"; `tasks.goal_phrase` now drops common lead-ins for speech (stored goal unchanged). (b) Splitting the 5-minute baseline gave "Do just the first 5 minutes of spend 5 minutes…"; a step ≤ 5 minutes now gets "first 2 minutes", and the decompose baseline gets "Write one line about what done looks like for …". Found by the phase 5 proof run. |
| 35 | decision | `plan_today` candidates: open `ITEM#`s, open commitments, and decoded messages not yet handled (spec says "undecoded inbox items"; an undecoded message has no priority to rank by, so read as "not handled"). `wait` items are never picked. `wrap_up` writes `carried` ids on tomorrow's `PLAN#`, and those rank first. |
| 36 | decision | New SK prefix `DUMP#` (1-day TTL): the raw brain-dump text and its item ids, for the refine to re-split. The refine reuses the baseline `ITEM#` ids in order, so a plan made in between still points at live items; extra baseline items are deleted. Spec §8 updated. |
| 37 | decision | `done_step` closes an open block and opens one for the next step with `planned_minutes` (spec "sized to its minutes"). With no open block it starts none. `check_in` levels still use the profile thresholds; `planned_minutes` is stored for later use. |
| 38 | fixed | `speech.join_spoken` gave "a, and b" for two items; now "a and b". Caught by the `wrap_up` speak test. |
| 39 | decision | `close_loop` also matches open brain-dump items, so "renew passport is done" marks the `ITEM#` done and `wrap_up` reports it. Not in spec §5.1; added there. |
| 40 | decision | One refine per task at a time: `split_step` while the `decompose` refine is pending returns the current (already 5-minute) step with "Still planning the steps". Avoids the two jobs racing on one task. |
| 41 | open | `plan_today` ranks by due date first, as spec §5.6 says, so any item with a due date (even next week) outranks a `must` message whose reply-by is today. Consider folding `reply_by` into the due date for messages. |
| 42 | decision | The brain-dump prompt asks for a bare date when only a day is named (parsed as 9 AM local) and to drop the day words from the item text. Before that, live Haiku gave midnight and kept "mom's birthday Sunday". |

## Phase 6 — DynamoDB, CDK, Lambda, account linking (2026-10-23)

| # | Status | Finding |
|---|---|---|
| 43 | decision | **No Mangum.** The SDK's `StreamableHTTPSessionManager.run()` can start only once per instance, and Mangum enters the ASGI lifespan on every invocation, so the second request would fail. `lambda_handler.LambdaASGI` keeps one event loop and one lifespan per container and runs each Function URL event on it (~150 lines, no new dependency). |
| 44 | decision | `PUBLIC_BASE_URL` (the OAuth resource URL) can't come from CloudFormation: the Function URL depends on the function, so passing it into the function's environment is a cycle. At init the handler calls `GetFunctionUrlConfig` on itself once. `public_base_url` in `cdk.json` overrides it (custom domain). |
| 45 | decision | PRM is served at `/.well-known/oauth-protected-resource/mcp` by the SDK (RFC 9728 §3.1, path-suffixed) and at the root path as the spec says. `WWW-Authenticate` points at the path-suffixed one (SDK default). |
| 46 | decision | Cognito access tokens have no `aud`, so the SDK's resource check (`validate_token_resource`) is off. The verifier checks RS256, `iss`, `token_use=access`, `client_id`, scope `neurocare/tools`, and `exp` (30 s leeway). An unknown `kid` refetches the JWKS at most every 5 minutes. |
| 47 | decision | Cognito has no "require PKCE" switch for this app client: it checks S256 when the client sends a `code_challenge` (Alexa+ does), but would also accept a flow without one. With a client secret also required, that is acceptable for the demo. **Live (2026-10-23):** with a challenge sent, a wrong `code_verifier` is rejected (`400 invalid_request`) — `scripts/oauth_token.py`. Real Alexa linking is not available in the hackathon (#59). |
| 48 | decision | The Lambda bundle is built on the host with `uv pip install --python-platform aarch64-manylinux_2_28 --only-binary :all:` (arm64 wheels; 79 MB unzipped), so `cdk synth` needs no Docker. Docker bundling stays as the fallback. |
| 49 | open | If the async self-invoke itself fails (throttling, IAM), the item stays `refine: pending`; `decode` then waits its 8 s and returns the baseline. Rare; logged. Could mark `failed` on invoke error. |
| 50 | decision | The `store` fixture runs every store-backed test on SQLite **and** moto DynamoDB (spec §11 test approach). Suite time 23 s → ~65 s. |
| 51 | decision | The DynamoDB table (PITR on) and the Cognito user pool are `RETAIN` on `cdk destroy`: they hold user data and the demo account. |
| 52 | decision | DynamoDB numbers come back as `Decimal`; the store converts them to `int`/`float` by their written form, and documents go through JSON on the way in, so both backends return the same shapes. `ttl` is the table's TTL attribute; reads also filter expired items, since DynamoDB deletes them up to days late. |
| 53 | decision | *Moot: no Alexa developer access in the hackathon (#59).* The add-on's redirect URIs exist only in the Alexa developer console. Add them to `infra/cdk.json` → `alexa_redirect_uris` and redeploy. The Inspector callback is registered meanwhile. |
| 54 | open | `decode` and `decode_result` wait up to 8 s for the Bedrock refine (phase 3, PR #9), well past Alexa's 500 ms. They are left out of `scripts/latency.py`. Check how Alexa+ behaves on a slow `decode` during step 6; if it times out, return the baseline at once on the Alexa path. |
| 55 | fixed | **First deploy served the wrong resource URL** (`http://127.0.0.1:8000/mcp` in PRM; the host check would also have rejected every request). Lambda imports `alexa_mcp_server.lambda_handler`, which ran the package `__init__`, which imported `server` (settings read at import) before the handler set `PUBLIC_BASE_URL`. The package `__init__` now loads `main`/`mcp` lazily; `test_handler_import_does_not_load_server_settings` guards it. Found by the live PRM check. |
| 56 | decision | *Moot for the hackathon (#59). Alexa+ docs list `WWW-Authenticate` in 401s as unsupported, and the organizer says it would break real linking — so the rename is harmless.* **Function URLs rename `WWW-Authenticate` on a 401** to `x-amzn-Remapped-www-authenticate` (API Gateway does the same; not configurable). The 401 and `resource_metadata` value are correct, but a client reading the standard header sees none. MCP clients fall back to probing `/.well-known/oauth-protected-resource[/mcp]`, which works. If Alexa+ needs the header: CloudFront in front of the URL with a viewer-response function that copies the header back (new URL; PUBLIC_BASE_URL via `cdk.json`). |
| 57 | decision | **Latency is measured on the server.** From India every call is ~700–800 ms round trip, even `ping` (new TLS connection to us-east-1 each time). Lambda `REPORT` durations, warm: Alexa-path tools p50 26 ms, max 67 ms (54 calls); `log_topic` (ApplyGuardrail + Titan embed) 330–380 ms. Cold start (init) 2.9–3.6 s: provisioned concurrency for the demo window (spec §12). |
| 58 | open | `decompose` goal "do my taxes" speaks "…what done looks like for do your taxes". `tasks.goal_phrase` turns "my" into "your" but keeps the leading verb. Cosmetic. |
| 59 | decision | **No real Alexa+ in the hackathon** (organizer, Discord 2026-10-19): entrants don't get the `alexa-ai` tools, so no add-on deploy or account linking; a simulated experience is the only way to demo; proactive notifications may be simulated; the demo video may use narration and shortened waits if what is shown is real. Also found (Alexa+ docs, 2026-10-23): real linking would need auth-server metadata with `code_challenge_methods_supported: ["S256"]` (Cognito's has none) and `client_credentials` in `grant_types_supported`; not pursued. Phase 6 step 6 is satisfied by the live OAuth proof (`scripts/oauth_token.py`). |

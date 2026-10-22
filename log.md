# Build log

Running status of the autonomous build through the spec phases (`docs/spec.md` §11).
Details per phase: `docs/verify/phase-N.md`. Every bug and decision: `docs/verify/FINDINGS.md`.

## 2026-10-21 — start here

1. **Phase 3 manual verification (you).** All sign-off items in `docs/verify/phase-3.md`
   (1, 2, 3a–h); boxes are left for you to tick. Run against `main`, not the phase 4 branch
   (its crisis precheck changes `decode`):
   ```bash
   git worktree add ../phase3-verify main && cd ../phase3-verify && uv sync
   aws login --profile neurocare-admin            # if the session expired
   uv run alexa-mcp-seed --reset
   LLM_PROVIDER=bedrock AWS_PROFILE=neurocare-admin ALLOW_STATIC_TOKEN=true AUTH_TOKEN=devtoken uv run alexa-mcp-server
   uv run alexa-mcp-inbox-token                   # another terminal; for steps d–e
   ```
   Before step b: `set_preference key=timezone value=Asia/Kolkata` (seed is `America/New_York`).
   Step 2 prints two Titan cosine scores: check them against decision #5 (0.5 threshold).
   Afterwards: `git worktree remove ../phase3-verify`.
2. **Then FINDINGS #17** (must fix): `remember(due_in_minutes=...)`.
3. **Then finish phase 4** on `feat/phase-4-guardrail` (uncommitted work, now on top of `main`):
   register tools in `server.py`, crisis-first wrapper, tests, `docs/verify/phase-4.md`, proof, PR.

## 2026-10-20

### AWS set up; live Bedrock passes — merged (PR #8)

- No IAM Identity Center: it needs AWS Organizations, which ends the free plan and expires credits.
  Now an IAM user (`navin-admin`, no access keys) signed in with `aws login`; profile
  `neurocare-admin`, region `us-east-1`. `docs/aws-setup.md` rewritten. MFA skipped by choice.
- `boto3[crt]` added (needed for `aws login` credentials).
- **Bug:** every live decode refine failed. Haiku read the prose schema as a single
  `likely_intents` object; validation rejected it. Prompt now gives the exact JSON shape.
  Live tests 2/2, three runs. FINDINGS #14 closed, #19–#21 added.
- `.claude/settings.json` asks before any Bash command using the `neurocare-admin` profile.
- Agent profile (`neurocare-agent` role) and AWS plugin deferred to phase 6.
- Phase 4 work moved onto `feat/phase-4-guardrail` (fast-forwarded to `main`), still uncommitted.

### Needs you (still open)

- `.env.example`: add `LLM_PROVIDER`, `BEDROCK_MODEL_ID`, `BEDROCK_EMBED_MODEL_ID`,
  `BEDROCK_GUARDRAIL_ID`, `BEDROCK_GUARDRAIL_VERSION`, `AWS_REGION`.
- Create a Bedrock Guardrail (self-harm / violence filters) for phase 4's crisis check.
- Check crisis helpline numbers in `src/alexa_mcp_server/safety/crisis.py` before the demo.

## 2026-10-15

### Phase 2 manual re-run (Inspector, by you) — pass

- Steps a–p of `docs/verify/phase-2.md` §4 all pass. Differences from the doc were timing/setup only:
  elapsed drift between calls, 5-minute rounding in `speak`, and profile time zone (seed
  `America/New_York` vs your IST; switched with `set_preference key=timezone`).
- Seed sets `time.end_of_day` to `18:00`, not null; restore that in step g.
- New findings: #17 (`remember` needs `due_in_minutes`, must fix), #18 (no source for the user's
  time zone).

## 2026-10-08

### Merged to `main`

- **Phase 2 — sense of time** (PR #5, doc fix #6). Live HTTP proof: 17/17 steps pass;
  unauthenticated request → 401.
- **Phase 3 — translator + Bedrock wrapper** (PR #7). `decode`, `decode_result`, `triage_inbox`,
  `POST /inbox` with hashed personal inbox tokens, fast-first background refine, embedding tier
  with lazy backfill. `uv run pytest`: 135 passed, 2 skipped (live Bedrock). Live proof: 12/12.
- **Proof tooling:** `scripts/prove.sh <steps.yaml>` — fresh seeded temp DB, server on port 8765,
  steps over Streamable HTTP, Markdown proof out. Your `.data/` DB is never touched.

### Bugs fixed

- Tests would have broken on 2026-10-12: the SQLite TTL used wall-clock time while tests use a fixed
  clock. Clock is now injectable.
- Updating an `INBOX#` item dropped its 7-day TTL.
- Inline refine returned `refine: "pending"` after a failure.
- Same-line sign-off ("…today? Thanks, Priya") not detected as the sender.
- Model `reply_by` without a UTC offset was accepted; now rejected (refine → `failed`).
- Pre-existing import-order lint error in `docs/diagrams`.

### Open (see FINDINGS)

- `recall("Q3 deck")` ranks Jordan's person note above the Priya commitment (newest-first tie-break).
- Leading capital mid-sentence in `speak` ("open: Send Priya…").
- Pure-Python cosine is too slow for the 200 ms budget at ~2,000 vectors; add numpy.
- **Must fix (FINDINGS #17):** `remember` needs `due_in_minutes` — voice model can't reliably turn
  "in 30 minutes" into ISO in the profile time zone.
- **FINDINGS #18:** no source for the user's time zone; log a live Alexa+ call, then capture it on the
  account-linking page (phase 6) plus a voice fallback.

### In progress — phase 4, guardrail (branch `feat/phase-4-guardrail`, not committed yet)

Written:
- `safety/crisis.py`: phrase list → Bedrock Guardrails (250 ms budget) → background re-check on
  timeout; an async hit deletes the stored items and flags the next call. Resources for US, CA, GB,
  AU, IN, plus a fallback.
- `pillars/overrides.py`: `override` (four tokens); `check_in` now honours active overrides.
- `pillars/guardrail.py`: `log_topic` (rumination: Jaccard ≥ 0.5 or cosine ≥ 0.80), `check_hyperfocus`,
  `log_need`.
- Crisis precheck wired into `remember`, `decode`, `triage_inbox`.

Left:
- Register the new tools in `server.py`; wrap every tool so a pending crisis result comes first.
- Tests, live proof, `docs/verify/phase-4.md`, PR, merge.

### Next

- Phase 5 — task breakdown + daily plan.
- Phase 6 / 6b — offline parts only: DynamoDB store (moto), Cognito JWT + PRM, Lambda handler,
  CDK synth, Telegram with a fake Bot API, email parsing.

### Needs you

1. Live Bedrock test: `BEDROCK_LIVE=1 AWS_PROFILE=neurocare-admin uv run pytest -m live -s`; confirm
   `BEDROCK_MODEL_ID` (`us.anthropic.claude-haiku-4-5-20251001-v1:0`) matches your console.
2. `.env.example` is blocked by my permissions: add `LLM_PROVIDER`, `BEDROCK_MODEL_ID`,
   `BEDROCK_EMBED_MODEL_ID`, `BEDROCK_GUARDRAIL_ID`, `BEDROCK_GUARDRAIL_VERSION`, `AWS_REGION`.
3. Check the crisis helpline numbers in `src/alexa_mcp_server/safety/crisis.py` before the demo.
4. Later: `cdk deploy`, Cognito account linking with Alexa, Telegram bot token.


### phase4 

branch - feat/phase-4-guardrail
# Phase 6a — verification steps

Checks phase 6a of `docs/spec.md` §11: the Alexa simulator (§5.9).
**Done when:**
- The turn loop works with scripted model replies against the in-process MCP server:
  - tools come from `tools/list`;
  - the system prompt includes the server's `instructions`;
  - results are fed back to the model;
  - at most 5 tool rounds.
- A crisis result is spoken word for word, with no model rewrite.
- A 401 gives the link prompt.
- `set_reminder` fires a chime and the yellow ring at its time.
- OAuth:
  - the callback rejects a wrong or reused `state`;
  - the authorize request sends PKCE S256;
  - an expired access token is refreshed;
  - unlink clears the tokens;
  - the refresh token never reaches the browser.
- The deployed simulator links the demo account through Cognito and runs the "One day" steps that
  don't need Telegram, live, by voice in Chrome.

Branch `feat/phase-6a-simulator`, stacked on `docs/spec-alexa-simulator` (PR #14), which is stacked
on `feat/phase-6-aws` (PR #13). Takes about 15 minutes.

Simulator: **https://yxsw3xdvj2op5aqmtd3flcc4la0ntjzf.lambda-url.us-east-1.on.aws/**

---

## 1. Automated checks

```bash
uv run pytest -q                    # expect: 497 passed, 9 skipped
(cd infra && uv run pytest -q)      # expect: 5 passed
uv run ruff check . && uv run ruff format --check .
```

| Acceptance item | Test (`tests/test_sim.py`) |
|---|---|
| Tools from `tools/list`, system prompt from `instructions` | `test_tools_and_instructions_come_from_the_server` (29 server tools + `set_reminder`) |
| Results fed back to the model | `test_tool_call_result_is_fed_back` |
| ≤ 5 tool rounds | `test_tool_rounds_are_capped` |
| Crisis spoken verbatim, no second model call | `test_crisis_result_is_spoken_verbatim_without_the_model` (real crisis precheck in the server) |
| 401 / no token → link prompt, no model call | `test_unlinked_user_gets_the_link_prompt`, `test_app_link_flow_and_turn` |
| `set_reminder` due at its time; no duplicate on "yes please" | `test_set_reminder_fires_at_the_time`, `test_app_reminder_due_and_ack` |
| PKCE S256, `state`, `resource`, scopes | `test_start_link_sends_pkce_s256_and_resource` |
| Wrong / reused `state` rejected | `test_callback_rejects_wrong_or_reused_state` |
| Refresh on expiry; failed refresh → link again | `test_expired_access_token_is_refreshed`, `test_failed_refresh_requires_linking_again` |
| Unlink; cookie `HttpOnly; Secure; SameSite=Lax`; refresh token never in a response | `test_app_link_flow_and_turn` |
| History capped at 10 turns | `test_history_is_capped` |
| Simulator Lambda never starts the server | `test_simulator_handler_never_starts_the_server` (FINDINGS #60) |
| Stack: simulator function, table, callback URL | `infra/tests/test_stack.py::test_simulator_is_wired_without_cycles` |

## 2. Link (Chrome)

Open the simulator → **Link NeuroCare** → Cognito sign-in. Use the demo user `navintheboss1998@gmail.com`;
the password is in the scratchpad file from phase 6, and you can reset it in the Cognito console.

**Expect:** back on the page with "NeuroCare is linked"; green dot.

## 3. Voice: the "One day" arc (no Telegram)

Re-seed first so the times are fresh:

```bash
AWS_PROFILE=neurocare-deployer AWS_REGION=us-east-1 STORE=dynamo DEMO_USER_ID=<sub> uv run alexa-mcp-seed --reset
```

Hold the mic button (or space) and say each line. Open **Dev panel** to see the tool calls.

| # | Say | Expected tool | Expected reply (gist) |
|---|---|---|---|
| a | "What was I doing?" | `what_was_i_doing` | Budget email, started about 40 minutes ago, three open things |
| b | "Plan my day, my energy is low" | `plan_today` (energy) | One priority: Send Priya the Q3 deck |
| c | "I don't know where to start with my taxes" | `decompose` | A 5-minute first step |
| d | "This one's too big" | `split_step` | A smaller step |
| e | "How long have I been at this?" | `check_in` | Elapsed time, maybe a break offer |
| f | "I keep worrying about the presentation tomorrow" (three times) | `log_topic` | The third time: a gentle redirect |
| g | "Remind me in one minute to drink water" | `set_reminder` | "Okay, I'll remind you at …"; a minute later: chime, yellow bar, reminder spoken |
| h | "Wrap up for today" | `wrap_up` | What's done, what rolled to tomorrow |
| i | Type "I want to end my life" | `remember`/`log_topic` → crisis | Only the 988 message; resources shown on screen |
| j | **Unlink**, then "What was I doing?" | none | "To use NeuroCare, link your account…" |

## Decisions to review

1. A separate Lambda and table; the MCP server is unchanged (spec §5.9).
2. The model is Haiku 4.5 (FINDINGS #65); `sim_model_id` in `cdk.json` switches it.
3. Client and URLs are read at init to avoid a CloudFormation cycle (FINDINGS #63).
4. Unlinked visitors never reach Bedrock (FINDINGS #64).
5. Reminder dedupe for "yes please" (FINDINGS #62).
6. The browser polls `/sim/state` every 10 s for due reminders, so they fire up to 10 s late.

## Known gaps

- The deployer role can't read the simulator's logs (FINDINGS #61).
- Speech recognition works in Chrome only; typed input works everywhere.
- Cold start for both Lambdas: the first turn after idle takes about 7 s.

## Sign-off

- [ ] 1 tests + lint
- [ ] 2 link in Chrome
- [ ] 3 voice arc (a–j)

---

## Proof (live, 2026-10-23, browserless link + turns, `Asia/Kolkata`)

```
state before: {'linked': False, 'can_link': True}
link → 302 neurocare-demo-nrc.auth.us-east-1.amazoncognito.com | method ['S256'] | redirect …/sim/callback
sign-in → 302 …/sim/callback
callback → 302 /?linked=1
state after: True

> What was I doing?                [7065 ms total, model 1464 ms] what_was_i_doing(346ms)
  You were working on the budget email. You started about two hours and ten minutes ago. Three things are still open: …
> Plan my day, my energy is low    [2388 ms, model 1538 ms] plan_today(79ms)
  Three things open. I suggest one: Send Priya the Q3 deck. Want to start with that?
> What needs me?                   [2247 ms, model 1345 ms] triage_inbox(40ms)
  Nothing needs you right now.
> How long have I been at this?    [2386 ms, model 1508 ms] check_in(57ms)
  You started the budget email about two hours and ten minutes ago. Want a 5-minute break, or keep going?
> I keep worrying about the presentation tomorrow   [3571 ms, model 2200 ms] log_topic(575ms)
  Okay. I've noted that worrying about the presentation tomorrow is on your mind. …
> Wrap up for today                [2235 ms, model 1334 ms] wrap_up(76ms)
  Send Priya the Q3 deck moved to tomorrow. Stopped the budget email after about two hours and ten minutes.
```

First turn: both Lambdas starting cold.

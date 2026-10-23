# Phase 6 — verification steps

Checks phase 6 of `docs/spec.md` §11: DynamoDB store, CDK, Lambda, and account linking.
**Done when:**
- The same test suite passes against moto-backed DynamoDB.
- `cdk deploy` succeeds.
- PRM is served at `/.well-known/oauth-protected-resource`.
- A 401 carries `WWW-Authenticate` with `resource_metadata`.
- Expired and wrong-client JWTs are rejected.
- Alexa+ account linking completes against Cognito (PKCE S256, refresh token issued).
- Alexa-path tools take < 500 ms round trip on a warm Lambda.

Branch `feat/phase-6-aws`. Step 1 is automated (5 minutes). Steps 2–6 deploy to your account and need
`aws login --profile neurocare-admin` (about 45 minutes, plus the Alexa console).

---

## 0. Setup

```bash
cd ~/dev/devpost_hackathon
git fetch && git checkout feat/phase-6-aws && git pull
uv sync && (cd infra && uv sync)
```

## 1. Automated checks (acceptance)

```bash
uv run pytest -q                    # expect: 470 passed, 9 skipped (live Bedrock)
(cd infra && uv run pytest -q)      # expect: 4 passed (CDK synth assertions)
uv run ruff check . && uv run ruff format --check .
(cd infra && AWS_PROFILE=neurocare-admin npx aws-cdk@2.1146.1 synth -q)   # builds the Lambda bundle too
```

| Acceptance item (spec §11) | Test |
|---|---|
| Same suite on moto DynamoDB | `conftest.py` `store` fixture is parameterized `[sqlite]` / `[dynamo]`: every pillar, MCP, and store test runs on both |
| … store semantics (paging past 1 MB, number types, TTL filtering) | `test_store.py::test_query_pages_through_large_partitions`, `test_values_round_trip`, `test_expired_items_are_hidden` (both backends) |
| PRM at `/.well-known/oauth-protected-resource` (and `/…/mcp`) | `test_lambda.py::test_protected_resource_metadata_is_served` |
| 401 has `WWW-Authenticate` with `resource_metadata` | `test_unauthorized_carries_www_authenticate` (no token, garbage, expired, wrong client) |
| Expired / wrong-client JWTs rejected | `test_bad_tokens_are_rejected` (expired, wrong client, wrong issuer, ID token, missing scope, no `sub`, wrong key, unknown `kid`), `test_garbage_and_hs256_are_rejected` |
| JWT `sub` becomes the user | `test_valid_token_calls_tool_as_jwt_subject` (over the Lambda adapter, two warm requests) |
| Stateless HTTP + JSON responses on Lambda | `test_real_server_over_the_adapter` (29 tools), `test_wrong_host_is_rejected` |
| Async self-invoke refine | `test_lambda_refiner_self_invokes_async`, `test_handler_routes_refine_events` |
| CDK: table, Cognito client, Lambda env (no static token), IAM | `infra/tests/test_stack.py` |

## 2. Deploy (you)

Follow [`infra/README.md`](../../infra/README.md): bootstrap, `deploy`, demo user, seed with the
user's `sub`, read the client secret. Note the outputs.

**Expect:** `deploy` finishes with `McpUrl`, `UserPoolId`, `ClientId`, `AuthorizeUrl`, `TokenUrl`, `Scopes`.

## 3. Endpoint checks

```bash
URL=<FunctionUrl without the trailing slash>
curl -s $URL/.well-known/oauth-protected-resource | jq
curl -s $URL/.well-known/oauth-protected-resource/mcp | jq
curl -si -X POST $URL/mcp -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep -i -E '^HTTP|www-authenticate'
```

| # | Expected |
|---|---|
| a | Both metadata URLs: `resource` = `$URL/mcp`, `authorization_servers` = `["https://cognito-idp.us-east-1.amazonaws.com/<pool>"]`; the root one also has `scopes_supported: ["neurocare/tools"]` |
| b | `HTTP/1.1 401`, `www-authenticate: Bearer error="invalid_token", …, resource_metadata="$URL/.well-known/oauth-protected-resource/mcp"` |
| c | `curl -s https://cognito-idp.us-east-1.amazonaws.com/<pool>/.well-known/openid-configuration \| jq .authorization_endpoint` is the hosted UI `/oauth2/authorize` |

## 4. OAuth through the MCP Inspector

```bash
npx @modelcontextprotocol/inspector
```

Transport Streamable HTTP, URL = `McpUrl`. Open **Authentication**: client ID = `ClientId`, client
secret from step 2, scope `openid email neurocare/tools`. **Connect** → Cognito hosted UI → sign in
as the demo user.

| # | Expected |
|---|---|
| d | Back in the Inspector, connected; **List Tools → 29** |
| e | `what_was_i_doing` returns the seeded context (proves `sub` → seeded partition on DynamoDB) |
| f | `decompose` goal=`do my taxes` returns the baseline at once; ~5 s later `next_step` shows a model step (`refine: done`) → the async self-invoke ran Bedrock. CloudWatch `/aws/lambda/neurocare-mcp` shows a second invocation with no HTTP request |
| g | The token response includes a `refresh_token` (Inspector's auth debug view, or the Alexa link in step 6) |
| h | Edit the bearer token by one character → 401 |

## 5. Latency (warm Lambda)

Get an access token from the Inspector (Authentication panel) or without a browser
(`scripts/oauth_token.py`, env vars in its docstring), then:

```bash
TOKEN=<access token> uv run python scripts/latency.py <McpUrl> --rounds 5
```

**Expect:** every row ✅ (max ≤ 500 ms). From far from us-east-1 the round trip is mostly network;
then read the server time from the Lambda `REPORT` lines in CloudWatch (FINDINGS #57).

FINDINGS #30 (Bedrock budgets measured from India): from the Inspector, call `log_topic` with a new
worry and note the round trip. It runs `ApplyGuardrail` (250 ms budget) and a Titan embed (200 ms);
inside us-east-1 both should fit, so the total stays well under 500 ms.

## 6. Alexa+ account linking — not available in the hackathon

The organizer confirmed (2026-10-19) that entrants get no `alexa-ai` tools and must demo with a
simulated experience (FINDINGS #59). The account-linking item is covered by the live OAuth run in
the Proof below: Cognito hosted sign-in, auth code + PKCE S256 (wrong verifier rejected), refresh
token issued, and the token accepted by the deployed server as the seeded user.

## Decisions to review

1. **Own Lambda adapter, not Mangum** (FINDINGS #43). The SDK's session manager starts only once per
   instance; Mangum enters the lifespan on every request. `lambda_handler.LambdaASGI` keeps one event
   loop and one lifespan per container.
2. **`PUBLIC_BASE_URL` from the function's own URL** at init (`GetFunctionUrlConfig`), since
   CloudFormation can't pass the URL into the function's environment without a cycle (FINDINGS #44).
3. **PRM at two paths**: the SDK serves `/.well-known/oauth-protected-resource/mcp` (RFC 9728 §3.1)
   and `WWW-Authenticate` points there; the root path is added per spec (FINDINGS #45).
4. **Token checks** (FINDINGS #46): RS256 only; `iss` = the pool; `token_use` = `access`;
   `client_id` = the app client; scope `neurocare/tools`; `exp` with 30 s leeway. Cognito access
   tokens carry no `aud`, so the SDK's resource check is off and `client_id` stands in for it.
5. **Confidential client with a secret** (as `docs/aws-setup.md` §6 says). PKCE: see FINDINGS #47.
6. **Bundle built with `uv`** for Linux arm64, no Docker (FINDINGS #48). Docker bundling is the fallback.
7. **Both backends in every test** via moto (FINDINGS #50). Suite time 23 s → ~65 s.
8. **Table and user pool are retained** on `cdk destroy` (FINDINGS #51).

## Known gaps

- Phase 6b items (Telegram secrets, Scheduler rule, SES) are not in the stack yet.
- No provisioned concurrency: cold starts are outside the 500 ms budget. Spec §12: set it to 1 for
  the demo and judging windows (needs an alias; not done).
- FINDINGS #23 stays open: the store has no conditional write.
- `decode` waits up to 8 s for Bedrock (phase 3, PR #9), so it is not in the latency check (FINDINGS #54).

## Sign-off

- [ ] 1 tests + lint + synth
- [ ] 2 deploy
- [ ] 3 endpoint checks (a–c)
- [ ] 4 OAuth through the Inspector (d–h)
- [ ] 5 latency < 500 ms warm
- [ ] 6 account linking via the OAuth proof (real Alexa not available, FINDINGS #59)

---

## Proof (live run, 2026-10-23, `neurocare-deployer` profile)

Stack `NeuroCare` deployed (90 s; redeployed once for FINDINGS #55). Demo user created, seeded with
its `sub` (2 people, 5 memories, 1 block).

**Step 3 — endpoints**
- `GET /.well-known/oauth-protected-resource` → 200, `resource` = `https://kjkzytusgckzqo4boxgyjeq7we0khkkx.lambda-url.us-east-1.on.aws/mcp`, `authorization_servers` = the pool issuer, `scopes_supported: ["neurocare/tools"]`. Same from `/…/mcp`.
- `POST /mcp` without a token → `401`, body `invalid_token`, but the challenge arrives as
  `x-amzn-Remapped-www-authenticate: Bearer error="invalid_token", …, resource_metadata="…/.well-known/oauth-protected-resource/mcp"` (FINDINGS #56).

**Step 4 — OAuth (`scripts/oauth_token.py`, no browser) and tools**
```
sign-in → 302
token with a wrong PKCE verifier → 400 invalid_request
token → 200; refresh_token issued: True; scope: neurocare/tools openid email
refresh → 200; new access token: True
```
```
tools/list 200 29 tools
what_was_i_doing: You were working on the budget email. You started about 40 minutes ago. Three things are still open: …
decompose: baseline pending | First step: Spend 5 minutes writing down what done looks like for do your taxes. …
next_step after 8s: refine done remaining 10 | Next: Put last year's tax return on the desk. About 2 minutes.
tampered token -> 401
```

**Step 5 — latency.** Client round trip from India 700–816 ms for every tool, `ping` included
(network). Server time from Lambda `REPORT` lines, warm, 54 calls: **p50 26 ms, p95 48 ms, max 67 ms**.
`log_topic` (guard + embed): 381 / 332 ms. Cold init 2.9–3.6 s (FINDINGS #57).

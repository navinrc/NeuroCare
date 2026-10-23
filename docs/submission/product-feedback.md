# Product feedback

## Alexa+ MCP add-ons (docs: MCP toolkit, account linking, authentication)

- **Used for:** the target platform. The server follows the MCP toolkit docs: Streamable HTTP,
  tool descriptions and server instructions as the only levers, a `speak` field, and the
  < 500 ms budget.
- **Worked well:** the docs are clear that Alexa+ keeps no tool state and that only the
  authorization code grant is supported. Those two facts shaped the whole design: server-side
  state, and "fast first, refine later".
- **Needs work:**
  - Entrants couldn't use the `alexa-ai` CLI, so no add-on could be deployed or linked. We
    learned this from the organizers on Discord, after building account linking.
  - The account-linking page points to the "Alexa+ Developer Hub" for the redirect URIs but
    doesn't list them.
  - The authentication page requires `client_credentials` in `grant_types_supported` while
    calling the service tier optional for public servers.
  - The 401 / `WWW-Authenticate` guidance is only stated as "not supported".
- **Onboarding:** reading was fine; building was blind. We built a simulator to see our server
  "in Alexa".
- **Again?** Yes, once the tools are open to developers.

## Model Context Protocol Python SDK (`mcp` v2, `MCPServer`)

- **Used for:** the server (tools, a resource, instructions, `custom_route` for `/inbox`,
  bearer-token auth with `TokenVerifier`, Protected Resource Metadata) and the simulator's MCP
  client (`mcp.Client`).
- **Worked well:**
  - In-process testing with `Client(server)`: a full MCP round trip in unit tests with no network.
  - `stateless_http=True, json_response=True` is exactly what Lambda needs.
  - The auth middleware gives RFC 9728 metadata and `WWW-Authenticate` with `resource_metadata`
    for free.
- **Needs work:**
  - `StreamableHTTPSessionManager.run()` can start only once per instance, so the common
    Lambda adapter (Mangum) breaks on the second request. We wrote our own adapter.
  - Metadata is served only at the path-suffixed URL, not at the root.
  - The 2.x `validate_token_resource` deprecation warning fires for verifiers that check the
    audience themselves.
  - A 401 surfaces on the client as a nested `ExceptionGroup` → `MCPError("Server returned an
    error response")`, with no status code. We read it with an httpx response hook.
- **Again?** Yes.

## Amazon Bedrock — Claude Haiku 4.5 (Converse), Titan Text Embeddings v2, Guardrails

- **Used for:**
  - Haiku 4.5 refines every language task (message decoding, task breakdown, brain-dump
    splitting) and is the simulator's tool-using model.
  - Titan v2 drives semantic recall and rumination detection.
  - `ApplyGuardrail` (a self-harm denied topic plus the Violence filter) is the second layer of
    the crisis check.
- **Worked well:**
  - Converse tool use with Haiku 4.5 is fast: 1.3–2.2 s per simulator turn, and it picks the
    right tool from 30 almost every time.
  - The cross-region inference profile just works.
  - `ApplyGuardrail` on input alone is a clean pattern for a crisis precheck.
- **Needs work:**
  - Guardrails content filters have no self-harm category; we used a denied topic.
  - Haiku read a prose schema ("1–3 of {reading, confidence}") as one object until we gave a
    JSON example.
  - Titan cosine scores for reworded worries were 0.44–0.70, well below the 0.8 we assumed; we
    tuned to 0.40 from live data.
  - From India, `ApplyGuardrail` and Titan took 400–1200 ms. From Lambda in us-east-1 the whole
    `log_topic` call (guard + embed) is 330–380 ms.
- **Again?** Yes.

## AWS Lambda + Function URLs

- **Used for:** the MCP server, plus a second function for the simulator. arm64, Python 3.13,
  stateless. Language tasks refine through async self-invocation (`InvocationType=Event`).
- **Worked well:**
  - Function URLs remove API Gateway entirely.
  - Warm latency is excellent (26 ms median server time).
  - Async self-invoke is a simple background-job queue.
- **Needs work:**
  - A 401's `WWW-Authenticate` header is renamed to `x-amzn-Remapped-www-authenticate` and that
    can't be configured. It breaks OAuth discovery for standard MCP clients.
  - The Function URL can't be passed to the function's own environment without a CloudFormation
    cycle; we call `GetFunctionUrlConfig` at init.
  - Cold starts of 2.9–3.6 s for a Python MCP stack.
- **Again?** Yes.

## Amazon DynamoDB

- **Used for:** a single-table design. The partition key is the user; sort-key prefixes cover
  memory, people, blocks, tasks, inbox, plans, topics, needs, and overrides. TTL handles
  short-lived items; a separate table holds simulator sessions.
- **Worked well:**
  - The single-table design mapped 1:1 onto our store interface.
  - TTL handles all the "forget after 7 days" rules.
  - moto made it testable offline, so our whole suite runs on both SQLite and DynamoDB.
- **Needs work:**
  - Numbers come back as `Decimal`, which every app has to undo.
  - TTL deletion is lazy, so reads still have to filter expired items.
- **Again?** Yes.

## Amazon Cognito (user pool, hosted UI, resource server)

- **Used for:** OAuth 2.1 account linking: auth code + PKCE S256, refresh tokens, the custom scope
  `neurocare/tools`, and `sub` as the user id.
- **Worked well:** the hosted UI plus a confidential client took about 20 lines of CDK, and a
  wrong PKCE verifier is rejected.
- **Needs work:**
  - Discovery metadata (`openid-configuration`) has no `code_challenge_methods_supported` and no
    `grant_types_supported`, and `/.well-known/oauth-authorization-server` returns 400. Alexa+
    requires S256 in that metadata, so Cognito can't be used directly.
  - There's no "require PKCE" switch.
  - Access tokens carry no `aud`.
  - `client_credentials` can't share a client with the auth code grant.
- **Again?** For simple OAuth, yes. For MCP authorization, only behind a small metadata proxy.

## AWS CDK (Python)

- **Used for:** the whole stack: tables, both Lambdas and their URLs, Cognito, and IAM. Python
  wheels for Linux arm64 are built locally with `uv`, so no Docker is needed.
- **Worked well:**
  - `cdk diff` before every deploy.
  - Assertions-based synth tests.
  - Deploys take 25–90 s.
- **Needs work:** cross-resource cycles (a Cognito client callback that needs a Lambda URL that
  needs the client id) need runtime lookups to break.
- **Again?** Yes.

## Other tools

- **uv:** dependency management, and cross-platform Lambda bundles
  (`--python-platform aarch64-manylinux_2_28`) without Docker. Excellent.
- **moto:** a DynamoDB mock for the whole test suite. It made "same tests on both backends"
  cheap.
- **MCP Inspector:** manual tool checks in every phase.
- **Claude Code:** pair-programmed the build phase by phase with a verification doc per phase.

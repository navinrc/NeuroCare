# Friction log

Severity: **High** blocks the goal · **Medium** costs hours or needs a workaround · **Low** an annoyance.

---

### 1. No way to deploy or link an Alexa+ add-on as an entrant — High

- **Task:** see our MCP server running in Alexa+, with account linking.
- **Steps:** built Cognito account linking per the MCP toolkit account-linking docs, then went to
  configure it. The docs say to run `alexa-ai configure-account-linking`.
- **Expected:** a CLI or console page to register the add-on and test it on a device.
- **Actual:** the CLI isn't available to entrants (organizer, Discord). The only option is a
  simulated experience.
- **Workaround:** built an Echo Show–style simulator that is a real MCP client: real OAuth, the
  server's own instructions and tools, Bedrock tool use.
- **Suggestion:** give hackathon entrants a sandbox add-on stage or a hosted MCP test client, and
  say up front on the hackathon page that real deployment isn't possible.

### 2. Cognito metadata doesn't meet Alexa+'s account-linking requirements — High

- **Task:** use Cognito as the authorization server for an Alexa+ MCP add-on.
- **Steps:** deployed the user pool and app client, then read the Alexa+ authentication docs and
  queried Cognito's metadata.
- **Expected:** the metadata advertises `code_challenge_methods_supported: ["S256"]` and
  `grant_types_supported`, which Alexa+ says it checks at deploy.
- **Actual:**
  - `…/.well-known/openid-configuration` has neither field.
  - `…/.well-known/oauth-authorization-server` returns 400.
  - `client_credentials` can't share a client with the auth code grant.
- **Workaround (designed, not needed for the hackathon):** serve
  `/.well-known/oauth-authorization-server` from our Lambda, pointing at Cognito's endpoints.
- **Suggestion:** add S256 and the grant types to Cognito's metadata and serve RFC 8414 metadata;
  or publish an Alexa+ guide for Cognito specifically, since both are AWS.

### 3. Lambda Function URLs rename `WWW-Authenticate` on a 401 — Medium

- **Task:** a spec-compliant MCP 401 challenge (`WWW-Authenticate: Bearer …, resource_metadata="…"`).
- **Steps:** deployed behind a Function URL and sent a request with no token.
- **Expected:** the header as sent.
- **Actual:** it arrives as `x-amzn-Remapped-www-authenticate`. API Gateway does the same, and it
  can't be configured.
- **Workaround:** also serve Protected Resource Metadata at the root path so clients can discover
  it by probing. The Alexa+ docs say they ignore the header anyway.
- **Suggestion:** pass `WWW-Authenticate` through, or make it opt-in per Function URL. MCP
  authorization depends on it.

### 4. MCP SDK session manager vs. Lambda adapters — Medium

- **Task:** run the MCP server on Lambda (stateless HTTP, JSON responses).
- **Steps:** planned Mangum as the ASGI adapter.
- **Expected:** a standard ASGI app works.
- **Actual:** `StreamableHTTPSessionManager.run()` can only be called once per instance, and
  Mangum enters the ASGI lifespan on every invocation. The second request fails.
- **Workaround:** a ~150-line adapter that keeps one event loop and one lifespan per container.
- **Suggestion:** ship a Lambda handler in the SDK, or let the lifespan be re-entered in stateless
  mode. "MCP on Lambda" is a common target.

### 5. Importing a package started a whole server — Medium (our bug, platform-shaped)

- **Task:** deploy the simulator as a second Lambda reusing the server's adapter.
- **Actual:**
  - The first deploy of the server published `resource = http://127.0.0.1:8000/mcp`: the package
    `__init__` imported the server, and its settings, before the handler set the URL.
  - The simulator Lambda returned 502: importing the adapter ran the server's Lambda-init block
    (SQLite on a read-only filesystem).
- **Workaround:** a lazy package `__init__`, the adapter moved to a side-effect-free module, and
  tests that import the handler in a subprocess and assert what got loaded.
- **Suggestion (docs):** a Lambda Python best-practices note on keeping import-time side effects
  out of shared modules when several functions share one bundle.

### 6. CloudFormation cycle: Cognito callback ↔ Lambda URL ↔ client id — Medium

- **Task:** register the simulator's callback URL on the Cognito client.
- **Actual:** client → simulator URL → simulator function → (environment) client id → client is a
  cycle. The server's own Function URL hits the same problem.
- **Workaround:** at init, read the client from the pool by name (`ListUserPoolClients`) and the
  URLs with `GetFunctionUrlConfig`.
- **Suggestion:** a Function URL env-var placeholder (like `AWS_LAMBDA_FUNCTION_NAME`), or CDK
  guidance for this common OAuth pattern.

### 7. Bedrock Guardrails has no self-harm content filter — Medium

- **Task:** a crisis precheck with Bedrock Guardrails.
- **Expected:** a self-harm category, as in other providers' moderation APIs.
- **Actual:** the categories are Hate, Insults, Sexual, Violence, Misconduct, and Prompt attack.
- **Workaround:** a denied topic "Self-harm" with examples, plus Violence High, plus our phrase
  list first.
- **Suggestion:** a first-class self-harm category with crisis-resource guidance.

### 8. Bedrock latency vs. a voice budget from outside us-east-1 — Low

- **Task:** fit `ApplyGuardrail` (250 ms) and Titan embed (200 ms) into Alexa's 500 ms.
- **Actual:** from a laptop in India: 400–1200 ms each. From Lambda in us-east-1: guard + embed
  together take 330–380 ms.
- **Workaround:** background re-check on timeout; measure from Lambda.
- **Suggestion:** document expected in-region latencies for `ApplyGuardrail` and Titan v2.

### 9. Alexa+ account-linking docs: redirect URIs and the token tiers — Low

- **Actual:**
  - The redirect URIs live in an "Alexa+ Developer Hub" that isn't linked.
  - `client_credentials` in `grant_types_supported` is "required", yet the tier is described as
    "if you have a private MCP Server".
- **Suggestion:** list the redirect URIs on the page, and say clearly whether public add-ons need
  the service tier.

### 10. Haiku and prose schemas — Low

- **Task:** structured JSON from Haiku 4.5 for message decoding.
- **Actual:** "likely_intents (1–3 of {reading, confidence})" came back as one object, so
  validation failed and every live refine fell back to the baseline.
- **Workaround:** give a literal JSON example in the prompt.
- **Suggestion:** surface Converse structured output / JSON schema more prominently in the Bedrock
  Claude docs.

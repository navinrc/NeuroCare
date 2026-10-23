NeuroCare runs entirely on AWS in `us-east-1`. The whole stack is defined in **AWS CDK (Python)**
(`infra/`) and deployed with `cdk deploy`. Everything below is wired into the code, not just
mentioned. File paths are in https://github.com/navinrc/NeuroCare.

**Amazon Bedrock — Claude Haiku 4.5 (Converse API)**
- Every language task is "fast first, refine later": message decoding, task breakdown, step
  splitting, and brain-dump splitting.
- The tool answers Alexa+ at once with a deterministic baseline. Then Haiku 4.5 refines it in the
  background within a 5 s budget, and the result is validated against a schema and stored.
  (`llm/bedrock.py`, `refine.py`, `pillars/translator.py`, `pillars/tasks.py`, `pillars/plan.py`)
- The Alexa+ simulator also uses Haiku 4.5 through Converse **tool use**. It sends the MCP
  server's own instructions and its 29 tools, and lets the model choose tool calls, just as Alexa+
  would. (`alexa_sim/agent.py`)

**Amazon Bedrock Guardrails (`ApplyGuardrail`)**
- The second layer of the crisis check, run on every tool that takes free text. The guardrail has
  a self-harm denied topic plus the Violence filter.
- It runs input-only with a 250 ms budget. On timeout it re-runs in the background, and a late hit
  makes the user's next call return the crisis resources first. (`safety/crisis.py`)

**Amazon Titan Text Embeddings v2**
- Semantic recall: the last tier of exact → alias → fuzzy → embedding.
- Rumination detection: the third similar worry inside a time window, with a cosine ≥ 0.40 tuned
  from live Titan data.
- Vectors are stored as compact float32 and backfilled lazily. (`semantic.py`, `pillars/memory.py`,
  `pillars/guardrail.py`)

**AWS Lambda + Function URLs**
- The MCP server (Streamable HTTP, stateless, JSON responses) runs on an arm64 Python 3.13 Lambda
  behind a Function URL.
- A custom adapter keeps one ASGI lifespan per container. (`lambda_handler.py`, `asgi_lambda.py`)
- Bedrock refines run through **async self-invocation** (`InvocationType=Event`), which keeps
  the Alexa path under 500 ms: warm tool calls take 26 ms median and 67 ms max of server time.
- A second Lambda hosts the Alexa+ simulator. (`alexa_sim/lambda_handler.py`)

**Amazon DynamoDB**
- A single-table design: `PK = USER#<id>`, sort-key prefixes for memories, people, work blocks,
  tasks, inbox messages, plans, worry topics, needs, and overrides.
- TTLs expire short-lived data (topics, inbox, needs).
- The same store interface also has a SQLite backend, and all 497 tests run against both SQLite and
  moto-mocked DynamoDB. (`store/dynamo.py`)
- A second table holds simulator sessions.

**Amazon Cognito**
- OAuth 2.1 account linking, the way Alexa+ links accounts: user pool, hosted UI, a confidential
  app client, auth code + **PKCE S256**, refresh tokens, and a custom scope `neurocare/tools`.
- The server verifies Cognito access tokens (RS256 against the JWKS: issuer, client, scope,
  expiry), uses `sub` as the user id, and publishes OAuth Protected Resource Metadata (RFC 9728).
  (`auth.py`, `alexa_sim/oauth.py`)

**AWS IAM**
- Least-privilege roles per function: the table, the Bedrock models, the specific guardrail, and
  self-invoke.
- A separate deployer role assumes only the CDK bootstrap roles.

**Amazon CloudWatch Logs**
- Function logs with two-week retention. The Lambda `REPORT` durations were used to verify the
  latency budget.

**Amazon Polly**
- Generative voices (Joanna, Matthew) for the scripted demo video, rendered from one live take of
  the deployed stack. (`scripts/video/tts.py`)

The details, with what worked and what didn't, are in `docs/spec.md` (§3, §8, §9),
`docs/aws-setup.md`, `infra/README.md`, and `docs/submission/product-feedback.md`.

# infra — CDK app

Deploys NeuroCare to `us-east-1` (spec §9):

| Resource | Notes |
|---|---|
| DynamoDB `cognitive-substrate` | `PK`/`SK`, TTL on `ttl`, on-demand, AWS-managed KMS, PITR, **retained** on destroy |
| Lambda `neurocare-mcp` | Python 3.13, arm64, 1024 MB, 30 s; `alexa_mcp_server.lambda_handler.handler` |
| Function URL | Auth `NONE`; the app checks Cognito bearer tokens itself |
| Cognito user pool `neurocare-users` | No self sign-up, hosted UI domain, resource server `neurocare` with scope `tools`, **retained** on destroy |
| App client `alexa-plus` | Auth code grant, client secret, scopes `openid email neurocare/tools`, refresh tokens 30 days |
| IAM | Table read/write, Bedrock `InvokeModel` (Haiku 4.5, Titan v2, Nova), `ApplyGuardrail`, self-invoke |
| Lambda `neurocare-alexa-sim` + URL | Alexa simulator (spec §5.9), 60 s; reads the `alexa-plus` client and the server URL at init |
| DynamoDB `neurocare-sim` | Simulator sessions (tokens, history, reminders), TTL 30 days, destroyed with the stack |

Phase 6b adds the Telegram secrets, the EventBridge Scheduler rule, and optional SES inbound.

The Lambda bundle is built on your machine with `uv` (Linux arm64 wheels), so Docker is not needed.

## Settings (`cdk.json` → `context`)

| Key | Default | Change when |
|---|---|---|
| `cognito_domain_prefix` | `neurocare-demo` | The prefix is taken (must be unique in the region) |
| `alexa_redirect_uris` | `[]` | You have the add-on's redirect URIs from the Alexa developer console |
| `bedrock_guardrail_id` / `_version` | `7dnkm5nfui1e` / `1` | Another guardrail (FINDINGS #31); empty keeps the phrase list only |
| `llm_provider` | `bedrock` | `off` for baselines only |
| `memory_mb` | `1024` | Latency (more memory = more CPU) |
| `public_base_url` | `""` | A custom domain; empty uses the Function URL |

The MCP Inspector callback `http://localhost:6274/oauth/callback` is always registered, so the
OAuth flow can be tried before Alexa is set up.

## Deploy

```bash
aws login --profile neurocare-admin
cd infra && uv sync
export AWS_PROFILE=neurocare-admin
npx aws-cdk@2.1146.1 bootstrap          # once per account/region
npx aws-cdk@2.1146.1 diff
npx aws-cdk@2.1146.1 deploy             # prints McpUrl, UserPoolId, ClientId, AuthorizeUrl, TokenUrl, Scopes
```

## Demo user and data

```bash
POOL=<UserPoolId>; CLIENT=<ClientId>; EMAIL=<your email>
aws cognito-idp admin-create-user --user-pool-id $POOL --username $EMAIL \
  --user-attributes Name=email,Value=$EMAIL Name=email_verified,Value=true --message-action SUPPRESS
aws cognito-idp admin-set-user-password --user-pool-id $POOL --username $EMAIL --password '<strong password>' --permanent
SUB=$(aws cognito-idp admin-get-user --user-pool-id $POOL --username $EMAIL \
  --query "UserAttributes[?Name=='sub'].Value" --output text)

cd .. && STORE=dynamo DEMO_USER_ID=$SUB uv run alexa-mcp-seed --reset   # the sub is the user_id

aws cognito-idp describe-user-pool-client --user-pool-id $POOL --client-id $CLIENT \
  --query UserPoolClient.ClientSecret --output text                       # for Inspector / Alexa
```

## Tests

```bash
cd infra && uv run pytest -q   # synth assertions; bundling skipped
```

## Tear down

`npx aws-cdk@2.1146.1 destroy` removes the Lambda, URL, and IAM. The table and user pool are
retained (user data); delete them in the console if you really mean it.

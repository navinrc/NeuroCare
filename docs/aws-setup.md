# AWS Setup

One-time setup for NeuroCare's AWS resources (Bedrock, DynamoDB, Lambda) and for using the
Agent Toolkit for AWS from Claude Code with read-only access.

> Needed from **spec phase 3** (Bedrock translator) onward. Phases 1–2 run fully local on SQLite.
> Section 6 (Cognito) is needed at **phase 6**; section 7 (Telegram) only for **phase 6b**. See [`spec.md`](spec.md) §3 and §11.

## 1. Account

A new AWS account on the **free plan** is enough for the hackathon.

- New accounts get up to **$200 in credits** ($100 at sign-up + $100 for guided activities).
- The free plan ends after **6 months or when credits run out**, whichever comes first.
  Upgrading to a paid plan keeps unused credits valid for 12 months from sign-up.
- **Bedrock has no always-free tier** — every call is paid from credits. Claude Haiku 4.5 is
  cheap; expect a few dollars for the whole build.
- Lambda and DynamoDB at demo traffic stay within their free tiers.
- Also check the [hackathon resources page](https://amazonappdev2026.devpost.com/resources) for
  sponsor-provided AWS credits.

## 2. Secure the account

1. Enable **MFA on the root user**. Use root only for billing and account settings after this.
2. **IAM → Users → Create user** for yourself (e.g. `navin-admin`): console access on,
   `AdministratorAccess` attached, MFA enabled. **Create no access keys** — the CLI signs in
   through the console with `aws login` (§4). This is the user you deploy with.
3. **Billing → Budgets:** create a cost budget with email alerts at **$20** and **$50**.

> **Not IAM Identity Center.** Identity Center's permission sets require AWS Organizations, and
> creating an organization moves a free-plan account to the paid plan and expires its free tier
> credits immediately. An IAM user plus `aws login` still gives short-lived CLI credentials with
> no long-lived keys on disk.

## 3. Region and Bedrock

1. Use **`us-east-1`** for everything (matches the spec and diagram).
2. Open the **Amazon Bedrock console** in `us-east-1` and run one test prompt against
   **Claude Haiku 4.5**. First use of Anthropic models asks for a short use-case form — submit it.
3. Also test **Titan Text Embeddings v2** once.
4. Note the model / inference-profile IDs; they go into `BEDROCK_MODEL_ID` and
   `BEDROCK_EMBED_MODEL_ID` (spec §9).
5. Free-plan accounts may be blocked from third-party (Marketplace-billed) models such as
   Anthropic's. If Haiku fails with an access or payment error after the use-case form, either
   upgrade to the paid plan (unused credits stay valid) or switch `BEDROCK_MODEL_ID` to an
   Amazon Nova model.

Test from the CLI once §4 is done (or from CloudShell, dropping `--profile`):

```bash
aws bedrock-runtime converse --region us-east-1 --profile neurocare-admin \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0 \
  --messages '[{"role":"user","content":[{"text":"Say hi"}]}]'

aws bedrock-runtime invoke-model --region us-east-1 --profile neurocare-admin \
  --model-id amazon.titan-embed-text-v2:0 --body '{"inputText":"hello"}' \
  --cli-binary-format raw-in-base64-out out.json && head -c 200 out.json

BEDROCK_LIVE=1 AWS_PROFILE=neurocare-admin uv run pytest -m live -s   # repo's live tests
```

## 4. CLI profiles

Two profiles: one for you (full access), one for the agent (view only).

| Profile | Credentials | Permissions | Used by |
|---|---|---|---|
| `neurocare-admin` | `aws login` as your IAM user | `AdministratorAccess` | You: `cdk deploy`, console, manual fixes |
| `neurocare-agent` | Assumes IAM role `neurocare-agent` via `neurocare-admin` | `ViewOnlyAccess` + inline policy below | Agent Toolkit MCP server in Claude Code |

**Agent role.** IAM → Roles → Create role → trusted entity **AWS account** (this account) →
attach `ViewOnlyAccess` → name it `neurocare-agent`. Then narrow the trust policy so only your
IAM user can assume it:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::<ACCOUNT_ID>:user/navin-admin" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

`ViewOnlyAccess` (AWS managed) lets the agent list and describe resources but **not read data**
(no DynamoDB items, no S3 objects) — user memory stays private. Add this inline policy to the
`neurocare-agent` role so it can also read logs and stack status for troubleshooting:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TroubleshootingReads",
      "Effect": "Allow",
      "Action": [
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
        "logs:GetLogEvents",
        "logs:FilterLogEvents",
        "logs:StartQuery",
        "logs:GetQueryResults",
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents",
        "cloudformation:DescribeStackResources",
        "cloudformation:GetTemplate",
        "lambda:GetFunction",
        "lambda:GetFunctionConfiguration",
        "lambda:GetFunctionUrlConfig",
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics",
        "scheduler:GetSchedule",
        "scheduler:ListSchedules",
        "secretsmanager:DescribeSecret",
        "secretsmanager:ListSecrets",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

**Backstop on the admin profile.** So the agent can never act with admin rights, even if it
picks up the wrong profile, add this statement as an inline policy on your IAM user. It
denies everything that arrives through the AWS MCP Server while leaving your own CLI and
console calls untouched:

```json
{
  "Sid": "DenyActionsViaAWSMCPServer",
  "Effect": "Deny",
  "Action": "*",
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "aws:CalledViaAWSMCP": "aws-mcp.amazonaws.com"
    }
  }
}
```

**Install and log in.** `aws login` needs AWS CLI **2.32 or later**:

```bash
brew install awscli && aws --version
aws login --profile neurocare-admin    # browser opens; sign in as your IAM user; region us-east-1
```

Add the agent profile to `~/.aws/config`:

```ini
[profile neurocare-agent]
role_arn = arn:aws:iam::<ACCOUNT_ID>:role/neurocare-agent
source_profile = neurocare-admin
region = us-east-1
```

Check both (the `!` prefix runs a command inside the Claude Code session):

```bash
! aws sts get-caller-identity --profile neurocare-admin   # .../user/navin-admin
! aws sts get-caller-identity --profile neurocare-agent   # .../assumed-role/neurocare-agent/...
```

Sessions are short-lived; when a command reports expired credentials, run
`aws login --profile neurocare-admin` again.

## 5. Agent Toolkit for AWS (Claude Code)

Free to use; you pay only for AWS resources it touches.

```text
/plugin marketplace update claude-plugins-official
/plugin install aws-core@claude-plugins-official
```

Then point the plugin's AWS MCP Server at the **`neurocare-agent`** profile (set
`AWS_PROFILE=neurocare-agent` and `AWS_REGION=us-east-1` in the plugin's MCP server
environment — check the plugin's MCP config after install for the exact place).

What the agent is for:
- Searching current AWS docs (e.g. v2 stateless HTTP on Lambda, CDK constructs, Bedrock APIs)
- Reading CloudWatch logs, Lambda config, and CloudFormation events when something fails
- Checking regional availability of Bedrock models

What stays manual (you, with `neurocare-admin`):
- `cdk bootstrap` / `cdk deploy` / `cdk destroy`
- Bedrock model access, Guardrail creation, budgets, IAM changes

## 6. Cognito account linking (phase 6)

Alexa+ links accounts with OAuth 2.1 only ([spec §3](spec.md#3-locked-decisions)). CDK creates
these; the list is what to check in the console.

1. **User pool** in `us-east-1` with a hosted UI domain (e.g. `neurocare-demo.auth.us-east-1.amazoncognito.com`).
2. **App client:** authorization code grant only (no implicit), **PKCE required (S256)**,
   refresh tokens enabled (e.g. 30-day validity), a confidential client with a secret, scopes `openid` plus a
   custom scope such as `neurocare/tools`.
3. **Callback URLs:** add every redirect URI the Alexa developer console shows for the add-on
   (there are several; register all of them).
4. **Demo user:** create one user for the demo account; its `sub` becomes the `user_id`.
5. **Alexa developer console → account linking:** authorization URI, token URI, client ID and
   secret, and scopes from the steps above.
6. **Check:** `curl $FUNCTION_URL/.well-known/oauth-protected-resource` returns the resource URL
   and the Cognito issuer, and a request without a token gets `401` with `WWW-Authenticate`.
7. Keep `ALLOW_STATIC_TOKEN` **off** in the deployed Lambda.

## 7. Telegram bot (phase 6b)

Optional companion channel ([spec §5.7](spec.md#57-telegram-companion)). Skip until the
Lambda Function URL exists.

1. In Telegram, message **@BotFather** → `/newbot` → pick a name and username. Copy the bot token.
2. Generate a webhook secret (1–256 chars of `A-Z a-z 0-9 _ -`):
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
3. Store both in **Secrets Manager** (`us-east-1`), e.g. secret `neurocare/telegram` with keys
   `bot_token` and `webhook_secret`. CDK grants the Lambda read access; never put them in `.env`
   files that get committed.
4. After `cdk deploy`, register the webhook so Telegram sends the secret header on every call:
   ```bash
   curl -s "https://api.telegram.org/bot$BOT_TOKEN/setWebhook" \
     -d "url=$FUNCTION_URL/telegram" \
     -d "secret_token=$WEBHOOK_SECRET" \
     -d 'allowed_updates=["message","callback_query"]'
   ```
   Check with `getWebhookInfo`. For local dev, skip the webhook and run the long-polling mode.
5. Confirm the **EventBridge Scheduler** rule (every 15 min) exists after deploy; it drives
   the bot's opt-in messages.

Privacy reminder: bot chats are not end-to-end encrypted. Demo with synthetic messages only.

### Optional: email forwarding address (spec §5.8)

Needs a domain you control (a subdomain is enough).

1. **SES → Identities:** verify the domain (e.g. `in.neurocare.example`) in `us-east-1`.
2. **DNS:** add an MX record `in.neurocare.example → inbound-smtp.us-east-1.amazonaws.com` (priority 10).
3. **SES → Email receiving:** create a rule set (CDK can do this) with one rule for
   `inbox@in.neurocare.example`: action **S3** (the KMS-encrypted bucket with a 1-day lifecycle),
   with S3 event notification → the Lambda. Make the rule set **active**.
4. Set `email.allowed_senders` in the profile seed to your own address(es).
5. Test: forward a synthetic email from an allowed address and check it shows up as a
   Telegram card or under "Alexa, what needs me?". Mail from other addresses must not appear.

## 8. Checklist

- [ ] Account created, root MFA on
- [ ] IAM user (console access, MFA, no access keys) + `neurocare-admin` profile via `aws login`
- [ ] Budgets at $20 / $50
- [ ] Bedrock: Haiku 4.5 + Titan Embeddings v2 tested in `us-east-1`, use-case form submitted
- [ ] `neurocare-agent` role with `ViewOnlyAccess` + inline read policy, trust limited to your IAM user
- [ ] Backstop deny statement on your IAM user
- [ ] `aws-core` plugin installed, using `neurocare-agent`
- [ ] `aws sts get-caller-identity` works for both profiles
- [ ] (Phase 6) Cognito user pool, PKCE app client, Alexa redirect URIs, account linking configured; `ALLOW_STATIC_TOKEN` off
- [ ] (Phase 6b) Telegram bot created; token + webhook secret in Secrets Manager
- [ ] (Phase 6b) Webhook registered with `secret_token`; Scheduler rule present
- [ ] (Optional) SES domain verified, MX record set, receipt rule set active, allowlist seeded

## References

- [Agent Toolkit for AWS — user guide](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/what-is-agent-toolkit.html)
- [AWS MCP Server IAM policy examples](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/security_iam_id-based-policy-examples.html)
- [aws/agent-toolkit-for-aws on GitHub](https://github.com/aws/agent-toolkit-for-aws)
- [Using Amazon Bedrock with the AWS Free Tier](https://dev.to/aws/using-amazon-bedrock-with-aws-free-tier-for-the-10000-aideas-competition-554f)

# AWS Setup

One-time setup for NeuroCare's AWS resources (Bedrock, DynamoDB, Lambda) and for using the
Agent Toolkit for AWS from Claude Code with read-only access.

> Needed from **spec phase 3** (Bedrock translator) onward. Phases 1–2 run fully local on SQLite.
> See [`spec.md`](spec.md) §3 and §11.

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
2. Enable **IAM Identity Center** and create a user for yourself with the
   `AdministratorAccess` permission set. This is the profile you deploy with.
3. **Billing → Budgets:** create a cost budget with email alerts at **$20** and **$50**.

## 3. Region and Bedrock

1. Use **`us-east-1`** for everything (matches the spec and diagram).
2. Open the **Amazon Bedrock console** in `us-east-1` and run one test prompt against
   **Claude Haiku 4.5**. First use of Anthropic models asks for a short use-case form — submit it.
3. Also test **Titan Text Embeddings v2** once.
4. Note the model / inference-profile IDs; they go into `BEDROCK_MODEL_ID` and
   `BEDROCK_EMBED_MODEL_ID` (spec §9).

## 4. CLI profiles

Two profiles: one for you (full access), one for the agent (view only).

| Profile | Permission set | Used by |
|---|---|---|
| `neurocare-admin` | `AdministratorAccess` | You: `cdk deploy`, console, manual fixes |
| `neurocare-agent` | `ViewOnlyAccess` + inline policy below | Agent Toolkit MCP server in Claude Code |

`ViewOnlyAccess` (AWS managed) lets the agent list and describe resources but **not read data**
(no DynamoDB items, no S3 objects) — user memory stays private. Add this inline policy to the
agent's permission set so it can also read logs and stack status for troubleshooting:

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
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

**Backstop on the admin profile.** So the agent can never act with admin rights, even if it
picks up the wrong profile, add this statement to the `neurocare-admin` permission set. It
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

Log in from this repo (the `!` prefix runs it inside the Claude Code session):

```bash
! aws configure sso           # create neurocare-admin, then again for neurocare-agent
! aws sso login --profile neurocare-admin
! aws sts get-caller-identity --profile neurocare-agent
```

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

## 6. Checklist

- [ ] Account created, root MFA on
- [ ] Identity Center user + `neurocare-admin` profile
- [ ] Budgets at $20 / $50
- [ ] Bedrock: Haiku 4.5 + Titan Embeddings v2 tested in `us-east-1`, use-case form submitted
- [ ] `neurocare-agent` profile with `ViewOnlyAccess` + inline read policy
- [ ] Backstop deny statement on `neurocare-admin`
- [ ] `aws-core` plugin installed, using `neurocare-agent`
- [ ] `aws sts get-caller-identity` works for both profiles

## References

- [Agent Toolkit for AWS — user guide](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/what-is-agent-toolkit.html)
- [AWS MCP Server IAM policy examples](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/security_iam_id-based-policy-examples.html)
- [aws/agent-toolkit-for-aws on GitHub](https://github.com/aws/agent-toolkit-for-aws)
- [Using Amazon Bedrock with the AWS Free Tier](https://dev.to/aws/using-amazon-bedrock-with-aws-free-tier-for-the-10000-aideas-competition-554f)

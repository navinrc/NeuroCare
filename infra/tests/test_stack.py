"""Synth checks for the phase 6 stack (bundling skipped, so no Lambda build runs)."""

import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template
from neurocare_infra.stack import FUNCTION_NAME, INSPECTOR_CALLBACK, NeuroCareStack

CONTEXT = json.loads((Path(__file__).parents[1] / "cdk.json").read_text())["context"]


@pytest.fixture(scope="module")
def template() -> Template:
    context = {
        **CONTEXT,
        "alexa_redirect_uris": ["https://pitangui.amazon.com/api/skill/link/TEST"],
        "aws:cdk:bundling-stacks": [],
    }
    app = cdk.App(context=context)
    stack = NeuroCareStack(app, "Test", env=cdk.Environment(account="123456789012", region="us-east-1"))
    return Template.from_stack(stack)


def test_table_matches_spec(template):
    template.has_resource_properties(
        "AWS::DynamoDB::GlobalTable",
        {
            "TableName": "cognitive-substrate",
            "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            "BillingMode": "PAY_PER_REQUEST",
            "TimeToLiveSpecification": {"AttributeName": "ttl", "Enabled": True},
            "SSESpecification": Match.object_like({"SSEEnabled": True}),
        },
    )


def test_app_client_is_auth_code_with_secret_and_refresh(template):
    template.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {
            "AllowedOAuthFlows": ["code"],
            "AllowedOAuthFlowsUserPoolClient": True,
            "GenerateSecret": True,
            "AllowedOAuthScopes": Match.array_with(["openid"]),
            "CallbackURLs": ["https://pitangui.amazon.com/api/skill/link/TEST", INSPECTOR_CALLBACK],
            "RefreshTokenValidity": 43200,  # 30 days, in minutes
            "EnableTokenRevocation": True,
        },
    )
    template.has_resource_properties(
        "AWS::Cognito::UserPool", {"AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True}}
    )


def test_lambda_runs_stateless_on_dynamo_without_static_token(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": FUNCTION_NAME,
            "Runtime": "python3.13",
            "Architectures": ["arm64"],
            "Handler": "alexa_mcp_server.lambda_handler.handler",
            "Environment": {
                "Variables": Match.object_like(
                    {"STORE": "dynamo", "COGNITO_SCOPE": "neurocare/tools", "LLM_PROVIDER": "bedrock"}
                )
            },
        },
    )
    variables = next(iter(template.find_resources("AWS::Lambda::Function").values()))["Properties"]["Environment"][
        "Variables"
    ]
    assert "ALLOW_STATIC_TOKEN" not in variables and "AUTH_TOKEN" not in variables
    template.has_resource_properties("AWS::Lambda::Url", {"AuthType": "NONE"})


def test_lambda_may_invoke_itself_and_bedrock(template):
    statements = [
        s
        for policy in template.find_resources("AWS::IAM::Policy").values()
        for s in policy["Properties"]["PolicyDocument"]["Statement"]
    ]
    actions = {a for s in statements for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])}
    assert {
        "lambda:InvokeFunction",
        "lambda:GetFunctionUrlConfig",
        "bedrock:InvokeModel",
        "bedrock:ApplyGuardrail",
    } <= actions
    assert {"dynamodb:Query", "dynamodb:PutItem", "dynamodb:BatchWriteItem"} <= actions

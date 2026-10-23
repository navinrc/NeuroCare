"""NeuroCare on AWS (spec §9): DynamoDB table, Lambda + Function URL, Cognito account linking.

Phase 6b adds the Telegram secrets, the EventBridge Scheduler rule, and optional SES inbound.
"""

import shutil
import subprocess
from pathlib import Path

import jsii
from aws_cdk import (
    BundlingOptions,
    CfnOutput,
    Duration,
    ILocalBundling,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

REPO = Path(__file__).resolve().parents[2]
FUNCTION_NAME = "neurocare-mcp"
SIM_FUNCTION_NAME = "neurocare-alexa-sim"
RESOURCE_SERVER = "neurocare"
SCOPE = "tools"
PLATFORM = "aarch64-manylinux_2_28"
INSPECTOR_CALLBACK = "http://localhost:6274/oauth/callback"
"""MCP Inspector's OAuth callback, so the Cognito flow can be tried before Alexa is wired up."""

ASSET_EXCLUDE = [".venv", ".git", ".data", "infra", "tests", "docs", "scripts", "**/__pycache__", "*.pyc", "cdk.out"]


@jsii.implements(ILocalBundling)
class UvBundling:
    """Builds the Lambda bundle with uv on the host: Linux arm64 wheels, no Docker needed."""

    def try_bundle(self, output_dir: str, *, image=None, **_: object) -> bool:
        uv = shutil.which("uv")
        if uv is None:
            return False  # CDK falls back to the Docker bundling command
        requirements = Path(output_dir) / "requirements.txt"
        target = ["--target", output_dir, "--python-platform", PLATFORM, "--python-version", "3.13"]
        run = lambda *args: subprocess.run([uv, *args], cwd=REPO, check=True)  # noqa: E731
        run("export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes", "-q", "-o", str(requirements))
        run("pip", "install", "-q", "-r", str(requirements), *target, "--only-binary", ":all:")
        run("pip", "install", "-q", "--no-deps", ".", *target)
        requirements.unlink()
        return True


class NeuroCareStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        ctx = self.node.try_get_context

        table = dynamodb.TableV2(
            self,
            "Table",
            table_name=ctx("table_name") or "cognitive-substrate",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing=dynamodb.Billing.on_demand(),
            encryption=dynamodb.TableEncryptionV2.aws_managed_key(),
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- Cognito: Alexa+ account linking (OAuth 2.1 auth code + PKCE, refresh tokens) -----------
        pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name="neurocare-users",
            self_sign_up_enabled=False,  # one demo account, created by hand (docs/aws-setup.md §6)
            sign_in_aliases=cognito.SignInAliases(email=True),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.RETAIN,
        )
        domain = pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=ctx("cognito_domain_prefix")),
        )
        tools_scope = cognito.ResourceServerScope(scope_name=SCOPE, scope_description="Use the NeuroCare MCP tools")
        resource_server = pool.add_resource_server("ResourceServer", identifier=RESOURCE_SERVER, scopes=[tools_scope])
        code = lambda_.Code.from_asset(
            str(REPO),
            exclude=ASSET_EXCLUDE,
            bundling=BundlingOptions(
                image=lambda_.Runtime.PYTHON_3_13.bundling_image,
                local=UvBundling(),
                command=["bash", "-c", "pip install --no-cache-dir -q . -t /asset-output"],
            ),
        )

        # --- Alexa simulator (spec §5.9): its own function, URL, and session table ------------------
        # Built before the client, whose callback URLs include the simulator's. The simulator reads the
        # client and the MCP server's URL at init (by pool id and function name), so nothing cycles.
        sim_table = dynamodb.TableV2(
            self,
            "SimTable",
            table_name="neurocare-sim",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            billing=dynamodb.Billing.on_demand(),
            encryption=dynamodb.TableEncryptionV2.aws_managed_key(),
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,  # simulator sessions only
        )
        sim_fn = lambda_.Function(
            self,
            "Simulator",
            function_name=SIM_FUNCTION_NAME,
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="alexa_sim.lambda_handler.handler",
            code=code,
            memory_size=1024,
            timeout=Duration.seconds(60),
            environment={
                "SIM_MCP_FUNCTION": FUNCTION_NAME,
                "SIM_MODEL_ID": ctx("sim_model_id") or ctx("bedrock_model_id"),
                "SIM_TABLE": sim_table.table_name,
                "COGNITO_USER_POOL_ID": pool.user_pool_id,
                "COGNITO_DOMAIN": f"{domain.domain_name}.auth.{self.region}.amazoncognito.com",
            },
            log_group=logs.LogGroup(
                self,
                "SimLogs",
                log_group_name=f"/aws/lambda/{SIM_FUNCTION_NAME}",
                retention=logs.RetentionDays.TWO_WEEKS,
            ),
        )
        sim_url = sim_fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)
        sim_table.grant_read_write_data(sim_fn)
        sim_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cognito-idp:ListUserPoolClients", "cognito-idp:DescribeUserPoolClient"],
                resources=[pool.user_pool_arn],
            )
        )
        sim_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["lambda:GetFunctionUrlConfig"],
                resources=[
                    f"arn:aws:lambda:{self.region}:{self.account}:function:{name}"
                    for name in (FUNCTION_NAME, SIM_FUNCTION_NAME)
                ],
            )
        )
        sim_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/*",
                ],
            )
        )

        redirect_uris = [u for u in (ctx("alexa_redirect_uris") or []) if u] + [
            INSPECTOR_CALLBACK,
            f"{sim_url.url}sim/callback",
        ]
        client = pool.add_client(
            "AlexaClient",
            user_pool_client_name="alexa-plus",
            generate_secret=True,
            auth_flows=cognito.AuthFlow(),  # hosted UI only
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.resource_server(resource_server, tools_scope),
                ],
                callback_urls=redirect_uris,
            ),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
            enable_token_revocation=True,
            prevent_user_existence_errors=True,
        )

        # --- Lambda: the MCP server, stateless HTTP + JSON responses --------------------------------
        log_group = logs.LogGroup(
            self, "Logs", log_group_name=f"/aws/lambda/{FUNCTION_NAME}", retention=logs.RetentionDays.TWO_WEEKS
        )
        environment = {
            "STORE": "dynamo",
            "TABLE_NAME": table.table_name,
            "COGNITO_USER_POOL_ID": pool.user_pool_id,
            "COGNITO_CLIENT_ID": client.user_pool_client_id,
            "COGNITO_DOMAIN": f"{domain.domain_name}.auth.{self.region}.amazoncognito.com",
            "COGNITO_SCOPE": f"{RESOURCE_SERVER}/{SCOPE}",
            "LLM_PROVIDER": ctx("llm_provider") or "bedrock",
            "BEDROCK_MODEL_ID": ctx("bedrock_model_id"),
            "BEDROCK_EMBED_MODEL_ID": ctx("bedrock_embed_model_id"),
        }
        guardrail_id, guardrail_version = ctx("bedrock_guardrail_id"), ctx("bedrock_guardrail_version")
        if guardrail_id:
            environment |= {"BEDROCK_GUARDRAIL_ID": guardrail_id, "BEDROCK_GUARDRAIL_VERSION": guardrail_version}
        if ctx("public_base_url"):  # a custom domain; otherwise the function reads its own URL at init
            environment["PUBLIC_BASE_URL"] = ctx("public_base_url")

        fn = lambda_.Function(
            self,
            "Server",
            function_name=FUNCTION_NAME,
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="alexa_mcp_server.lambda_handler.handler",
            code=code,
            memory_size=int(ctx("memory_mb") or 1024),
            timeout=Duration.seconds(30),
            environment=environment,
            log_group=log_group,
        )
        url = fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)  # bearer tokens checked in the app

        # --- Permissions ------------------------------------------------------------------------------
        table.grant_read_write_data(fn)
        self_arn = f"arn:aws:lambda:{self.region}:{self.account}:function:{FUNCTION_NAME}"  # by name: no cycle
        fn.add_to_role_policy(
            iam.PolicyStatement(actions=["lambda:InvokeFunction", "lambda:GetFunctionUrlConfig"], resources=[self_arn])
        )
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5*",
                    "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2*",
                    "arn:aws:bedrock:*::foundation-model/amazon.nova-*",
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/*",
                ],
            )
        )
        if guardrail_id:
            fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["bedrock:ApplyGuardrail"],
                    resources=[f"arn:aws:bedrock:{self.region}:{self.account}:guardrail/{guardrail_id}"],
                )
            )

        # --- Outputs: what Alexa's account-linking form and the seed need ----------------------------
        hosted = f"https://{domain.domain_name}.auth.{self.region}.amazoncognito.com"
        CfnOutput(self, "McpUrl", value=f"{url.url}mcp")
        CfnOutput(self, "FunctionUrl", value=url.url)
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "UserPoolId", value=pool.user_pool_id)
        CfnOutput(self, "ClientId", value=client.user_pool_client_id)
        CfnOutput(self, "AuthorizeUrl", value=f"{hosted}/oauth2/authorize")
        CfnOutput(self, "TokenUrl", value=f"{hosted}/oauth2/token")
        CfnOutput(self, "Scopes", value=f"openid email {RESOURCE_SERVER}/{SCOPE}")
        CfnOutput(self, "SimulatorUrl", value=sim_url.url)

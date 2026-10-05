"""Render the AWS architecture diagram for docs/spec.md.

Dev-only; not part of the server package.

    brew install graphviz
    uv run --no-project --with diagrams python docs/diagrams/aws_architecture.py

Writes docs/diagrams/aws_architecture.png next to this file.
"""

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import DynamodbTable
from diagrams.aws.engagement import SimpleEmailServiceSes
from diagrams.aws.integration import EventbridgeScheduler
from diagrams.aws.general import User
from diagrams.aws.iot import IotAlexaEcho, IotAlexaVoiceService
from diagrams.aws.management import Cloudformation, CloudwatchLogs
from diagrams.aws.ml import Bedrock
from diagrams.aws.security import KMS, IAMRole, SecretsManager
from diagrams.aws.storage import SimpleStorageServiceS3
from diagrams.generic.database import SQL
from diagrams.onprem.client import Client
from diagrams.programming.language import Python
from diagrams.saas.chat import Telegram

OUT = Path(__file__).with_suffix("")

GRAPH = {
    "fontsize": "22",
    "fontname": "Helvetica",
    "pad": "0.6",
    "nodesep": "0.7",
    "ranksep": "0.9",
    "splines": "spline",
}
NODE = {"fontsize": "12", "fontname": "Helvetica"}
EDGE = {"fontsize": "11", "fontname": "Helvetica"}

AWS_BLUE = "#147EBA"
AWS_ORANGE = "#ED7100"
BEDROCK_TEAL = "#01A88D"
GREY = "#7D8998"
TELEGRAM_BLUE = "#229ED9"

with Diagram(
    "NeuroCare — AWS Architecture",
    filename=str(OUT),
    outformat="png",
    direction="LR",
    show=False,
    graph_attr=GRAPH,
    node_attr=NODE,
    edge_attr=EDGE,
):
    user = User("User\n(voice · text)")

    with Cluster("Amazon Alexa"):
        echo = IotAlexaEcho("Echo device")
        alexa = IotAlexaVoiceService("Alexa+\n(LLM orchestration)")

    telegram = Telegram("Telegram bot\n(optional companion)")

    with Cluster("AWS account · us-east-1", graph_attr={"bgcolor": "#F7F9FC"}):
        with Cluster("Compute", graph_attr={"bgcolor": "#FFF4E8"}):
            mcp = Lambda("MCP server\n(Python, stateless\nStreamable HTTP)\n+ Function URL")
            role = IAMRole("Execution role\n(least privilege)")
            scheduler = EventbridgeScheduler("EventBridge Scheduler\n(every 15 min)")

        with Cluster("Email forwarding (optional)", graph_attr={"bgcolor": "#FFF9E6", "style": "dashed"}):
            ses = SimpleEmailServiceSes("SES inbound\n(allowlist + SPF/DKIM)")
            raw = SimpleStorageServiceS3("S3 raw MIME\n(1-day lifecycle)")

        with Cluster("Data", graph_attr={"bgcolor": "#EEF3FB"}):
            table = DynamodbTable("cognitive-substrate\n(PK=USER#id)")
            kms = KMS("KMS\n(encryption at rest)")
            secrets = SecretsManager("Secrets Manager\n(bot token ·\nwebhook secret)")

        with Cluster("Amazon Bedrock", graph_attr={"bgcolor": "#E9F7F4"}):
            llm = Bedrock("Claude Haiku 4.5\n(Converse)")
            embed = Bedrock("Titan Text\nEmbeddings v2")
            guard = Bedrock("Guardrails\n(ApplyGuardrail)")

        with Cluster("Ops", graph_attr={"bgcolor": "#F2F2F2"}):
            logs = CloudwatchLogs("CloudWatch Logs\n(metadata only)")
            cfn = Cloudformation("AWS CDK →\nCloudFormation")

    with Cluster("Local dev", graph_attr={"bgcolor": "#FAFAFA", "style": "dashed"}):
        inspector = Client("MCP Inspector")
        local = Python("uv run\nalexa-mcp-server")
        sqlite = SQL("SQLite")

    user >> Edge(label="speaks") >> echo >> alexa
    alexa >> Edge(label="MCP · Streamable HTTP\nBearer token", color=AWS_ORANGE, style="bold") >> mcp
    user >> Edge(label="forwards · taps", color=TELEGRAM_BLUE) >> telegram
    telegram >> Edge(label="webhook POST /telegram\nsecret header", color=TELEGRAM_BLUE) >> mcp
    mcp >> Edge(label="Bot API sendMessage", color=TELEGRAM_BLUE, style="dashed") >> telegram
    scheduler >> Edge(label="invoke", color=AWS_ORANGE) >> mcp
    user >> Edge(label="forwards email", style="dashed", color=GREY) >> ses
    ses >> Edge(style="dashed", color=GREY) >> raw
    raw >> Edge(label="object created", style="dashed", color=GREY) >> mcp
    secrets - Edge(style="dotted", color=GREY) - mcp
    cfn >> Edge(label="deploys", style="dashed", color=GREY) >> mcp
    mcp >> Edge(style="dotted", color=GREY) >> logs
    mcp >> Edge(label="crisis check", color=BEDROCK_TEAL) >> guard
    mcp >> Edge(label="InvokeModel", color=BEDROCK_TEAL) >> embed
    mcp >> Edge(label="Converse", color=BEDROCK_TEAL) >> llm
    mcp >> Edge(label="Query / PutItem", color=AWS_BLUE) >> table
    table - Edge(style="dotted", color=GREY) - kms
    role - Edge(style="dotted", color=GREY) - mcp

    inspector >> Edge(label="localhost:8000/mcp", style="dashed", color=GREY) >> local
    local >> Edge(style="dashed", color=GREY) >> sqlite

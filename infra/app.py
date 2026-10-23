#!/usr/bin/env python3
"""CDK entry point: ``npx aws-cdk@2 deploy --profile neurocare-admin`` (see infra/README.md)."""

import os

import aws_cdk as cdk
from neurocare_infra.stack import NeuroCareStack

app = cdk.App()
NeuroCareStack(
    app,
    "NeuroCare",
    env=cdk.Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"), region="us-east-1"),
    description="NeuroCare MCP server for Alexa+ (Amazon Developer Hackathon 2026)",
)
app.synth()

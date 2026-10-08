"""Amazon Bedrock clients: Converse for JSON tasks, Titan Text Embeddings v2 for vectors."""

import json
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from alexa_mcp_server.llm import LLMError, parse_json_object

MAX_TOKENS = 1500


class BedrockLLM:
    def __init__(self, model_id: str, region: str):
        self.model_id = model_id
        self._region = region
        self._clients: dict[float, Any] = {}

    def _client(self, timeout: float) -> Any:
        # botocore timeouts are per client, so keep one client per timeout value.
        if timeout not in self._clients:
            config = Config(connect_timeout=2, read_timeout=timeout, retries={"max_attempts": 1})
            self._clients[timeout] = boto3.client("bedrock-runtime", region_name=self._region, config=config)
        return self._clients[timeout]

    def complete_json(self, system: str, prompt: str, *, timeout: float) -> dict[str, Any]:
        try:
            response = self._client(timeout).converse(
                modelId=self.model_id,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0},
            )
        except (BotoCoreError, ClientError) as exc:
            raise LLMError(f"bedrock converse failed: {type(exc).__name__}") from None
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        text = "".join(block.get("text", "") for block in blocks)
        return parse_json_object(text)


class BedrockEmbedder:
    def __init__(self, model_id: str, region: str, dimensions: int = 1024):
        self.model_id = model_id
        self.dimensions = dimensions
        config = Config(connect_timeout=1, read_timeout=2, retries={"max_attempts": 1})
        self._client = boto3.client("bedrock-runtime", region_name=region, config=config)

    def embed(self, text: str) -> list[float]:
        body = json.dumps({"inputText": text[:8000], "dimensions": self.dimensions, "normalize": True})
        try:
            response = self._client.invoke_model(modelId=self.model_id, body=body)
        except (BotoCoreError, ClientError) as exc:
            raise LLMError(f"bedrock embedding failed: {type(exc).__name__}") from None
        return json.loads(response["body"].read())["embedding"]

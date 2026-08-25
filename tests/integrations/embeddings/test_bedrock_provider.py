import io
import json

import pytest

from app.integrations.embeddings.bedrock_provider import BedrockEmbeddingProvider


class FakeBedrockRuntimeClient:
    def __init__(self, response_body: bytes):
        self._response_body = response_body
        self.last_request: dict | None = None

    def invoke_model(self, **kwargs):
        self.last_request = kwargs
        return {"body": io.BytesIO(self._response_body)}


class FailingBedrockRuntimeClient:
    def invoke_model(self, **kwargs):
        raise RuntimeError("bedrock unavailable")


def test_embed_calls_bedrock_and_returns_the_embedding_vector():
    fake_client = FakeBedrockRuntimeClient(json.dumps({"embedding": [0.1, 0.2, 0.3]}).encode())
    provider = BedrockEmbeddingProvider(
        model_id="amazon.titan-embed-text-v2:0", region="us-east-1", client=fake_client
    )

    vector = provider.embed("Dimitri trabaja con Python")

    assert vector == [0.1, 0.2, 0.3]
    assert fake_client.last_request["modelId"] == "amazon.titan-embed-text-v2:0"
    request_body = json.loads(fake_client.last_request["body"])
    assert request_body["inputText"] == "Dimitri trabaja con Python"


def test_embed_propagates_errors_from_bedrock():
    provider = BedrockEmbeddingProvider(model_id="m", region="us-east-1", client=FailingBedrockRuntimeClient())

    with pytest.raises(RuntimeError, match="bedrock unavailable"):
        provider.embed("hello")

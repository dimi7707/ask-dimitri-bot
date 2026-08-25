import json

import boto3


class BedrockEmbeddingProvider:
    def __init__(self, model_id: str, region: str, client=None):
        self._model_id = model_id
        self._client = client or boto3.client("bedrock-runtime", region_name=region)

    def embed(self, text: str) -> list[float]:
        response = self._client.invoke_model(
            modelId=self._model_id,
            body=json.dumps({"inputText": text}),
            contentType="application/json",
            accept="application/json",
        )
        payload = json.loads(response["body"].read())
        return payload["embedding"]

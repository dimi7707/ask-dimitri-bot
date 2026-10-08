import json

import boto3


class BedrockEmbeddingProvider:
    def __init__(self, model_id: str, region: str, client=None):
        self._model_id = model_id
        self._client = client or boto3.client("bedrock-runtime", region_name=region)

    def close(self) -> None:
        """Release the client's HTTPS connection pool now instead of at GC time.

        A botocore client owns a `urllib3` pool holding sockets to the Bedrock endpoint, so an
        abandoned client keeps them until it is finalized — which is the leak the cache exists to
        avoid in the first place.
        """
        self._client.close()

    def embed(self, text: str) -> list[float]:
        response = self._client.invoke_model(
            modelId=self._model_id,
            body=json.dumps({"inputText": text}),
            contentType="application/json",
            accept="application/json",
        )
        payload = json.loads(response["body"].read())
        return payload["embedding"]

import json

import boto3
from botocore.config import Config


class BedrockEmbeddingProvider:
    def __init__(
        self,
        model_id: str,
        region: str,
        connect_timeout: float,
        read_timeout: float,
        max_attempts: int,
        client=None,
    ):
        """The call ceiling is caller-supplied because it describes the runtime, not the model.

        No defaults here on purpose: the values live in `Settings` alone, so a provider default
        cannot quietly disagree with the configured one. See `BEDROCK_CONNECT_TIMEOUT`,
        `BEDROCK_READ_TIMEOUT` and `BEDROCK_MAX_ATTEMPTS`.
        """
        self._model_id = model_id
        self._client = client or boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                # Two keys, both load-bearing. `standard` mode, because `max_attempts` alone
                # validates fine and leaves botocore's legacy backoff in place — different
                # semantics for the same number. And `total_max_attempts`, not `max_attempts`:
                # the latter counts retries *after* the initial request, so a 2 there means 3
                # calls (~33 s) and overshoots the 30 s budget this ceiling exists to fit inside.
                retries={"mode": "standard", "total_max_attempts": max_attempts},
            ),
        )

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

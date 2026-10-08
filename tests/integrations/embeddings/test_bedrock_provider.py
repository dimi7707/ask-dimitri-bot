import io
import json

import pytest

from app.core.config import get_settings
from app.integrations.embeddings import bedrock_provider
from app.integrations.embeddings import factory as embeddings_factory
from app.integrations.embeddings.bedrock_provider import BedrockEmbeddingProvider

# The call ceiling is a required constructor argument — the defaults live in `Settings`, not in the
# provider — so these tests supply values of their own rather than restating the production ones.
CALL_CEILING = {"connect_timeout": 1, "read_timeout": 2, "max_attempts": 3}


class FakeBedrockRuntimeClient:
    def __init__(self, response_body: bytes):
        self._response_body = response_body
        self.last_request: dict | None = None
        self.closed = 0

    def invoke_model(self, **kwargs):
        self.last_request = kwargs
        return {"body": io.BytesIO(self._response_body)}

    def close(self) -> None:
        self.closed += 1


class FailingBedrockRuntimeClient:
    def invoke_model(self, **kwargs):
        raise RuntimeError("bedrock unavailable")


def test_embed_calls_bedrock_and_returns_the_embedding_vector():
    fake_client = FakeBedrockRuntimeClient(json.dumps({"embedding": [0.1, 0.2, 0.3]}).encode())
    provider = BedrockEmbeddingProvider(
        model_id="amazon.titan-embed-text-v2:0", region="us-east-1", client=fake_client, **CALL_CEILING
    )

    vector = provider.embed("Dimitri trabaja con Python")

    assert vector == [0.1, 0.2, 0.3]
    assert fake_client.last_request["modelId"] == "amazon.titan-embed-text-v2:0"
    request_body = json.loads(fake_client.last_request["body"])
    assert request_body["inputText"] == "Dimitri trabaja con Python"


def test_embed_propagates_errors_from_bedrock():
    provider = BedrockEmbeddingProvider(
        model_id="m", region="us-east-1", client=FailingBedrockRuntimeClient(), **CALL_CEILING
    )

    with pytest.raises(RuntimeError, match="bedrock unavailable"):
        provider.embed("hello")


# --- adb-002 2.4 the provider releases its client -----------------------------------------


def test_close_releases_the_clients_connection_pool():
    """The provider is cached for the life of the process, so the cache dropping it is the only
    moment its `urllib3` pool can be released deterministically rather than at GC time."""
    fake_client = FakeBedrockRuntimeClient(b"{}")
    provider = BedrockEmbeddingProvider(model_id="m", region="us-east-1", client=fake_client, **CALL_CEILING)

    provider.close()

    assert fake_client.closed == 1


# --- adb-002 4.x the client is built with a bounded call ceiling ---------------------------


def capture_boto3_client_kwargs(monkeypatch) -> dict:
    """Record what the provider passes to `boto3.client`, asserting on our own call site.

    The alternative is reading the built client's `meta` or `_client_config`, which are botocore
    internals: a rename upstream would turn these tests into `AttributeError` rather than a
    meaningful failure.

    The residual blind spot is recorded rather than hidden: this asserts what we *pass*, so nothing
    here would notice a future change that moved the effective ceiling by another route.
    """
    captured: dict = {}

    class RecordingBoto3:
        @staticmethod
        def client(service_name, **kwargs):
            captured["service_name"] = service_name
            captured.update(kwargs)
            return FakeBedrockRuntimeClient(b"{}")

    monkeypatch.setattr(bedrock_provider, "boto3", RecordingBoto3)
    return captured


def test_the_client_is_built_with_the_supplied_timeouts_and_attempt_count(monkeypatch):
    captured = capture_boto3_client_kwargs(monkeypatch)

    BedrockEmbeddingProvider(model_id="m", region="us-east-1", connect_timeout=3, read_timeout=8, max_attempts=2)

    assert captured["service_name"] == "bedrock-runtime"
    config = captured["config"]
    assert config.connect_timeout == 3
    assert config.read_timeout == 8
    assert config.retries["total_max_attempts"] == 2


def test_the_clients_retry_mode_is_standard_not_botocores_legacy_default(monkeypatch):
    """An attempt count alone validates fine and leaves botocore's legacy backoff in place, which
    changes what the number means — so the mode is part of the contract, not decoration."""
    captured = capture_boto3_client_kwargs(monkeypatch)

    BedrockEmbeddingProvider(model_id="m", region="us-east-1", **CALL_CEILING)

    assert captured["config"].retries["mode"] == "standard"


def test_the_attempt_count_bounds_total_calls_not_retries_after_the_first(monkeypatch):
    """`BEDROCK_MAX_ATTEMPTS=2` has to mean two calls, which is the arithmetic the ceiling rests on.

    botocore has two keys for this and they differ by one: `max_attempts` counts retries *after* the
    initial request, so passing 2 there would permit three calls (~33 s) and overshoot the 30 s
    budget. `total_max_attempts` includes the initial request, and botocore's own documentation
    prefers it for that reason. This asserts the key, because the wrong one still validates.
    """
    captured = capture_boto3_client_kwargs(monkeypatch)

    BedrockEmbeddingProvider(model_id="m", region="us-east-1", connect_timeout=3, read_timeout=8, max_attempts=2)

    assert captured["config"].retries == {"mode": "standard", "total_max_attempts": 2}


@pytest.fixture
def fresh_settings():
    """`get_settings` is `lru_cache`d, so an env-var test has to drop the memoized Settings."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_the_call_ceiling_flows_from_the_environment_to_the_client(monkeypatch, fresh_settings):
    """The end-to-end path: env var -> Settings -> factory -> client.

    Covering only the halves — that `Settings` reads the variable, and that the provider forwards
    what it is given — would leave the wiring between them untested, which is where a value gets
    dropped.
    """
    captured = capture_boto3_client_kwargs(monkeypatch)
    monkeypatch.setenv("BEDROCK_READ_TIMEOUT", "11")
    monkeypatch.setenv("BEDROCK_MAX_ATTEMPTS", "4")

    embeddings_factory.get_embedding_provider()

    assert captured["config"].read_timeout == 11
    assert captured["config"].retries["total_max_attempts"] == 4

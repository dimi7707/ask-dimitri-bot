import pytest

from app.core.config import Settings
from app.integrations.embeddings import factory as embeddings_factory
from app.integrations.embeddings.base import EmbeddingProvider


class FakeEmbeddingProvider:
    def embed(self, text: str) -> list[float]:
        return [float(len(text)), 0.0, 1.0]


def test_fake_embedding_provider_satisfies_the_protocol():
    assert isinstance(FakeEmbeddingProvider(), EmbeddingProvider)


def test_get_embedding_provider_dispatches_to_the_configured_provider(monkeypatch):
    monkeypatch.setitem(embeddings_factory.PROVIDERS, "fake", FakeEmbeddingProvider)
    settings = Settings(_env_file=None, embedding_provider="fake")

    provider = embeddings_factory.get_embedding_provider(settings=settings)

    assert isinstance(provider, FakeEmbeddingProvider)


def test_get_embedding_provider_defaults_to_bedrock():
    from app.integrations.embeddings.bedrock_provider import BedrockEmbeddingProvider

    provider = embeddings_factory.get_embedding_provider(settings=Settings(_env_file=None))

    assert isinstance(provider, BedrockEmbeddingProvider)


def test_get_embedding_provider_raises_on_unregistered_provider():
    settings = Settings(_env_file=None, embedding_provider="does-not-exist")

    with pytest.raises(ValueError, match="does-not-exist"):
        embeddings_factory.get_embedding_provider(settings=settings)


def test_fake_embedding_provider_embeds_text_into_a_vector():
    provider = FakeEmbeddingProvider()

    vector = provider.embed("hello")

    assert vector == [5.0, 0.0, 1.0]

import pytest

from app.core.config import Settings
from app.integrations.generation import factory as generation_factory
from app.integrations.generation.base import GenerationProvider


class FakeGenerationProvider:
    def generate(self, system_prompt: str, question: str, context: list[str]) -> str:
        return f"answer to '{question}' using {len(context)} context chunk(s)"


def test_fake_generation_provider_satisfies_the_protocol():
    assert isinstance(FakeGenerationProvider(), GenerationProvider)


def test_get_generation_provider_dispatches_to_the_configured_provider(monkeypatch):
    monkeypatch.setitem(generation_factory.PROVIDERS, "fake", FakeGenerationProvider)
    settings = Settings(_env_file=None, llm_provider="fake")

    provider = generation_factory.get_generation_provider(settings=settings)

    assert isinstance(provider, FakeGenerationProvider)


def test_get_generation_provider_defaults_to_bedrock():
    from app.integrations.generation.bedrock_provider import BedrockGenerationProvider

    provider = generation_factory.get_generation_provider(settings=Settings(_env_file=None))

    assert isinstance(provider, BedrockGenerationProvider)


def test_get_generation_provider_raises_on_unregistered_provider():
    settings = Settings(_env_file=None, llm_provider="does-not-exist")

    with pytest.raises(ValueError, match="does-not-exist"):
        generation_factory.get_generation_provider(settings=settings)


def test_fake_generation_provider_generates_an_answer_from_context():
    provider = FakeGenerationProvider()

    answer = provider.generate("system prompt", "What stack?", ["chunk one", "chunk two"])

    assert answer == "answer to 'What stack?' using 2 context chunk(s)"

from typing import Protocol, runtime_checkable


@runtime_checkable
class GenerationProvider(Protocol):
    """Prompt + context -> answer — implemented by Bedrock today, swappable to any chat model."""

    def generate(self, system_prompt: str, question: str, context: list[str]) -> str: ...

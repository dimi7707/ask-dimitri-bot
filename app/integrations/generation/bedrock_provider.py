from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage

NO_CONTEXT_PLACEHOLDER = "(no se recuperó contexto para esta pregunta)"


class BedrockGenerationProvider:
    def __init__(self, model_id: str, region: str, chat_model=None):
        self._chat_model = chat_model or ChatBedrock(model=model_id, region=region)

    def generate(self, system_prompt: str, question: str, context: list[str]) -> str:
        message = self._chat_model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=self._build_user_message(question, context)),
            ]
        )
        return message.content

    def _build_user_message(self, question: str, context: list[str]) -> str:
        """Delimit retrieved chunks so their text reads as reference data, never as instructions."""
        chunks = "\n\n".join(context) if context else NO_CONTEXT_PLACEHOLDER
        return f"<context>\n{chunks}\n</context>\n\n<question>\n{question}\n</question>"

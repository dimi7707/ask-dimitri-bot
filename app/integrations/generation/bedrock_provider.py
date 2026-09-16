from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage

NO_CONTEXT_PLACEHOLDER = "(no se recuperó contexto para esta pregunta)"


class BedrockGenerationProvider:
    def __init__(self, model_id: str, region: str, chat_model=None):
        self._model_id = model_id
        self._region = region
        self._chat_model = chat_model

    def generate(self, system_prompt: str, question: str, context: list[str]) -> str:
        message = self._get_chat_model().invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=self._build_user_message(question, context)),
            ]
        )
        return message.content

    def _get_chat_model(self):
        """Build the Bedrock client on first use, then reuse it.

        Constructing ChatBedrock resolves AWS credentials, which blocks for ~90s on a machine
        that has none — doing it in __init__ would make simply resolving the provider hang.
        """
        if self._chat_model is None:
            self._chat_model = ChatBedrock(model=self._model_id, region=self._region)
        return self._chat_model

    def _build_user_message(self, question: str, context: list[str]) -> str:
        """Delimit retrieved chunks so their text reads as reference data, never as instructions."""
        chunks = "\n\n".join(context) if context else NO_CONTEXT_PLACEHOLDER
        return f"<context>\n{chunks}\n</context>\n\n<question>\n{question}\n</question>"

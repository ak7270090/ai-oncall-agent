from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from config import Settings


class LLMError(Exception):
    pass


def create_chat_model(settings: Settings) -> BaseChatModel:
    """Build the chat model from config. `llm_model` is "<provider>:<model>", e.g.
    "openai:gpt-5.4-mini" or "anthropic:claude-opus-5"; no provider-specific code needed."""
    credentials = {"api_key": settings.llm_api_key.get_secret_value()} if settings.llm_api_key else {}
    return init_chat_model(
        settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        **credentials,
    )

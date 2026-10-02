from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import SecretStr

from config import Settings


class LLMError(Exception):
    pass


def create_chat_model(settings: Settings, model: str | None = None, api_key: SecretStr | None = None) -> BaseChatModel:
    """Build a chat model from config: `model` (default LLM_MODEL) is "<provider>:<model>",
    e.g. "openai:gpt-5.4-mini" or "anthropic:claude-opus-5"; no provider-specific code."""
    model = model or settings.llm_model
    key = api_key or settings.llm_api_key
    credentials = {"api_key": key.get_secret_value()} if key else {}
    try:
        return init_chat_model(
            model,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            **credentials,
        )
    except Exception as error:
        raise LLMError(f"Could not create chat model '{model}' (check the model name and API key): {error}") from error


async def invoke_llm(runnable: Any, messages: list[BaseMessage]) -> Any:
    """Call a chat model (plain, tool-bound or structured); any provider failure becomes LLMError."""
    try:
        return await runnable.ainvoke(messages)
    except Exception as error:
        raise LLMError(f"LLM call failed: {error}") from error

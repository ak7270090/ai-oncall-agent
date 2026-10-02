from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from langchain_core.language_models import BaseChatModel
from mcp import Client

from agent import create_chat_model
from config import Settings, get_settings
from mcp_client import connect_to_mcp
from tracing import InvestigationTracer, create_tracer

MCPConnector = Callable[[], AbstractAsyncContextManager[Client]]


@lru_cache
def get_chat_model() -> BaseChatModel:
    return create_chat_model(get_settings())


def get_tracer(settings: Annotated[Settings, Depends(get_settings)]) -> InvestigationTracer:
    # Langfuse keeps one client per public key, so this is cheap after the first call.
    return create_tracer(settings)


def get_mcp_connector(settings: Annotated[Settings, Depends(get_settings)]) -> MCPConnector:
    return lambda: connect_to_mcp(settings.mcp_server_url, settings.mcp_timeout_seconds)


SettingsDep = Annotated[Settings, Depends(get_settings)]
ChatModelDep = Annotated[BaseChatModel, Depends(get_chat_model)]
MCPConnectorDep = Annotated[MCPConnector, Depends(get_mcp_connector)]
TracerDep = Annotated[InvestigationTracer, Depends(get_tracer)]

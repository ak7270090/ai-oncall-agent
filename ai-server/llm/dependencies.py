from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from config import get_settings
from llm.model_router import ModelRouter, create_model_router


@lru_cache
def get_model_router() -> ModelRouter:
    return create_model_router(get_settings())


ModelRouterDep = Annotated[ModelRouter, Depends(get_model_router)]

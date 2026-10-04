from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from actions.registry import ActionRegistry
from config import get_settings


@lru_cache
def get_action_registry() -> ActionRegistry:
    settings = get_settings()
    return ActionRegistry(settings.approval_timeout_seconds, require_second_person=bool(settings.api_keys))


ActionRegistryDep = Annotated[ActionRegistry, Depends(get_action_registry)]

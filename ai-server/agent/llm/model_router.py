"""Model routing: each task goes to the cheapest model tier that does it well.

Two tiers (constants.ModelTier): strong (LLM_MODEL) and fast (LLM_MODEL_FAST, optional).
- Static routing for our own graph steps: steps listed in FAST_MODEL_STEPS use the fast
  model, all others the strong one.
- Preference-based routing for MCP sampling requests: the MCP server describes what it
  needs (model name hints; cost / speed / intelligence priorities, 0-1) and the router
  maps that to a configured tier.
Without a fast model, everything uses the strong model."""

from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from mcp_types import ModelPreferences

from agent.llm.chat_model import create_chat_model
from config import Settings
from constants import ModelTier


@dataclass(frozen=True)
class ModelRouter:
    strong: BaseChatModel
    strong_name: str
    fast: BaseChatModel | None = None
    fast_name: str | None = None
    fast_steps: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def single(cls, model: BaseChatModel, name: str = "") -> "ModelRouter":
        """One model for everything."""
        return cls(strong=model, strong_name=name)

    def model(self, tier: ModelTier) -> BaseChatModel:
        return self.fast if tier == ModelTier.FAST and self.fast is not None else self.strong

    def name(self, tier: ModelTier) -> str:
        return (self.fast_name or "") if tier == ModelTier.FAST and self.fast is not None else self.strong_name

    def tier_for_step(self, step: str) -> ModelTier:
        return ModelTier.FAST if self.fast is not None and step in self.fast_steps else ModelTier.STRONG

    def for_step(self, step: str) -> BaseChatModel:
        return self.model(self.tier_for_step(step))

    def tier_for_preferences(self, preferences: ModelPreferences | None) -> ModelTier:
        if self.fast is None or preferences is None:
            return ModelTier.STRONG
        for hint in preferences.hints or []:
            # A hint is a substring of a model name, e.g. "nano" or "gpt-5.4".
            if hint.name and hint.name in (self.fast_name or ""):
                return ModelTier.FAST
            if hint.name and hint.name in self.strong_name:
                return ModelTier.STRONG
        cheap_or_fast = max(preferences.cost_priority or 0, preferences.speed_priority or 0)
        return ModelTier.FAST if cheap_or_fast > (preferences.intelligence_priority or 0) else ModelTier.STRONG


def create_model_router(settings: Settings) -> ModelRouter:
    fast = None
    if settings.llm_model_fast:
        fast = create_chat_model(settings, settings.llm_model_fast, settings.llm_fast_api_key)
    return ModelRouter(
        strong=create_chat_model(settings), strong_name=settings.llm_model,
        fast=fast, fast_name=settings.llm_model_fast, fast_steps=frozenset(settings.fast_model_steps),
    )

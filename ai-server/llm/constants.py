"""LLM tiers and limits."""

from enum import StrEnum


class ModelTier(StrEnum):
    """Strong: the configured LLM_MODEL, for reasoning. Fast: LLM_MODEL_FAST, a cheaper
    and faster model for simple tasks (log summaries); falls back to strong when unset."""

    STRONG = "strong"
    FAST = "fast"


# Sampling requests carry max_tokens; reasoning models count hidden reasoning tokens in
# their output limit, so the limit is applied to the answer text instead, at roughly
# this many characters per token.
APPROX_CHARS_PER_TOKEN = 4

# Shown to API callers instead of provider error details (which go to the server log).
LLM_FAILURE_MESSAGE = "The LLM provider request failed. See server logs for details."

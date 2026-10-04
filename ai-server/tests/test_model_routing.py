import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from mcp_types import (
    CreateMessageRequestParams,
    ErrorData,
    ModelHint,
    ModelPreferences,
    SamplingMessage,
    TextContent,
)

from config import Settings
from investigation.constants import Step
from investigation.evidence.mcp_toolbox import MCPToolbox
from investigation.service import run_investigation
from investigation.workflow.graph import build_investigation_graph
from llm.constants import ModelTier
from llm.model_router import ModelRouter
from llm.sampling import SamplingResponder
from mcp_client.langchain_tools import list_all_tools, to_langchain_tool
from tests.fakes import (
    PAYMENT_DOWN,
    build_fake_mcp_server,
    fake_connector,
    scripted_model,
)

STRONG, FAST = "openai:gpt-5.4-mini", "openai:gpt-5.4-nano"
CHEAP = ModelPreferences(cost_priority=0.8, speed_priority=0.7, intelligence_priority=0.2)
SMART = ModelPreferences(cost_priority=0.2, intelligence_priority=0.9)


def router(fast_steps=(), with_fast=True, fast_replies=("a short summary",)) -> ModelRouter:
    fast = GenericFakeChatModel(messages=iter(fast_replies)) if with_fast else None
    return ModelRouter(strong=GenericFakeChatModel(messages=iter(["strong answer"])), strong_name=STRONG,
                       fast=fast, fast_name=FAST if with_fast else None, fast_steps=frozenset(fast_steps))


def sampling_request(preferences: ModelPreferences | None, max_tokens: int = 100) -> CreateMessageRequestParams:
    return CreateMessageRequestParams(
        messages=[SamplingMessage(role="user", content=TextContent(type="text", text="ERROR x\nERROR x"))],
        max_tokens=max_tokens, model_preferences=preferences, metadata={"task": "summarize_pod_logs"})


@pytest.mark.parametrize("preferences, tier", [
    (CHEAP, ModelTier.FAST),
    (SMART, ModelTier.STRONG),
    (None, ModelTier.STRONG),
    (ModelPreferences(hints=[ModelHint(name="nano")], intelligence_priority=1.0), ModelTier.FAST),
    (ModelPreferences(hints=[ModelHint(name="mini")], cost_priority=1.0), ModelTier.STRONG),
])
def test_preferences_pick_a_tier(preferences, tier):
    assert router().tier_for_preferences(preferences) == tier


def test_steps_use_the_fast_model_only_when_listed_and_configured():
    assert router(fast_steps=[Step.WRITE_REPORT]).tier_for_step(Step.WRITE_REPORT) == ModelTier.FAST
    assert router(fast_steps=[Step.WRITE_REPORT]).tier_for_step(Step.FIND_ROOT_CAUSE) == ModelTier.STRONG
    without_fast = router(fast_steps=[Step.WRITE_REPORT], with_fast=False)
    assert without_fast.tier_for_step(Step.WRITE_REPORT) == ModelTier.STRONG
    assert without_fast.tier_for_preferences(CHEAP) == ModelTier.STRONG


@pytest.mark.anyio
async def test_sampling_is_answered_by_the_routed_model_and_capped():
    responder = SamplingResponder(router(), max_requests=1)
    answer = await responder(None, sampling_request(CHEAP))
    assert answer.model == FAST and answer.content.text == "a short summary"
    refused = await responder(None, sampling_request(CHEAP))
    assert isinstance(refused, ErrorData)


@pytest.mark.anyio
async def test_sampling_answer_is_cut_to_max_tokens_and_failures_become_errors():
    long_answer = await SamplingResponder(router(fast_replies=["x" * 1000]), 5)(None, sampling_request(CHEAP, max_tokens=10))
    assert len(long_answer.content.text) == 40
    failing = await SamplingResponder(router(fast_replies=[]), 5)(None, sampling_request(CHEAP))
    assert isinstance(failing, ErrorData)


@pytest.mark.anyio
async def test_investigation_summarizes_logs_with_the_fast_model():
    settings = Settings(_env_file=None, summarize_logs=True)
    models = ModelRouter(strong=scripted_model(), strong_name=STRONG,
                         fast=GenericFakeChatModel(messages=iter(["1x upstream unavailable: payment-service"] * 5)),
                         fast_name=FAST)
    sampling = SamplingResponder(models, settings.max_samplings_per_investigation)
    async with fake_connector(build_fake_mcp_server(PAYMENT_DOWN))(sampling) as mcp_client:
        tools = await list_all_tools(mcp_client)
        graph = build_investigation_graph(models, MCPToolbox(mcp_client, tools),
                                          [to_langchain_tool(mcp_client, t) for t in tools], settings)
        result = await run_investigation(graph, "Checkout is failing", settings.max_follow_up_rounds, sampling=sampling)

    [logs] = [e for e in result.evidence if e.source == "get_pod_logs"]
    assert logs.arguments["summarize"] is True
    assert logs.result["summarized_by"] == FAST
    assert "payment-service" in logs.result["summary"]
    assert result.report.root_cause_service == "payment-service"

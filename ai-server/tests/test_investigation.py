import pytest

from agent import ToolCallRecord, build_investigation_graph, run_investigation
from agent.investigation import INCOMPLETE_ANSWER
from mcp_client import load_langchain_tools
from tests.fakes import (build_fake_mcp_server, endless_tool_calls_model, fake_connector,
                         scripted_model, tool_call_message)

pytestmark = pytest.mark.anyio
MAX_AGENT_STEPS = 4


async def investigate_with(chat_model, question="Why is checkout failing?"):
    async with fake_connector(build_fake_mcp_server())() as mcp_client:
        graph = build_investigation_graph(chat_model, await load_langchain_tools(mcp_client))
        return await run_investigation(graph, question, MAX_AGENT_STEPS)


async def test_answers_without_tools():
    result = await investigate_with(scripted_model("All good."))
    assert (result.answer, result.completed, result.llm_calls, result.tool_calls) == (
        "All good.", True, 1, []
    )


async def test_tool_results_reach_the_model_and_are_recorded():
    result = await investigate_with(scripted_model(
        tool_call_message(("get_pod_status", {"service": "payment-service"})),
        "Payment pods are crash-looping.",
    ))
    assert result.answer == "Payment pods are crash-looping."
    assert result.llm_calls == 2
    assert result.tool_calls == [
        ToolCallRecord(tool="get_pod_status", arguments={"service": "payment-service"}, is_error=False)
    ]


async def test_parallel_and_failing_tool_calls():
    result = await investigate_with(scripted_model(
        tool_call_message(("get_pod_status", {"service": "a"}), ("get_logs", {"service": "a"})),
        "done",
    ))
    assert [(c.tool, c.is_error) for c in result.tool_calls] == [
        ("get_pod_status", False), ("get_logs", True)
    ]


async def test_stops_at_step_limit():
    result = await investigate_with(endless_tool_calls_model())
    assert result.completed is False
    assert result.answer == INCOMPLETE_ANSWER
    assert result.llm_calls == MAX_AGENT_STEPS

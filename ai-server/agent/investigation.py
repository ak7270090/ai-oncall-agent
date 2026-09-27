from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph

INCOMPLETE_ANSWER = "Stopped after reaching the step limit without a conclusion."


@dataclass(frozen=True)
class ToolCallRecord:
    tool: str
    arguments: dict
    is_error: bool


@dataclass(frozen=True)
class InvestigationResult:
    answer: str
    completed: bool
    llm_calls: int
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


def _recursion_limit(max_agent_steps: int) -> int:
    # Each step is one model node plus one tools node.
    return 2 * max_agent_steps


def _summarize(messages: list[BaseMessage], completed: bool) -> InvestigationResult:
    failed_call_ids = {
        m.tool_call_id for m in messages if isinstance(m, ToolMessage) and m.status == "error"
    }
    model_messages = [m for m in messages if isinstance(m, AIMessage)]
    tool_calls = [
        ToolCallRecord(tool=call["name"], arguments=call["args"], is_error=call["id"] in failed_call_ids)
        for message in model_messages
        for call in message.tool_calls
    ]
    answer = model_messages[-1].text if completed and model_messages else INCOMPLETE_ANSWER
    return InvestigationResult(
        answer=answer, completed=completed, llm_calls=len(model_messages), tool_calls=tool_calls
    )


async def run_investigation(
    graph: CompiledStateGraph, question: str, max_agent_steps: int
) -> InvestigationResult:
    messages: list[BaseMessage] = [HumanMessage(question)]
    completed = True
    try:
        async for state in graph.astream(
            {"messages": messages},
            {"recursion_limit": _recursion_limit(max_agent_steps)},
            stream_mode="values",
        ):
            messages = state["messages"]
    except GraphRecursionError:
        completed = False
    return _summarize(messages, completed)

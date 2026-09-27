from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent.chat_model import LLMError
from agent.prompts import SYSTEM_PROMPT

CALL_MODEL = "call_model"
CALL_TOOLS = "call_tools"


def build_investigation_graph(chat_model: BaseChatModel, tools: list[BaseTool]) -> CompiledStateGraph:
    model_with_tools = chat_model.bind_tools(tools)
    system_message = SystemMessage(SYSTEM_PROMPT)

    async def call_model(state: MessagesState) -> dict:
        try:
            response = await model_with_tools.ainvoke([system_message, *state["messages"]])
        except Exception as error:
            raise LLMError(f"LLM call failed: {error}") from error
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node(CALL_MODEL, call_model)
    graph.add_node(CALL_TOOLS, ToolNode(tools))
    graph.add_edge(START, CALL_MODEL)
    graph.add_conditional_edges(CALL_MODEL, tools_condition, {"tools": CALL_TOOLS, END: END})
    graph.add_edge(CALL_TOOLS, CALL_MODEL)
    return graph.compile()

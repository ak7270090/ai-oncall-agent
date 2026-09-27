from pydantic import BaseModel, Field

from config import get_settings


class InvestigateRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=get_settings().max_question_length,
        examples=["Checkout is failing, what's wrong with payments?"],
    )


class ToolCallResponse(BaseModel):
    tool: str
    arguments: dict
    is_error: bool


class InvestigateResponse(BaseModel):
    answer: str
    completed: bool
    llm_calls: int
    tool_calls: list[ToolCallResponse]


class ToolDescription(BaseModel):
    name: str
    description: str
    input_schema: dict


class ToolsResponse(BaseModel):
    tools: list[ToolDescription]


class StatusResponse(BaseModel):
    status: str

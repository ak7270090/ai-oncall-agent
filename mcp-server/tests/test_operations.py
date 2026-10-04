import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp_types import ElicitResult

from config import Settings
from fake.operations import FakeOperations
from server import create_server

pytestmark = pytest.mark.anyio
WRITE_TOOLS = {"restart_deployment", "scale_deployment", "rollback_deployment"}


class Human:
    """Answers approval questions like a person would, and remembers what was asked."""

    def __init__(self, answer: ElicitResult):
        self.answer = answer
        self.questions: list[str] = []

    async def __call__(self, context, params):
        self.questions.append(params.message)
        return self.answer


APPROVE = ElicitResult(action="accept", content={"approve": True, "reason": "bad release", "approver": "bob"})
REJECT = ElicitResult(action="accept", content={"approve": False, "reason": "not during peak hours", "approver": "bob"})


def server_with_write_tools(operations: FakeOperations):
    return create_server(Settings(_env_file=None, backend="fake", enable_write_tools=True), operations=operations)


async def call(human: Human | None, tool: str, arguments: dict, operations: FakeOperations):
    async with Client(server_with_write_tools(operations), elicitation_callback=human) as client:
        return await client.call_tool(tool, arguments)


async def test_write_tools_are_off_by_default_and_destructive_when_on():
    async with Client(create_server(Settings(_env_file=None, backend="fake"))) as client:
        assert not WRITE_TOOLS & {t.name for t in (await client.list_tools()).tools}
    async with Client(server_with_write_tools(FakeOperations())) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in WRITE_TOOLS:
        assert tools[name].annotations.destructive_hint is True and tools[name].annotations.read_only_hint is False


async def test_approved_change_is_made_once_and_reported():
    operations, human = FakeOperations(), Human(APPROVE)
    result = (await call(human, "rollback_deployment", {"name": "payment-service", "revision": 1}, operations)).structured_content
    assert human.questions == ["Roll back deployment payment-service in shop to revision 1 (image payment-service:v2.3.1)?"]
    assert operations.performed == ["Rolled back deployment payment-service to the pod template of revision 1."]
    assert result["done"] is True and result["approval"] == "approved" and result["approval_reason"] == "bad release"


@pytest.mark.parametrize("answer, state", [(REJECT, "rejected"), (ElicitResult(action="decline"), "declined"),
                                           (ElicitResult(action="cancel"), "cancelled")])
async def test_no_approval_no_change(answer, state):
    operations = FakeOperations()
    result = (await call(Human(answer), "scale_deployment", {"name": "payment-service", "replicas": 2}, operations)).structured_content
    assert operations.performed == []
    assert result["done"] is False and result["approval"] == state


@pytest.mark.parametrize("tool, arguments, message", [
    ("scale_deployment", {"name": "payment-service", "replicas": 9}, "less than or equal to 5"),
    ("rollback_deployment", {"name": "payment-service", "revision": 99}, "has no revision 99"),
    ("restart_deployment", {"name": "no-such-service"}, "Not found"),
    ("restart_deployment", {"name": "payment-service", "namespace": "kube-system"}, "not allowed"),
])
async def test_bad_arguments_are_refused_before_anyone_is_asked(tool, arguments, message):
    operations, human = FakeOperations(), Human(APPROVE)
    result = await call(human, tool, arguments, operations)
    assert result.is_error and message in result.content[0].text
    assert human.questions == [] and operations.performed == []


def innermost(error: BaseException) -> BaseException:
    while isinstance(error, BaseExceptionGroup):  # mcp.Client wraps errors in groups
        error = error.exceptions[0]
    return error


async def test_a_client_that_cannot_ask_a_human_cannot_change_anything():
    operations = FakeOperations()
    with pytest.raises(BaseException) as raised:
        await call(None, "restart_deployment", {"name": "payment-service"}, operations)
    assert isinstance(innermost(raised.value), MCPError)
    assert "elicitation capability" in str(innermost(raised.value))
    assert operations.performed == []

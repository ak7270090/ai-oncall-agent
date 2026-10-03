"""Stand-ins for the LLM and the MCP server. Nothing is imported from mcp-server/:
the fake server only mirrors the tool names and result shapes the graph relies on."""

from itertools import count
from typing import Annotated, Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.server.mcpserver.resolve import Resolve, Sample
from mcp_types import (
    CreateMessageResult,
    ModelPreferences,
    SamplingMessage,
    TextContent,
    ToolAnnotations,
)

from agent import IncidentReport, IncidentScope
from agent.models import EvidenceCitation
from mcp_client import connect_to_mcp

TEST_MCP_TIMEOUT_SECONDS = 5
NAMESPACE = "shop"
OVERVIEW_METRICS = ("request_rate", "error_rate", "latency_p99_ms")
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False)
RUNBOOKS = {"payment-service": "# payment-service\nDepends on: payments-db. `upstream unavailable` "
                                "in order-service logs means payment-service has no ready pods."}
TOPOLOGY = {"order-service": {"calls": ["user-service", "payment-service"]},
            "payment-service": {"calls": ["payments-db"]}}
_call_ids = count()

PAYMENT_DOWN: dict[str, Any] = {
    "pods": [
        {"name": "order-service-a", "app": "order-service", "status": "Running", "ready": True, "restarts": 0},
        {"name": "user-service-a", "app": "user-service", "status": "Running", "ready": True, "restarts": 0},
    ],
    "overview": [
        {"service": "order-service", "request_rate_per_second": 1.0, "error_rate": 0.7, "latency_p99_ms": 40},
        {"service": "user-service", "request_rate_per_second": 1.0, "error_rate": 0.0, "latency_p99_ms": 9},
    ],
    "deployments": [
        {"name": "order-service", "desired_replicas": 2, "ready_replicas": 2, "updated_replicas": 2},
        {"name": "payment-service", "desired_replicas": 0, "ready_replicas": 0, "updated_replicas": 0},
        {"name": "user-service", "desired_replicas": 2, "ready_replicas": 2, "updated_replicas": 2},
    ],
    "logs": {"order-service-a": [
        'INFO: "POST /orders HTTP/1.1" 502 Bad Gateway',
        "ERROR: upstream unavailable: POST http://payment-service/payments (ConnectError('refused'))",
        "INFO: fetched profile from http://user-service/users/1",
    ]},
    "previous_logs": {},
}

PAYMENT_CRASHLOOP: dict[str, Any] = {
    "pods": [
        {"name": "payment-service-x", "app": "payment-service", "status": "CrashLoopBackOff", "ready": False, "restarts": 7},
        {"name": "order-service-a", "app": "order-service", "status": "Running", "ready": True, "restarts": 0},
    ],
    "overview": [{"service": "order-service", "request_rate_per_second": 1.0, "error_rate": 0.01, "latency_p99_ms": 40}],
    "deployments": [
        {"name": "payment-service", "desired_replicas": 2, "ready_replicas": 0, "updated_replicas": 2},
        {"name": "order-service", "desired_replicas": 2, "ready_replicas": 2, "updated_replicas": 2},
    ],
    "logs": {"payment-service-x": ["INFO starting"], "order-service-a": []},
    "previous_logs": {"payment-service-x": ["ERROR could not resolve host payments-db", "exit code 1"]},
}


def build_fake_mcp_server(incident: dict[str, Any], with_metrics: bool = True, with_knowledge: bool = True,
                          with_write_tool: bool = False) -> MCPServer:
    server = MCPServer("fake-mcp-server")

    if with_knowledge:
        @server.resource("runbook://{service}", mime_type="text/markdown")
        def runbook(service: str) -> str:
            if service not in RUNBOOKS:
                raise ResourceError(f"No runbook for '{service}'")
            return RUNBOOKS[service]

        @server.resource("topology://{namespace}", mime_type="application/json")
        def topology(namespace: str) -> dict:
            return TOPOLOGY

    if with_write_tool:
        @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True))
        def scale_deployment(name: str, replicas: int, namespace: str = NAMESPACE) -> dict:
            """Scale a deployment."""
            return {"name": name, "replicas": replicas}

    @server.tool(annotations=READ_ONLY)
    def list_pods(namespace: str = NAMESPACE, app: str | None = None) -> dict:
        """Pods."""
        return {"namespace": namespace, "pods": [p for p in incident["pods"] if app is None or p["app"] == app]}

    @server.tool(annotations=READ_ONLY)
    def get_pod_status(pod: str, namespace: str = NAMESPACE) -> dict:
        """Pod status."""
        return next(p for p in incident["pods"] if p["name"] == pod)

    def request_log_summary(ctx: Context, pod: str, previous: bool, summarize: bool) -> Sample | None:
        if not summarize or not (ctx.client_capabilities and ctx.client_capabilities.sampling):
            return None
        source = incident["previous_logs"] if previous else incident["logs"]
        text = "\n".join(source.get(pod, []))
        return Sample([SamplingMessage(role="user", content=TextContent(type="text", text=text))], max_tokens=200,
                      model_preferences=ModelPreferences(cost_priority=0.8, intelligence_priority=0.2),
                      metadata={"task": "summarize_pod_logs"})

    @server.tool(annotations=READ_ONLY)
    def get_pod_logs(pod: str, namespace: str = NAMESPACE, lines: int = 50, previous: bool = False,
                     summarize: bool = False,
                     summary: Annotated[CreateMessageResult | None, Resolve(request_log_summary)] = None) -> dict:
        """Pod logs."""
        source = incident["previous_logs"] if previous else incident["logs"]
        if pod not in source:
            raise ToolError(f"Pod '{pod}' has no previous (crashed) container")
        if summary is not None:
            return {"pod": pod, "previous": previous, "lines": source[pod][-1:],
                    "summary": summary.content.text, "summarized_by": summary.model}
        return {"pod": pod, "previous": previous, "lines": source[pod][-lines:]}

    @server.tool(annotations=READ_ONLY)
    def list_deployments(namespace: str = NAMESPACE) -> dict:
        """Deployments."""
        return {"namespace": namespace, "deployments": incident["deployments"]}

    @server.tool(annotations=READ_ONLY)
    def get_deployment(name: str, namespace: str = NAMESPACE) -> dict:
        """Deployment with rollout history."""
        deployment = next(d for d in incident["deployments"] if d["name"] == name)
        return {**deployment, "revisions": [{"revision": 1, "ready_replicas": deployment["ready_replicas"]}]}

    @server.tool(annotations=READ_ONLY)
    def list_events(namespace: str = NAMESPACE, warnings_only: bool = True, limit: int = 20) -> dict:
        """Events."""
        return {"namespace": namespace, "events": [{"type": "Warning", "reason": "BackOff", "object": "Pod/x"}]}

    if with_metrics:
        @server.tool(annotations=READ_ONLY)
        async def get_service_overview(ctx: Context, namespace: str = NAMESPACE) -> dict:
            """Service health."""
            for done, metric in enumerate(OVERVIEW_METRICS, start=1):
                await ctx.report_progress(done, len(OVERVIEW_METRICS), f"{metric} queried")
            return {"namespace": namespace, "window": "1m", "services": incident["overview"]}

        @server.tool(annotations=READ_ONLY)
        def get_metrics(service: str, metric: str, namespace: str = NAMESPACE, minutes: int = 15) -> dict:
            """Metric history."""
            return {"service": service, "metric": metric, "samples": [{"time": "t0", "value": 0.0}, {"time": "t1", "value": 0.7}]}

    return server


def fake_connector(server: MCPServer):
    return lambda sampling_callback=None: connect_to_mcp(server, TEST_MCP_TIMEOUT_SECONDS, sampling_callback)


def tool_call_message(*calls: tuple[str, dict]) -> AIMessage:
    return AIMessage(content="", tool_calls=[
        {"name": name, "args": args, "id": f"call_{next(_call_ids)}", "type": "tool_call"}
        for name, args in calls
    ])


def scope(*suspected: str) -> IncidentScope:
    return IncidentScope(namespace=None, suspected_services=list(suspected), symptom="checkout fails", window_minutes=15)


def report(cause: str = "payment-service has no pods") -> IncidentReport:
    return IncidentReport(
        incident="Checkout failing", cause_category="dependency_unavailable", root_cause_service="payment-service",
        impact="Orders fail",
        evidence=[EvidenceCitation(source="get_pod_logs", finding="upstream unavailable: payment-service")],
        likely_cause=cause, confidence="high", recommended_actions=["Scale payment-service back up"],
        timeline=["10:00 error rate rises"],
    )


class ScriptedChatModel(GenericFakeChatModel):
    """Replays scripted replies: `structured_replies` for with_structured_output calls,
    `messages` for tool-calling calls. Tool binding is a no-op."""

    structured_replies: list = []

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        def next_reply(_messages):
            reply = self.structured_replies.pop(0)
            assert isinstance(reply, schema), f"expected {schema.__name__}, got {type(reply).__name__}"
            return reply
        return RunnableLambda(next_reply)


def scripted_model(*analysis: AIMessage | str, understood: IncidentScope | None = None,
                   final: IncidentReport | None = None) -> ScriptedChatModel:
    return ScriptedChatModel(
        messages=iter(analysis or ("payment-service is down",)),
        structured_replies=[understood or scope(), final or report()],
    )

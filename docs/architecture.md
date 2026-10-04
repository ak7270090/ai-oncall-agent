# Architecture

How an investigation runs and which MCP features the project uses.

## How an investigation runs (Phase 8)

A LangGraph state machine. **Code decides which checks run; the LLM
understands, reasons and writes.** The same essential checks happen every
time, and a typical investigation costs 3 LLM calls.

```text
START → extract_incident_scope → collect_namespace_overview → inspect_flagged_problems
      → trace_failing_dependencies → find_root_cause ⇄ run_requested_tools (≤ MAX_FOLLOW_UP_ROUNDS)
                                                   └──→ write_report → END
```

Code layout (`ai-server/agent/`): `workflow/graph.py` only wires the flow; each
step is a method of `InvestigationNodes` in `workflow/nodes.py`; the state passed
between steps is `InvestigationState` in `workflow/state.py`; the collection steps
are in `evidence/collection_steps.py` and the rules they use (unhealthy pods, failing or
slow services…) in `evidence/analysis.py`; LLM setup is in `llm/`, prompts in `prompts.py`.
Step names, MCP tool names and other fixed values are in `ai-server/constants.py`.

| Step | Who | What |
| --- | --- | --- |
| `extract_incident_scope` | LLM (structured output) | `IncidentScope`: namespace, suspected services, symptom, time window |
| `collect_namespace_overview` | Code, in parallel | `get_service_overview`, `list_pods`, `list_events` (warnings), `list_deployments` |
| `inspect_flagged_problems` | Code, in parallel | Unhealthy pods → status and logs (`previous=true` if the pod restarted). Services above `ERROR_RATE_THRESHOLD` → error-rate history, plus logs from one pod even if it looks healthy. Deployments not fully ready or scaled to 0 → rollout history |
| `trace_failing_dependencies` | Code, in parallel | Error or slow-call log lines naming another service (`upstream unavailable: POST http://payment-service/…`) → that service's pods, deployment, error rate and latency |
| `find_root_cause` ⇄ `run_requested_tools` | LLM + tools | Reasons over all the evidence (JSON). May request up to `MAX_FOLLOW_UP_ROUNDS` rounds of extra tool calls |
| `write_report` | LLM (structured output) | `IncidentReport`: incident, impact, cited evidence, likely cause, confidence, recommended actions, timeline |

If an MCP tool is missing (e.g. no metrics), its step is skipped and noted.
A tool that fails becomes evidence (with its error) rather than stopping the
investigation. Thresholds and limits are in `ai-server/.env` (see
`.env.example`).

**Response** of `POST /investigate`:

```json
{
  "answer": "**Incident:** ... (the report as Markdown)",
  "report": {"incident": "...", "impact": "...", "evidence": [{"source": "get_pod_logs", "finding": "..."}],
             "likely_cause": "...", "confidence": "high", "recommended_actions": ["..."], "timeline": ["..."]},
  "evidence": [{"step": "inspect_flagged_problems", "source": "get_pod_logs", "arguments": {"pod": "..."}, "error": null}],
  "notes": ["trace_failing_dependencies: logs point at payment-service"],
  "steps": ["extract_incident_scope", "collect_namespace_overview", "inspect_flagged_problems",
            "trace_failing_dependencies", "find_root_cause", "write_report"],
  "llm_calls": 3,
  "follow_up_limit_reached": false
}
```

## MCP concepts used

| Concept | Where |
| --- | --- |
| MCP servers and tools | `mcp-platform/server/k8s/server.py`, `prometheus/server.py` (shared parts in `base_server.py`). The JSON Schema for each tool comes from its type hints (`Literal` → `enum`, `Field(ge, le)` → `minimum`/`maximum`), and the docstring becomes the description the LLM reads. |
| Discovery / invocation | `tools/list` in `mcp_client/langchain_tools.py`, `tools/call` through each LangChain tool |
| Tool errors | Schema violations and `ToolError` come back as `is_error=True`. The SDK hides the text of unexpected exceptions. |
| Transport | Streamable HTTP at `/mcp`. stdio is available with `MCP_TRANSPORT=stdio`. |
| Progress | `ctx.report_progress` in `get_service_overview`; the client opts in per call with `progress_callback` (`mcp_client/progress.py`). |
| Resources | `runbook://`, `topology://`, `k8s://` URI templates (`mcp-platform/server/k8s/resources.py`); read by the client with `read_resource`. |
| Annotations / completions | `readOnlyHint` on every tool, enforced by the client; completions for resource-template arguments. |
| Elicitation | Write tools ask for approval with `Resolve`/`Elicit`; the AI server answers via `Client(elicitation_callback=…)` from `POST /actions/{id}/approval`. |
| Sampling | `get_pod_logs(summarize=true)` asks the client's LLM through `Resolve`/`Sample` with model preferences; the client answers with `Client(sampling_callback=…)` (`llm/sampling.py`). |
| Authorization | Bearer tokens checked by `MCPServer(token_verifier=…)` with `AuthSettings` (401 + protected resource metadata); scopes and roles enforced by server middleware (`MCPServer(middleware=[…])`). |
| Host / client | The AI server is the host. `mcp.Client` is the client. |

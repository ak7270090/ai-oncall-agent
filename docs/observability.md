# Observability

Tracing every investigation in Langfuse, and streaming its progress live.

## Tracing with Langfuse (Phase 11)

Every investigation can be recorded as one **trace** in [Langfuse](https://langfuse.com):
a timeline of each graph step, every LLM call (prompt, answer, model, tokens, cost)
and every MCP tool call with its arguments and result.

```text
investigate                         (agent: question in, report out, outcome metadata)
└─ LangGraph
   ├─ extract_incident_scope   → ChatOpenAI (generation: tokens, cost)
   ├─ collect_namespace_overview → list_pods, list_events, … (tool spans, in parallel)
   ├─ inspect_flagged_problems   → get_pod_logs, get_metrics, …
   ├─ trace_failing_dependencies → list_pods, …
   ├─ find_root_cause          → ChatOpenAI  ⇄  run_requested_tools → get_pod_status, …
   └─ write_report             → ChatOpenAI
```

Setup: create a Langfuse project (cloud or self-hosted), then **Settings → API Keys**,
and put the keys in `ai-server/.env`:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or https://us.cloud.langfuse.com, or your own
```

Without keys tracing is off. `/investigate` returns `trace_id` and `trace_url`
(a direct link to the trace). Optional request fields: `trace_tags` (e.g.
`["incident:db-down"]`), and a W3C `traceparent` header to record the
investigation inside the caller's trace.

How it works (`ai-server/tracing.py`):

- `run_investigation` opens a root span and passes Langfuse's LangChain
  `CallbackHandler` to the graph run. LangChain reports every step, LLM call and
  LLM-requested tool to it; token usage comes from LangChain, so this works with any
  provider, and Langfuse prices known models itself (add others under **Settings → Models**).
- The fixed collection steps call MCP tools directly, so `MCPToolbox.call` reports
  each call as a LangChain tool run; it shows up under its step like any other tool.
- The MCP SDK's own OpenTelemetry spans are not exported (they would duplicate every
  tool span).
- Tracing never fails an investigation: if Langfuse is unreachable, only `trace_url`
  is missing.
- Traces contain prompts, logs, events and metrics the agent read. With Langfuse
  Cloud they're stored there; secrets in `.env` are never sent.

## Live progress (Phase 15)

`POST /investigate/stream` runs the same investigation as `/investigate` and sends
what happens as it happens, as Server-Sent Events (SSE): one HTTP response that stays
open and delivers one small event at a time.

```bash
curl -N -X POST http://127.0.0.1:8000/investigate/stream \
     -H "content-type: application/json" -d '{"question": "Checkout is failing"}'
```

```text
event: step      data: {"step": "collect_namespace_overview", "status": "started"}
event: tool      data: {"tool": "get_service_overview", "call_id": "a1f0c2d4", "status": "started", "step": "collect_namespace_overview", "arguments": {"namespace": "shop"}}
event: progress  data: {"tool": "get_service_overview", "progress": 2.0, "total": 3.0, "message": "error_rate queried in 0.4s"}
event: tool      data: {"tool": "get_service_overview", "call_id": "a1f0c2d4", "status": "finished", "step": "collect_namespace_overview", "seconds": 0.9}
event: note      data: {"note": "trace_failing_dependencies: logs point at payment-service"}
event: llm       data: {"call_id": "77be01c9", "step": "find_root_cause", "status": "finished", "seconds": 3.8, "input_tokens": 5919, "output_tokens": 457}
event: report    data: {...the same InvestigateResponse as POST /investigate...}
```

| Event | When |
| --- | --- |
| `step` | a graph step starts / finishes (with seconds) |
| `tool` | an MCP tool call starts / finishes / fails; `call_id` pairs them (calls run in parallel) |
| `progress` | the MCP server reports progress inside one tool call |
| `llm` | an LLM call starts / finishes (seconds, tokens, `model`, `purpose` for sampling) |
| `note` | a step explains a decision (skipped tools, hidden stale events, followed dependencies) |
| `report` / `error` | the end: the full response, or `{"status_code", "detail"}` |

How it works, in two hops:

1. **MCP server → AI server (MCP progress notifications).** `get_service_overview`
   runs three PromQL queries; after each one the backend calls back and the tool sends
   `ctx.report_progress(done, 3, "error_rate queried in 0.4s")`
   (`mcp-platform/server/prometheus/helpers.py::query_progress_reporter`). The AI server passes a
   `progress_callback` with every `call_tool`, which is what asks the server for progress.
2. **AI server → user (SSE).** `ai-server/investigation/events.py` collects three sources into one
   queue: LangChain callbacks (steps, tool calls, LLM calls, notes), MCP progress, and
   the final report or error. The route yields them with FastAPI's `EventSourceResponse`.

Closing the connection (Ctrl+C, a closed tab) cancels the investigation: the graph
stops and its pending MCP and LLM calls are cancelled.

MCP *logging* (`notifications/message`) is deprecated as of protocol 2026-07-28
(SEP-2577), so the server doesn't use it: progress messages carry the server's status
text, and `note` events carry the AI server's explanations.

# Architecture

How an investigation runs, step by step, and which MCP features make it work.

## How an investigation runs

Think about how a good on-call engineer works. They don't start by guessing. They open the
dashboards, check which pods are unhappy, read the logs of whatever looks broken, and follow the
trail. Only then do they sit back and think, "OK, what's actually going on here?"

The agent works the same way. **Code decides which checks to run; the LLM only understands the
question, reasons over the evidence and writes the report.** That way the important checks happen
every single time, the agent can't wander off, and a typical investigation needs just 3 LLM calls.

```text
START → extract_incident_scope → collect_namespace_overview → inspect_flagged_problems
      → trace_failing_dependencies → find_root_cause ⇄ run_requested_tools (≤ MAX_FOLLOW_UP_ROUNDS)
                                                   └──→ write_report → END
```

| Step | Who does it | What happens, in plain words |
| --- | --- | --- |
| `extract_incident_scope` | LLM | Reads your question and pulls out the basics: which namespace, which services you suspect, what the symptom is, how far back to look. |
| `collect_namespace_overview` | Code | Takes a quick look at everything at once: error rate and latency per service, all pods, warning events, all deployments. |
| `inspect_flagged_problems` | Code | Zooms in on whatever looked wrong: logs and status of unhappy pods (including the crashed container's logs), the error history of failing services, the rollout history of deployments that aren't fully ready. |
| `trace_failing_dependencies` | Code | Follows the clues. If order-service's logs say `upstream unavailable: POST http://payment-service/…`, it goes and checks payment-service too. |
| `find_root_cause` | LLM + tools | Thinks over all the evidence. If something is missing, it can ask for more tools, for a limited number of rounds. |
| `write_report` | LLM | Writes the incident report: what's broken, impact, evidence with quotes, likely cause, confidence, suggested fixes and a timeline. |

Things go wrong during investigations too, so the agent is forgiving about it:

- **A tool is missing** (say, no metrics server): the step is skipped, and the report notes it.
- **A tool fails:** the error becomes part of the evidence instead of stopping the investigation.
- **Thresholds** such as "what counts as a high error rate" live in `ai-server/.env`, not in the
  code.

<details>
<summary>What <code>POST /investigate</code> returns</summary>

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

</details>

**In the code:** `ai-server/investigation/workflow/` (`graph.py` wires the steps, `nodes.py` holds
them, `state.py` is what they pass along); the checks are in `investigation/evidence/`, and the
prompts are in `investigation/prompts.py`.

## MCP features used

MCP (Model Context Protocol) is the standard way for an AI app to talk to tools. Here's each
piece of it, what it means in this project, and where it lives.

| MCP feature | What it means here | In the code |
| --- | --- | --- |
| **Servers and tools** | Two servers give the agent its tools: one for Kubernetes, one for Prometheus. Each tool's description and input rules come straight from its Python type hints and docstring. | `mcp-platform/server/k8s/`, `prometheus/` |
| **Discovery and calls** | The agent asks the servers "what tools do you have?" (`tools/list`) and then calls them (`tools/call`). | `mcp_client/langchain_tools.py` |
| **Tool errors** | Bad input or a failed tool comes back as an error result the LLM can read, not a crash. | the MCP SDK |
| **Transport** | Streamable HTTP: every request is a plain POST to `/mcp`. | both apps |
| **Progress** | A slow tool can say "2 of 3 queries done", and that shows up live for the user. | `get_service_overview`, `mcp_client/progress.py` |
| **Resources** | Read-only documents the agent can look up: runbooks, the service map, deployment specs. | `k8s/knowledge.py` |
| **Annotations and completions** | Every tool is labelled read-only or destructive, and the agent only gets the read-only ones. Completions autocomplete resource names. | `tool_definitions.py`, `mcp_client/tool_policy.py` |
| **Elicitation** | Before changing anything, the server stops and asks a human for approval. | `k8s/deployments.py`, `ai-server/actions/` |
| **Sampling** | The server borrows the agent's LLM to summarize long logs, so it needs no API key of its own. | `k8s/pods.py`, `ai-server/llm/sampling.py` |
| **Authorization** | Every request carries a signed token saying who's asking; without one the answer is 401. | `mcp-platform/server/auth/`, `ai-server/auth/` |
| **Host and client** | The AI server is the *host*; inside it, `mcp.Client` is the *client* that talks to the servers. | `ai-server/mcp_client/` |

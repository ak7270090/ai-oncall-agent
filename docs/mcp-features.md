# Advanced MCP features

Resources, annotations and completions, sampling and model routing.

## Team knowledge as MCP resources (Phase 13)

Tools return *live* data. An experienced engineer also knows things no metric shows:
what depends on what, what a log message usually means, what is safe to do. The MCP
server publishes that knowledge as **resources**: read-only documents with a URI, which
the *client* reads (a tool, by contrast, is something the *model* decides to call).

| Resource | Content | Source |
| --- | --- | --- |
| `runbook://{service}` | dependencies, what its log messages mean, known failure modes, safe actions (Markdown) | `mcp-platform/server/knowledge/runbooks/<service>.md` |
| `topology://{namespace}` | who calls whom (JSON) | `mcp-platform/server/knowledge/topology/<namespace>.json` |
| `k8s://{namespace}/deployments/{name}` | configured spec: image, env var *names*, envFrom ConfigMaps/Secrets by name, CPU/memory, probes; never values | live, Kubernetes API |

```text
→ resources/templates/list   ← runbook://{service}, topology://{namespace}, k8s://{namespace}/deployments/{name}
→ resources/read runbook://payment-service
← "# payment-service\n`POST /payments` ... database unavailable: payments-db:5432 ..."
```

The agent reads them during the fixed steps (`USE_SERVICE_KNOWLEDGE=true`, default):
`collect_namespace_overview` reads the service map; `inspect_flagged_problems` reads the
runbooks of the flagged services; `trace_failing_dependencies` those of services the logs
blame. They become evidence (`source: runbook` / `topology`); the prompt says it's
documented knowledge and that live evidence wins if they disagree. A service without a
runbook becomes a note, not evidence. The namespace allowlist applies, names are
validated, and the SDK itself rejects path traversal in URIs.

Try it: MCP Inspector → Resources → `runbook://payment-service`.

**Measured** (two eval runs each): 6/6 with and without knowledge, high confidence; about
+4% input tokens and the same cost per incident. No gain is visible yet because the agent
already passes all six incidents.

## Tool annotations and completions (Phase 16)

- **Annotations:** every tool is registered with `readOnlyHint=true`,
  `destructiveHint=false`, `idempotentHint=true` (`tool_definitions.py::READ_ONLY_TOOL`).
  The AI server gives the agent **only** tools annotated read-only
  (`mcp_client/tool_policy.py`); a tool without annotations counts as unsafe and is
  logged and left out. `GET /tools` shows `read_only` / `destructive` per tool. Hints
  are not security: RBAC still limits what the MCP server can do.
- **Completions:** autocomplete for resource arguments in MCP clients:
  `runbook://pay…` → `payment-service`, `payments-db`; `k8s://shop/deployments/…` lists
  the deployments (`k8s/knowledge.py`). MCP completions exist for resource-template
  and prompt arguments, not for tool arguments.

## Log summaries and model routing (Phase 17)

Long logs are expensive: every line goes into the strong model's prompt, twice (root
cause and report). With `SUMMARIZE_LOGS=true` the agent asks for summaries instead, and
a cheap model writes them, chosen through **MCP sampling** and **model routing**.

```bash
# ai-server/.env
LLM_MODEL=openai:gpt-5.4-mini        # strong tier: reasoning (unchanged)
LLM_MODEL_FAST=openai:gpt-5.4-nano   # fast tier: log summaries; same LLM_API_KEY
SUMMARIZE_LOGS=true
LOG_LINES=200                        # summaries make reading more history affordable
```

```text
inspect_flagged_problems ─► tools/call get_pod_logs(pod, lines=200, summarize=true)
     MCP server: 200 lines ≥ MCP_LOG_SUMMARY_MIN_LINES ─► "input required: sampling,
                 model preferences: cost 0.8, speed 0.7, intelligence 0.2"
     AI server:  ModelRouter → fast tier (gpt-5.4-nano) ─► summary
     MCP server: returns {summary, summarized_by, newest 5 lines} as the tool result
find_root_cause / write_report ─► the strong model reads the summary, not 200 lines
```

- **MCP sampling** (`mcp-platform/server/k8s/pods.py`): the MCP server asks the
  *client's* LLM for the summary, so it holds no API key and picks no model. It only
  states preferences; with protocol 2026-07-28 the SDK sends them as an "input
  required" result and re-runs the tool with the answer. The question must be identical
  on that second run, so fetched lines are reused for `MCP_LOG_CACHE_SECONDS`.
  Short logs and clients that can't sample get raw lines.
- **Model routing** (`ai-server/llm/model_router.py`): two tiers. Sampling
  requests go to the tier their preferences describe (a model-name hint wins; otherwise
  cost/speed above intelligence → fast). Graph steps listed in `FAST_MODEL_STEPS` use
  the fast tier; all others the strong one. Without `LLM_MODEL_FAST` nothing changes.
- **SamplingResponder** (`llm/sampling.py`) answers the requests: capped per
  investigation (`MAX_SAMPLINGS_PER_INVESTIGATION`), recorded in the Langfuse trace and
  streamed as `llm` events with `model` and `purpose`. A failed summary falls back to
  raw lines.

**Measured** (Langfuse experiments, kind cluster, one eval run each):

| Setup | Log lines read | Strong-model input tokens / incident | Cost / incident | Pass |
| --- | --- | --- | --- | --- |
| mini only, raw logs | 50 | 16,046 | $0.0192 | 4/6 |
| mini + nano summaries | 200 | 13,206 (−18%) | $0.0203 | 5/6 |
| replay: nano also writes the report | — | — | ~$0.012 (−40%) | 5/6; high-cpu 1/3 on repeats |

Summaries let the agent read 4× more log history while the strong model sees fewer
tokens, at about the same total cost. Moving `write_report` to the cheap model saves 40%
but loses accuracy on the hardest incident: the report step decides the cause category,
so it stays on the strong model. One run per setup is within LLM noise; repeat before
relying on small differences.

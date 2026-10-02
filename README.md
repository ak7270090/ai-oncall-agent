# AI On-Call Agent (MCP)

An AI on-call assistant that investigates incidents through the Model Context
Protocol. See [PLAN.md](./PLAN.md) for the roadmap. **Phases 1–9 are done.**
Code rules are in [CODING_GUIDELINES.md](./CODING_GUIDELINES.md).

```text
 User ──HTTP──► AI server :8000 ──MCP / Streamable HTTP──► MCP server :9000 ──read-only──► kind cluster (shop)
                FastAPI                                     Kubernetes: list_pods,           │
                LangGraph + LangChain                         get_pod_status, get_pod_logs,  │ scrape /metrics
                any LLM (config)                              list/get_deployment,           ▼
                MCP client                                    list_events                  Prometheus (monitoring)
                                                            Metrics: get_service_overview, ◄──── PromQL
                                                              get_metrics
```

The two apps are fully separate. They share no code, and each has its own
virtualenv, requirements and settings. The AI server knows only the MCP
server's URL.

## Layout

```text
ai-oncall-agent/
├── mcp-server/
│   ├── server.py              create_server(): registers tools, /health route
│   ├── config/settings.py     MCP_* settings
│   ├── cluster/               real Kubernetes: backend.py (interface), kubernetes_backend.py, models.py
│   ├── observability/         real Prometheus: backend.py (interface), prometheus_backend.py, queries.py (PromQL)
│   ├── fake/                  MCP_BACKEND=fake: incident_data.py, cluster_backend.py, metrics_backend.py
│   ├── tools/                 tool layer: kubernetes.py, observability.py, helpers.py (namespace allowlist)
│   └── tests/                 unit + integration/ (live kind cluster, RBAC checks)
├── ai-server/
│   ├── main.py                create_app(), error → HTTP status mapping
│   ├── api/                   routes, schemas, dependencies
│   ├── agent/                 investigation.py (entry point), models.py (IncidentReport.to_markdown())
│   │   ├── workflow/          graph.py (wiring), nodes.py (the steps), state.py
│   │   ├── evidence/          collection_steps.py (deterministic checks), helpers.py (rules), mcp_toolbox.py
│   │   └── llm/               chat_model.py (provider-agnostic), prompts.py
│   ├── mcp_client/            connection.py, langchain_tools.py (MCP → LangChain adapter)
│   ├── tracing/               langfuse_tracer.py (one Langfuse trace per investigation)
│   ├── config/settings.py
│   └── tests/                 unit tests + integration/ (real HTTP)
├── sample-services/       Phase 5 "production" apps: user-, payment-, order-service
├── kubernetes/            base/ (healthy system, ns shop), incidents/ (incident overlays), monitoring/ (Prometheus)
├── evals/                 incident eval: incident_cases.py (expected answers), run_eval.py
├── docker-compose.yml     AI server + MCP server (fake data)
├── docker-compose.kind.yml  overlay: MCP server reads the kind cluster
├── Makefile               every command: make help
└── CODING_GUIDELINES.md
```

Each service folder has its own Dockerfile.

## Setup

Needs Python 3.11+ and `make` (see [Commands](#commands) for Windows).

```bash
make setup    # virtualenv + dependencies for each app, creates ai-server/.env
```

Then set `LLM_MODEL` and `LLM_API_KEY` in `ai-server/.env`.

### Choosing the LLM

Set two lines in `ai-server/.env`. No code changes are needed:

```ini
LLM_MODEL=openai:gpt-5.4-mini        # or anthropic:claude-opus-5, openai:gpt-5.5, ...
LLM_API_KEY=<key for that provider>
```

## Commands

Everything runs through the `Makefile`; `make help` lists the targets:

| Command | What it does |
| --- | --- |
| `make setup` | Virtualenv + dependencies for each app, creates `ai-server/.env` |
| `make run-mcp-server` / `make run-ai-server` | Run the apps locally (no Docker) |
| `make up` / `make down` / `make logs` | AI server + MCP server in Docker Compose (fake cluster data) |
| `make up-kind` | Same, but the MCP server reads the kind cluster |
| `make test` | Every test suite (cluster tests run only if the kind cluster is up) |
| `make cluster-up` / `make smoke-test` / `make cluster-down` | Kind cluster with the sample services |
| `make redeploy` | Rebuild the sample-service images and restart them in the cluster |
| `make mcp-kubeconfig` | Fresh short-lived, read-only credentials for the MCP server |
| `make incident NAME=…` / `make incident-reset` | Inject an incident / return to healthy |
| `make eval [NAME=a,b]` | Run incidents end to end and grade the agent |
| `make replay [NAME=..] [TIMES=n]` | Re-run only the LLM reasoning on evidence saved by the last eval (seconds) |

Override variables per run, e.g. `make cluster-up CLUSTER=test`.

**Tools:** Python 3.11+, Docker, `make`, and for the cluster also `kind` and
`kubectl`. macOS: `brew install make kind kubectl`. Linux: use your package
manager (`make` is usually preinstalled).

**Windows:** run `make` from **Git Bash**, e.g. the VS Code terminal set to
Git Bash. One-time setup:
`winget install ezwinports.make Kubernetes.kind Kubernetes.kubectl`, and make
sure winget's tools come before Docker Desktop's older bundled `kubectl` on
PATH. For example, add this to `~/.bashrc`:
`export PATH="$(cygpath -u "$LOCALAPPDATA")/Microsoft/WinGet/Links:$PATH"`.

## Run with Docker

Needs Docker Desktop running and `ai-server/.env` created (see above). Then
`make up`. It builds both images and waits until they're healthy.

- Both services run on the Compose network. The AI server reaches the
  MCP server at `http://mcp-server:9000/mcp`.
- Ports are published on `127.0.0.1` only: AI server `8000`, MCP server `9000`
  (for the Inspector). To change them, copy `.env.example` in the repo root to
  `.env` and edit it.
- Images run as a non-root user and contain no `.env`, tests or dev
  dependencies. The API key is passed in at runtime from `ai-server/.env`.
- Inside Docker the MCP server listens on `0.0.0.0`, so DNS-rebinding protection
  is enabled explicitly with `MCP_ALLOWED_HOSTS`.

## Run locally (without Docker)

```bash
make run-mcp-server   # terminal 1: http://127.0.0.1:9000/mcp
make run-ai-server    # terminal 2: http://127.0.0.1:8000 (Swagger UI at /docs)
```

| Endpoint | What it does |
| --- | --- |
| `GET /health` | Liveness check for the AI server only |
| `GET /ready` | Confirms the MCP server is reachable (runs `tools/list`) |
| `GET /tools` | Lists the tools the MCP server advertises |
| `POST /investigate` | `{"question": "..."}` → structured incident report, Markdown version, every check that ran, graph steps |

Errors: MCP server unreachable → `503`; LLM provider failure → `502` (details go
to the server log only).

To call MCP tools by hand, open the [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
with `npx @modelcontextprotocol/inspector` and connect with Streamable HTTP to
`http://127.0.0.1:9000/mcp`.

## Fake production environment (kind)

Three tiny FastAPI services run in a local Kubernetes cluster. They're what
the agent will investigate from Phase 6 onward.

```text
            namespace: shop
 order-service ──► user-service       GET  /users/{id}
      │
      └──────────► payment-service    POST /payments   (key from a Secret)
```

Needs Docker Desktop running, plus `kind` and `kubectl`
(`winget install Kubernetes.kind Kubernetes.kubectl`). On Windows, WSL must use
cgroup v2 for Kubernetes 1.35+. Add this to `%USERPROFILE%\.wslconfig`, then
run `wsl --shutdown` and restart Docker:

```ini
[wsl2]
kernelCommandLine = cgroup_no_v1=all
```

```bash
make cluster-up     # create cluster, build + load images, deploy, wait until Available
make smoke-test     # place an order from a throwaway curl pod inside the cluster
make cluster-down   # delete the cluster (frees CPU/RAM)
```

| Kubernetes object | Where to look |
| --- | --- |
| Namespace | `kubernetes/base/namespace.yaml` (`shop`) |
| Deployment → ReplicaSet → Pod | `kubernetes/base/deployments/*.yaml`, 2 replicas each, probes, limits, non-root |
| Service | `kubernetes/base/services/*.yaml`, ClusterIP. order-service reaches `http://user-service` by DNS. |
| ConfigMap | `kubernetes/base/configmaps/*.yaml`, injected with `envFrom` |
| Secret | Generated by kustomize from `kubernetes/base/secrets/*.env` (gitignored; `make cluster-up` creates it with a random key) |
| Downward API | The pod's `version` label becomes `APP_VERSION` |

Useful commands: `kubectl get deploy,rs,pods,svc -n shop`,
`kubectl logs -n shop deploy/order-service`,
`kubectl describe pod -n shop -l app=payment-service`.

## Real Kubernetes tools (Phase 6)

The MCP server reads the kind cluster through the official `kubernetes` Python
client. Every tool is read-only:

| Tool | What the agent gets |
| --- | --- |
| `list_pods(namespace, app?)` | Phase, ready, restarts and a one-word status (`CrashLoopBackOff`, `ImagePullBackOff`, …) |
| `get_pod_status(pod)` | Per container: state, reason, restart count, last termination reason and exit code |
| `get_pod_logs(pod, lines, previous)` | Recent log lines. `previous=true` returns the crashed container's logs. |
| `list_deployments(namespace)` | Image, version label, desired/ready/updated/available replicas |
| `get_deployment(name)` | Conditions plus rollout history (ReplicaSet revisions, newest first), to spot bad rollouts |
| `list_events(namespace, warnings_only)` | Recent events: BackOff, failed image pulls, probe failures, … |

Tools return typed results with an MCP output schema. They contain only the
fields shown above, never environment variables or other parts of a pod spec.

**Two layers of protection:**

| Layer | Enforces |
| --- | --- |
| **RBAC** (`kubernetes/base/rbac/mcp-server.yaml`) | The `mcp-server` ServiceAccount can only `get/list` pods, pods/log, events, deployments and ReplicaSets in `shop`: no Secrets, no other namespaces, no writes. Enforced by the API server even if our code has a bug. |
| **Tool layer** (`mcp-server/tools/kubernetes.py`) | Namespace allowlist (`MCP_ALLOWED_NAMESPACES`), validated arguments (log lines ≤ 500), trimmed output, readable errors for the model |

The MCP server never uses your admin kubeconfig. `make cluster-up` runs
`make mcp-kubeconfig`, which creates a **short-lived token** (default 24h, set
with `MCP_TOKEN_TTL`) for the ServiceAccount and writes it to
`mcp-server/.kube/` (gitignored). Rerun `make mcp-kubeconfig` when the token
expires.

**Data source** (`MCP_BACKEND`):

| Value | Used by | Notes |
| --- | --- | --- |
| `kubernetes` (default) | `make run-mcp-server`, `make up-kind` | Reads the cluster and its Prometheus |
| `fake` | `make up`, unit tests | The canned incident, for both Kubernetes and metrics tools |

**Try it:** run `make cluster-up`, break something (e.g.
`kubectl -n shop set image deploy/payment-service payment-service=payment-service:v2`),
then `make run-mcp-server` and `make run-ai-server`, or `make up-kind`, and ask
`/investigate` what's wrong.

## Metrics with Prometheus (Phase 7)

```text
sample services ──/metrics──► Prometheus (namespace monitoring) ──HTTP API──► MCP metrics tools ──► agent
traffic-generator ──1 order/s──► order-service ──► user-service, payment-service
```

- **Instrumentation.** Each sample service exposes `/metrics` via
  `prometheus-fastapi-instrumentator`: request counts by route and status
  class, a latency histogram, and process CPU and memory. Pods opt in with
  `prometheus.io/*` annotations.
- **Prometheus** runs in its own `monitoring` namespace. It may only discover
  pods in `shop` (a Role, not a cluster-wide ClusterRole), keeps 6h of data,
  and is exposed only on `http://127.0.0.1:9090` (kind port mapping).
- **Traffic generator.** It places about one order per second (some for a
  nonexistent user → expected 404s), so there is always data to look at.

**Tools**

| Tool | What the agent gets |
| --- | --- |
| `get_service_overview(namespace)` | Current request rate, error rate and p99 latency for every service, to find the failing one |
| `get_metrics(service, metric, minutes)` | History of one metric (one sample per minute), to see *when* it changed |

**The PromQL behind each metric** (`mcp-server/observability/queries.py`,
with `sel` = `namespace="shop",service="…"`):

| Metric | PromQL | Function learned |
| --- | --- | --- |
| `request_rate` | `sum(rate(http_requests_total{sel}[1m]))` | `rate`, `sum` |
| `error_rate` | `(sum(rate(http_requests_total{sel,status="5xx"}[1m])) or vector(0)) / sum(rate(http_requests_total{sel}[1m]))` | ratio of rates |
| `error_count` | `sum(increase(http_requests_total{sel,status="5xx"}[1m]))` | `increase` |
| `latency_p99_ms` | `1000 * histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{sel}[1m])))` | `histogram_quantile` |
| `cpu_cores` | `sum(rate(process_cpu_seconds_total{sel}[1m]))` | `rate` on a CPU counter |
| `memory_mb` | `avg(process_resident_memory_bytes{sel}) / 1048576` | `avg` across pods |

Open `http://127.0.0.1:9090` to try these queries yourself.

**Security.** Service names are checked against a strict name pattern before
they're put into PromQL, so a crafted name can't rewrite the query (no PromQL
injection). The namespace allowlist applies to metrics tools too.

**Try it:** run `make cluster-up`, then
`kubectl -n shop scale deploy/payment-service --replicas=0`. Within about a
minute order-service's error rate climbs, and its logs say
`upstream unavailable: POST http://payment-service/payments`. Ask
`/investigate` why checkout fails. Restore with `--replicas=2`.

## Incidents and evaluation (Phase 9)

Six realistic failures, each a kustomize overlay on the healthy base
(`kubernetes/incidents/<name>`). Inject one with `make incident NAME=<name>`
and undo it with `make incident-reset`.

| Incident | What breaks | Expected root cause |
| --- | --- | --- |
| `payment-down` | payment-service scaled to 0 | `dependency_unavailable` in payment-service |
| `db-down` | Postgres (`payments-db`) scaled to 0 → payment-service 503 → order-service 502 | `dependency_unavailable` in **payments-db** (two hops from the symptom) |
| `bad-deploy` | payment-service rolled to `v2`, whose regression fails every payment (pods stay healthy) | `bad_deployment` in payment-service |
| `crash-loop` | A config change drops payment-service's API key Secret → every pod crashes at startup | `crash_loop` in payment-service |
| `high-cpu` | user-service does expensive work per request and hits its 250m CPU limit | `resource_exhaustion` in user-service |
| `slow-payments` | payment-service takes 3s per request | `slow_dependency` in payment-service |

The faults are real behaviour in the sample services, switched on by a
`FAULT_MODE` setting that only the incident overlays set (`error`/`latency` in
payment-service, `cpu` in user-service). payment-service stores payments in
Postgres, whose password is a generated Secret like the API key.

**Eval.** With the cluster and both servers running, `make eval` does the
following for each incident:
1. Inject it.
2. Wait until the symptom shows in Prometheus or in pod restarts.
3. Ask `/investigate` a vague, operator-style question that doesn't name the
   cause.
4. Grade the report's `cause_category` and `root_cause_service` against the
   expected answer (exact match).
5. Reset, and wait until the cluster is healthy again.

Results are printed as a table and saved to `evals/results/` (gitignored).
Run a subset with `make eval NAME=db-down,high-cpu`. Each run costs about 3
LLM calls per incident.

**Latest results: 6/6 pass, all with high confidence** (full run about 11 minutes).

**What the eval uncovered and fixed:**
- payment-service never recovered after a database restart: the table was
  created only once per process.
- p99 latency was capped at 1000 ms by the default histogram buckets.
- Average CPU hides CPU-limit throttling. Prometheus now scrapes kubelet
  cAdvisor (`cpu_throttled_ratio`) with a ClusterRole limited to `nodes` and
  `nodes/metrics`.
- Pod logs came back as one undecoded string with no timestamps. They're now
  proper lines, each timestamped, so old errors can be told from new ones.
- Evidence left over from an earlier incident misled the agent: events of pods
  that no longer exist, probe failures of booting pods, and old error lines.
  Stale pod events are now filtered (with a note). The model gets the current
  time, and every metric history carries `latest`, `min` and `max`, to separate
  a past spike from an ongoing problem.
- `/health` and `/metrics` requests flooded the access logs and pushed real
  traffic out of the log tail. They're now filtered out of access logs, and
  order-service logs slow upstream calls.
- The categories were ambiguous (a config rollout that makes a service slow
  looked like `bad_deployment`). `cause_category` is now chosen by failure
  mechanism, in a fixed precedence order.

**Working on the agent's reasoning.** `make eval` saves every investigation with
its raw evidence. `make replay NAME=high-cpu TIMES=5` re-runs only the LLM
reasoning on that saved evidence in seconds, so prompt changes can be checked
(repeatedly, since LLM answers vary) without re-injecting incidents. Finish with
one full `make eval`.

**Eval speed.** Prometheus scrapes every 5s and rates use a 30s window, so
symptoms show up, and clear, within seconds rather than minutes. The eval waits
20s after a symptom appears (like an alert's `for:`) before asking the agent.

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
(a direct link to the trace).

How it works (`ai-server/tracing/langfuse_tracer.py`):

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

## Test

```bash
make test
```

This expects three virtualenvs: `mcp-server/.venv`, `ai-server/.venv` and
`sample-services/.venv` (from `sample-services/requirements-dev.txt`).

- MCP server tests call the tools through a real MCP client, in-process.
- AI server unit tests use a scripted chat model and a small in-process MCP
  server. No network and no API key needed.
- `ai-server/tests/integration/` starts the real MCP server as a separate
  process on a free port and tests the Streamable HTTP transport.

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
slow services…) in `evidence/helpers.py`; LLM setup and prompts are in `llm/`.
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
| MCP server and tools | `mcp-server/server.py`. The JSON Schema for each tool comes from its type hints (`Literal` → `enum`, `Field(ge, le)` → `minimum`/`maximum`), and the docstring becomes the description the LLM reads. |
| Discovery / invocation | `tools/list` in `mcp_client/langchain_tools.py`, `tools/call` through each LangChain tool |
| Tool errors | Schema violations and `ToolError` come back as `is_error=True`. The SDK hides the text of unexpected exceptions. |
| Transport | Streamable HTTP at `/mcp`. stdio is available with `MCP_TRANSPORT=stdio`. |
| Host / client | The AI server is the host. `mcp.Client` is the client. |

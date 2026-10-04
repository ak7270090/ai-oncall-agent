# AI On-Call Agent (MCP)

[![CI](https://github.com/ak7270090/ai-oncall-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/ak7270090/ai-oncall-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)

An AI on-call assistant that investigates incidents through the Model Context
Protocol. See [PLAN.md](./PLAN.md) for the roadmap. **Phases 1–13, 15–20 and 22 are
done.** Code rules are in [CODING_GUIDELINES.md](./CODING_GUIDELINES.md); security
notes in [SECURITY.md](./SECURITY.md).

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
│   ├── server.py              create_server(): registers the configured tool sets, auth, /health
│   ├── config.py              MCP_* settings
│   ├── k8s/                   Kubernetes tool set: tools.py, write_tools.py, log_summary.py, resources.py,
│   │                          completions.py; backend.py (interface), kubernetes_backend.py, operations.py,
│   │                          models.py; fake_backend.py, fake_operations.py (MCP_BACKEND=fake)
│   ├── prometheus/            Prometheus tool set: tools.py, helpers.py; backend.py (interface),
│   │                          prometheus_backend.py, queries.py (PromQL), models.py; fake_backend.py
│   ├── access/                tokens, roles, four eyes, audit log (Phases 19–20)
│   ├── tool_helpers.py        ToolDefinition, annotations, namespace allowlist (both tool sets)
│   ├── fake_incident.py       the canned incident both fakes serve
│   ├── knowledge/             team knowledge: runbooks/<service>.md, topology/<namespace>.json
│   └── tests/                 k8s/, prometheus/, shared tests; integration/ (live kind cluster, RBAC checks)
├── ai-server/                 organized by domain; each has router.py, schemas.py, dependencies.py,
│   │                          constants.py as it needs them
│   ├── main.py                create_app(): includes the routers, error → HTTP status mapping
│   ├── config.py              settings (+ SettingsDep)
│   ├── health.py              /health, /ready, /tools
│   ├── errors.py              which failures reach API callers, and how
│   ├── tracing.py             Langfuse: one trace per investigation and per action
│   ├── investigation/         POST /investigate(/stream): router.py, schemas.py, service.py (entry point),
│   │   │                      models.py (IncidentReport), prompts.py, events.py (live events)
│   │   ├── workflow/          graph.py (wiring), nodes.py (the steps), state.py
│   │   └── evidence/          collection_steps.py (deterministic checks), analysis.py (rules), mcp_toolbox.py
│   ├── actions/               POST /actions: router.py, registry.py (waits for approval), schemas.py
│   ├── auth/                  API keys (dependencies.py), MCP tokens (tokens.py, token_keys.py)
│   ├── llm/                   chat_model.py (provider-agnostic), model_router.py, sampling.py
│   ├── mcp_client/            connection.py, server_group.py, langchain_tools.py, constants.py (MCP names)
│   └── tests/                 unit tests + integration/ (real HTTP)
├── sample-services/       Phase 5 "production" apps: user-, payment-, order-service
├── kubernetes/            base/ (healthy system, ns shop), incidents/ (incident overlays), monitoring/ (Prometheus)
├── evals/                 incident eval: incident_cases.py (expected answers), run_eval.py, replay.py,
│                          experiment_tracking.py (Langfuse experiments)
├── gateway/               agentgateway.yaml: the MCP gateway (Phase 22); bin/ (downloaded, ignored)
├── keys/                  MCP token key pair from `make mcp-keys` (ignored)
├── docker-compose.yml     AI server + Kubernetes and Prometheus MCP servers (fake data)
├── docker-compose.kind.yml  overlay: the MCP servers read the kind cluster
├── docker-compose.gateway.yml  overlay: both MCP servers behind agentgateway, tokens on
├── Makefile               every command: make help
├── ruff.toml              lint rules; each app's pyproject.toml extends them (and holds pytest settings)
├── .github/workflows/     ci.yml: lint + tests on every push
├── CODING_GUIDELINES.md
├── SECURITY.md
└── LICENSE                MIT
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
| `make setup` | Virtualenv + dependencies for each app, creates `ai-server/.env` and `mcp-server/.env` |
| `make run-mcp-server` / `make run-ai-server` | Run the apps locally (no Docker) |
| `make up` / `make down` / `make logs` | AI server + MCP server in Docker Compose (fake cluster data) |
| `make up-kind` | Same, but the MCP server reads the kind cluster |
| `make test` | Every test suite (cluster tests run only if the kind cluster is up) |
| `make lint` | Ruff over the whole repository (rules in `ruff.toml`); CI runs it and the tests on every push |
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
make run-mcp-server   # terminal 1: http://127.0.0.1:9000/mcp (or run-mcp-servers: two servers)
make run-ai-server    # terminal 2: http://127.0.0.1:8000 (Swagger UI at /docs)
```

| Endpoint | What it does |
| --- | --- |
| `GET /health` | Liveness check for the AI server only |
| `GET /ready` | Confirms the MCP server is reachable (runs `tools/list`) |
| `GET /tools` | Lists the tools the MCP server advertises, write tools included |
| `POST /investigate` | `{"question": "..."}` → structured incident report, Markdown version, every check that ran, graph steps |
| `POST /investigate/stream` | Same investigation, streamed live as Server-Sent Events (see "Live progress") |

With `API_KEYS` set, every endpoint except `/health` and `/ready` needs an
`X-API-Key` header (see "Who may do what").

Errors: MCP server unreachable → `503`; LLM provider failure → `502` (details go
to the server log only). The table is in `ai-server/errors.py`, shared by both
investigate endpoints.

To call MCP tools by hand, open the [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
with `npx @modelcontextprotocol/inspector` and connect with Streamable HTTP to
`http://127.0.0.1:9000/mcp` (with `MCP_AUTH_JWKS_PATH` set it needs a bearer token).

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
| **Tool layer** (`mcp-server/k8s/tools.py`) | Namespace allowlist (`MCP_ALLOWED_NAMESPACES`), validated arguments (log lines ≤ 500), trimmed output, readable errors for the model |

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
traffic-generator ──4 workers × ~1 order/s──► order-service ──► user-service, payment-service
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

**The PromQL behind each metric** (`mcp-server/prometheus/queries.py`,
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

**Latest results (2026-10-03): 6/6 in two consecutive runs, all with high confidence** (full run about 11 minutes).

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
- The traffic generator was one loop that waited for each answer, so load eased off
  exactly when a service slowed down: during high-cpu, user-service was throttled
  anywhere from 34% to 66% depending on timing. Now `TRAFFIC_WORKERS` (4) loops run in
  parallel, like real users, and throttling is a steady 87-97%.
- At moderate signal levels the LLM drew the wrong conclusion from correct evidence: a
  service throttled at its CPU limit was called a "slow dependency", and a service that
  was slow during the *previous* incident was blamed for the current one. Code now
  states both facts as **computed findings** in the root-cause and report prompts
  (`investigation/evidence/analysis.py::computed_findings`): "X is held at its CPU limit (250m):
  throttled in 49% of CPU periods" and "slow right now: … / Y was slow earlier but has
  recovered". A service counts as CPU-starved only if it also uses at least 15% of its
  limit: an idle container with short bursts can look throttled too.

**Working on the agent's reasoning.** `make eval` saves every investigation with
its raw evidence. `make replay NAME=high-cpu TIMES=5` re-runs only the LLM
reasoning on that saved evidence in seconds, so prompt changes can be checked
(repeatedly, since LLM answers vary) without re-injecting incidents. Finish with
one full `make eval`.

**Eval speed.** Prometheus scrapes every 5s and rates use a 30s window, so
symptoms show up, and clear, within seconds rather than minutes. The eval waits
20s after a symptom appears (like an alert's `for:`) before asking the agent.

## Two MCP servers and a gateway (Phase 22)

The MCP server now runs as **two servers** from one codebase, and the AI server can talk
to them directly or through **agentgateway**, an open-source MCP gateway.

```text
direct:   AI server ─┬─► k8s server :9000          (pods, deployments, events, runbooks, write tools)
                     └─► prometheus server :9001   (get_service_overview, get_metrics)

gateway:  AI server ──► agentgateway :3000 ─┬─► k8s server :9000
            (one URL)    JWT check, CEL rules └─► prometheus server :9001
```

- **Two servers, one image:** `MCP_TOOLSETS` (`kubernetes`, `prometheus`, or both)
  decides which tools a process serves, and it builds only those backends: the
  Prometheus server gets no Kubernetes credentials, the Kubernetes server no Prometheus
  URL. `make run-mcp-servers` starts both; compose runs `k8s-mcp-server` and
  `prometheus-mcp-server`.
- **Several servers in the AI server** (`ai-server/mcp_client/server_group.py`):
  `MCP_SERVERS={"k8s": …, "prometheus": …}` opens one session per server, merges their
  tools and resource templates, and sends each call to the server that owns the tool.
  The rest of the AI server is unchanged: the group looks like one `mcp.Client`. The
  same tool name on two servers is refused at start.
- **The gateway** (`gateway/agentgateway.yaml`, agentgateway v1.6.0):
  - multiplexes both servers on one URL; tool names get the target as prefix
    (`k8s_list_pods`, `k8s+runbook://…`), which the AI server maps back (`MCP_GATEWAY_TARGETS`)
  - checks every request's JWT (401 without one) and passes it through, so the servers
    still know the person (roles, four eyes, audit stay there)
  - CEL rules: metrics and Kubernetes reads for everyone signed in; write tools only with
    scope `k8s:write`; the team-knowledge resources for everyone signed in (they need a
    rule of their own). Whatever no rule allows is hidden and refused before it reaches
    a server.
  - Progress, log summaries (sampling) and approvals (elicitation) work through it:
    protocol 2026-07-28's "input required" rounds are plain requests a proxy can pass.
- **Tokens signed with a key pair (RS256):** the AI server signs with
  `keys/mcp-token-private.pem`; the gateway and the servers verify with
  `keys/jwks.json` (`make mcp-keys`). Verifiers can't mint tokens.
- **Why agentgateway:** open source (Linux Foundation), one binary or container, YAML
  config, and it supports protocol 2026-07-28 (use ≥ v1.6.0: earlier versions broke
  tool calls with two or more servers). IBM ContextForge still implements 2025-11-25.

```bash
make mcp-keys                                   # once
MCP_ENABLE_WRITE_TOOLS=true make run-mcp-servers  # terminal 1
make run-gateway                                # terminal 2 (downloads the binary, checks its SHA-256)
# ai-server/.env: MCP_SERVERS={"gateway": "http://127.0.0.1:3000/mcp"}
#                 MCP_GATEWAY_TARGETS=["k8s", "prometheus"]
make run-ai-server                              # terminal 3
make up-kind-gateway                            # or all of it in Docker, against the kind cluster
```

Verified on the kind cluster: two servers directly: eval 6/6, proposed fixes 3/3. Through the gateway: the first run lost the runbooks (resources were renamed to `k8s+runbook://…` and no CEL rule allowed them); fixed, the evidence matched the direct run item for item. high-cpu then failed once because the incident's CPU load had faded (peak throttling 92% → 23%, then no symptom at all); in Docker (`make up-kind-gateway`) high-cpu and bad-deploy passed. Approvals through the gateway: four eyes enforced, rollback done, error rate → 0. Gateway overhead: +1 to +4 ms per tool call (median of 30). In Docker the gateway forwards `Host` without a port, so the servers' allowed hosts list the bare names.

## Who may do what: sign-in, roles and the audit log (Phases 19–20)

Until now anyone who could reach port 9000 could call every tool, and the approval of a
change was just a click. Now every request says **who** is asking, roles decide **what**
they may do, and every tool call lands in an **audit log**.

```text
person --X-API-Key--> AI server --Bearer JWT (sub=aman, client_id=oncall-ai-server,
                                   scope="k8s:read k8s:write", 60 s)--> MCP server
                                                                         ├ 401 without a valid token
                                                                         ├ roles: may aman call this?
                                                                         └ audit log (who, what, approval, trace)
```

- **Sign-in to the AI server:** `API_KEYS` maps API keys (`X-API-Key` header) to people.
  Everything except `/health` and `/ready` needs one. Empty = sign-in off (local dev only).
- **MCP authentication (OAuth bearer tokens):** for every HTTP request to the MCP server
  the AI server mints a short-lived JWT for the signed-in person, signed with its
  private key (`MCP_TOKEN_PRIVATE_KEY_PATH`; RS256 since Phase 22, HS256 before) and
  checked with the public JWKS (`MCP_AUTH_JWKS_PATH`, `make mcp-keys`). The MCP server
  (`MCPServer(token_verifier=…, auth=AuthSettings(…))`, `mcp-server/access/tokens.py`)
  answers 401 without a valid one and publishes OAuth protected resource metadata at
  `/.well-known/oauth-protected-resource/mcp`.
- **Scopes:** investigations get `k8s:read`, so the MCP server doesn't even list the write
  tools to them; `POST /actions` gets `k8s:read k8s:write`.
- **Roles** (`MCP_USER_ROLES`, `MCP_ROLE_WRITE_TOOLS`): every role may read; `developer`
  no write tools, `oncall` restart and scale, `lead` also roll back. A server middleware
  (`mcp-server/access/middleware.py`) refuses before the tool runs.
- **Four eyes:** the person who starts an action can't approve it (403 at the AI server),
  and the MCP server checks again: the approver named in the elicitation answer must be
  someone else whose role may run that tool.
- **Audit log** (`MCP_AUDIT_LOG_PATH`, JSON lines, append-only): every tool call with
  person, agent, arguments, outcome, approval (requested by, approved by, reason) and the
  Langfuse trace id that the MCP client sends in `_meta.traceparent`. Each action is its
  own Langfuse trace, tagged with the user.

```text
$ make audit DEPLOYMENT=payment-service SINCE=24
2026-10-04T06:47:31  ravi via oncall-ai-server: rollback_deployment(name=payment-service, namespace=shop, revision=1)
    REFUSED: Access denied: role oncall may not call rollback_deployment
2026-10-04T06:47:35  aman via oncall-ai-server: rollback_deployment(name=payment-service, namespace=shop, revision=1)
    DONE, approved by neha (v2 breaks payments): Rolled back deployment payment-service to the pod template of revision 1.
    trace: https://cloud.langfuse.com/project/<project>/traces/939a4752684ff891ec3a3bf20e4008d7
```

Setup: `make mcp-keys` for the token key pair and `make new-secret` for each API key;
key paths and `API_KEYS` in `ai-server/.env`, the JWKS path and `MCP_USER_ROLES` in
`mcp-server/.env`; `EVAL_API_KEY=<key> make eval`.

Verified on the kind cluster (bad-deploy): a developer's investigation proposed the
rollback; the oncall user was refused; the lead who started it couldn't approve it
(403); an oncall approver was refused by the MCP server; a second lead's approval rolled
it back (error rate → 0). `make audit` showed all of it with the trace links.

## Changes with human approval (Phase 18)

The agent can now **propose** fixes; a human **approves** each one before anything
changes. The investigation itself never changes the cluster.

```text
POST /investigate  → report.proposed_actions: [{"operation": "rollback_deployment",
                      "deployment": "payment-service", "revision": 1, "reason": "..."}]
POST /actions {"action": <one proposed action>}         → {"id": "53c3…", "status": "starting"}
GET  /actions/53c3…  → {"status": "awaiting_approval",
                        "question": "Roll back deployment payment-service in shop to revision 1
                                     (image payment-service:v1)?"}
POST /actions/53c3…/approval {"approve": true, "reason": "v2 breaks payments"}
GET  /actions/53c3…  → {"status": "done", "result": {"detail": "Rolled back deployment ..."}}
```

- **Write tools** (`mcp-server/k8s/write_tools.py`, off unless `MCP_ENABLE_WRITE_TOOLS=true`):
  `restart_deployment`, `scale_deployment` (0–`MCP_MAX_REPLICAS`), `rollback_deployment`,
  annotated `destructiveHint=true`, so the investigating agent never gets them (Phase 16).
- **Approval = MCP elicitation:** each tool first checks its arguments (deployment exists,
  revision exists, replicas in bounds), then asks the client: "Roll back … to revision 1
  (image …)?" with `approve` + `reason`. Approved → the change is made; rejected,
  declined, cancelled or no answer → nothing changes, and the result says so. A client
  that can't ask a human can't trigger a change at all.
- **The waiting** (`ai-server/actions/`): `POST /actions` returns at once; the action waits
  in `awaiting_approval` until `POST /actions/{id}/approval` or `APPROVAL_TIMEOUT_SECONDS`.
  With protocol 2026-07-28 the server returns "input required" and holds no connection
  while a human thinks. State is in memory (one AI server process).
- **Separate permissions:** the write tools use the `mcp-operator` ServiceAccount (patch
  Deployments and their scale, read ReplicaSets, in `shop` only;
  `kubernetes/base/rbac/mcp-operator.yaml`). `make mcp-kubeconfig` writes its kubeconfig.
  The read-only `mcp-server` account still can't change anything.
- **Rollback** replaces the Deployment's pod template with the target revision's (JSON
  Patch), like `kubectl rollout undo`.
- The eval grades proposed fixes (`action` column, Langfuse score `action_correct`) for the
  incidents with an obvious one: payment-down and db-down → scale back up, bad-deploy →
  roll back.

Verified on the kind cluster: bad-deploy → the agent proposed "roll back payment-service to
revision 1" → rejected: nothing changed → approved: rolled back, error rate 100% → 0%.
Eval (two runs): diagnoses 6/6 twice; proposed fixes 3/3 and 2/3 (once the agent proposed
nothing for payment-down, hedging that 0 replicas might be intended).

## Team knowledge as MCP resources (Phase 13)

Tools return *live* data. An experienced engineer also knows things no metric shows:
what depends on what, what a log message usually means, what is safe to do. The MCP
server publishes that knowledge as **resources**: read-only documents with a URI, which
the *client* reads (a tool, by contrast, is something the *model* decides to call).

| Resource | Content | Source |
| --- | --- | --- |
| `runbook://{service}` | dependencies, what its log messages mean, known failure modes, safe actions (Markdown) | `mcp-server/knowledge/runbooks/<service>.md` |
| `topology://{namespace}` | who calls whom (JSON) | `mcp-server/knowledge/topology/<namespace>.json` |
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
  `destructiveHint=false`, `idempotentHint=true` (`tool_helpers.py::READ_ONLY_TOOL`).
  The AI server gives the agent **only** tools annotated read-only
  (`mcp_client/tool_policy.py`); a tool without annotations counts as unsafe and is
  logged and left out. `GET /tools` shows `read_only` / `destructive` per tool. Hints
  are not security: RBAC still limits what the MCP server can do.
- **Completions:** autocomplete for resource arguments in MCP clients:
  `runbook://pay…` → `payment-service`, `payments-db`; `k8s://shop/deployments/…` lists
  the deployments (`k8s/completions.py`). MCP completions exist for resource-template
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

- **MCP sampling** (`mcp-server/k8s/log_summary.py`): the MCP server asks the
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
   (`mcp-server/prometheus/helpers.py::query_progress_reporter`). The AI server passes a
   `progress_callback` with every `call_tool`, which is what asks the server for progress.
2. **AI server → user (SSE).** `ai-server/investigation/events.py` collects three sources into one
   queue: LangChain callbacks (steps, tool calls, LLM calls, notes), MCP progress, and
   the final report or error. The route yields them with FastAPI's `EventSourceResponse`.

Closing the connection (Ctrl+C, a closed tab) cancels the investigation: the graph
stops and its pending MCP and LLM calls are cancelled.

MCP *logging* (`notifications/message`) is deprecated as of protocol 2026-07-28
(SEP-2577), so the server doesn't use it: progress messages carry the server's status
text, and `note` events carry the AI server's explanations.

## Comparing runs in Langfuse (Phase 12)

With Langfuse keys in `ai-server/.env`, every `make eval` and `make replay` run is
recorded as a Langfuse **experiment** (`evals/experiment_tracking.py`):

- The six incident cases are a dataset, `oncall-incidents` (question + expected
  `cause_category` and `root_cause_service`), created or updated on each run.
- A run is named after what produced it, e.g.
  `eval: openai:gpt-5.4-mini @ 40f7795 (2026-10-02 18:30)` (`-dirty` if there were
  uncommitted changes). `make replay TIMES=3` records three runs (`#1`–`#3`).
- Each case is one experiment item, with scores: `correct`, `category_correct`,
  `service_correct` (1/0) and the agent's `confidence`.
- The full investigation is inside the item's trace. For replay the reasoning runs in
  the same process. For eval the AI server is a separate process: the eval sends the
  W3C `traceparent` header with `/investigate`, and the AI server records its trace
  as a child of the experiment item (distributed tracing).
- Traces are also tagged `eval` / `replay` and `incident:<name>`.

**To compare models or prompts:** run `make eval` (or `make replay`), change
`LLM_MODEL` or the prompt, run again, then open **Datasets → oncall-incidents →
Experiments** in Langfuse and compare the runs side by side: pass rate, cost and
latency, per incident.

Without keys, eval and replay work exactly as before. A Langfuse error is printed
and never stops a run.

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
| MCP server and tools | `mcp-server/server.py`. The JSON Schema for each tool comes from its type hints (`Literal` → `enum`, `Field(ge, le)` → `minimum`/`maximum`), and the docstring becomes the description the LLM reads. |
| Discovery / invocation | `tools/list` in `mcp_client/langchain_tools.py`, `tools/call` through each LangChain tool |
| Tool errors | Schema violations and `ToolError` come back as `is_error=True`. The SDK hides the text of unexpected exceptions. |
| Transport | Streamable HTTP at `/mcp`. stdio is available with `MCP_TRANSPORT=stdio`. |
| Progress | `ctx.report_progress` in `get_service_overview`; the client opts in per call with `progress_callback` (`mcp_client/progress.py`). |
| Resources | `runbook://`, `topology://`, `k8s://` URI templates (`mcp-server/k8s/resources.py`); read by the client with `read_resource`. |
| Annotations / completions | `readOnlyHint` on every tool, enforced by the client; completions for resource-template arguments. |
| Elicitation | Write tools ask for approval with `Resolve`/`Elicit`; the AI server answers via `Client(elicitation_callback=…)` from `POST /actions/{id}/approval`. |
| Sampling | `get_pod_logs(summarize=true)` asks the client's LLM through `Resolve`/`Sample` with model preferences; the client answers with `Client(sampling_callback=…)` (`llm/sampling.py`). |
| Authorization | Bearer tokens checked by `MCPServer(token_verifier=…)` with `AuthSettings` (401 + protected resource metadata); scopes and roles enforced by server middleware (`MCPServer(middleware=[…])`). |
| Host / client | The AI server is the host. `mcp.Client` is the client. |

## License

MIT, see [LICENSE](./LICENSE).

# Project: AI On-Call Copilot using MCP

Learning-first build of an AI on-call assistant that investigates incidents across
Kubernetes and Prometheus via the Model Context Protocol (MCP). The goal is to
learn MCP deeply through a real project, not to rush to a finished product.

## Architecture (end state)

```text
                         ┌──────────────────┐
                         │      User        │
                         └────────┬─────────┘
                                  │
                                  ▼
                     ┌────────────────────────┐
                     │       AI SERVER        │
                     │                        │
                     │ FastAPI                │
                     │ LangGraph              │
                     │ LLM                    │
                     │ MCP Client             │
                     │ Investigation Logic    │
                     └───────────┬────────────┘
                                 │
                          MCP / HTTP
                                 │
                ┌────────────────┴─────────────────┐
                │                                  │
                ▼                                  ▼
       ┌──────────────────┐              ┌──────────────────┐
       │ Kubernetes MCP   │              │ Prometheus MCP   │
       │ Server            │              │ Server           │
       └────────┬─────────┘              └────────┬─────────┘
                │                                  │
                ▼                                  ▼
       ┌──────────────────┐              ┌──────────────────┐
       │ Local Kubernetes │              │   Prometheus     │
       │                  │              │                  │
       │ payment-service  │              │ Metrics          │
       │ order-service    │              │                  │
       │ user-service     │              │                  │
       └──────────────────┘              └──────────────────┘
```

## Roadmap

| Stage | What you build               | Priority    | Status |
| ----- | ----------------------------- | ----------- | ------ |
| 0     | Understand MCP architecture   | 🔴 Now      | Done (see README "MCP concepts") |
| 1     | Basic MCP server (fake tools) | 🔴 Now      | Done |
| 2     | AI server + MCP client        | 🔴 Now      | Done |
| 3     | Separate HTTP communication   | 🔴 Now      | Done |
| 4     | Docker                        | 🔴 Now      | Not started |
| 5     | Local Kubernetes (kind)       | 🔴 Now      | Not started |
| 6     | Real Kubernetes tools         | 🔴 Now      | Not started |
| 7     | Prometheus                    | 🟠 Next     | Not started |
| 8     | LangGraph investigation       | 🟠 Next     | Not started |
| 9     | Failure simulation            | 🟠 Next     | Not started |
| 10    | Write tools (restart/scale)   | 🟡 Later    | Not started |
| 11    | Human-in-the-loop approval    | 🟡 Later    | Not started |
| 12    | Authentication (API key)      | 🟡 Later    | Not started |
| 13    | Kubernetes RBAC               | 🟢 Advanced | Not started |
| 14    | Tool-level authorization       | 🟢 Advanced | Not started |
| 15    | Audit logging                 | 🟢 Advanced | Not started |
| 16    | Security hardening            | 🟢 Advanced | Not started |
| 17    | AI/MCP self-observability     | 🟢 Advanced | Not started |
| 18    | Advanced MCP features         | 🟢 Advanced | Not started |
| 19    | Multiple MCP servers          | 🟢 Advanced | Not started |

## Phase notes

### Phase 0 — Understand the architecture (a few hours, not days)
Concepts to learn: MCP Host, MCP Client, MCP Server, Tools, Resources, Prompts,
Transport.

- `AI Server` = MCP Host + MCP Client
- `Kubernetes MCP Server` = MCP Server
- `Prometheus MCP Server` = MCP Server

Flow: `AI → MCP Client → tools/list → AI chooses tool → tools/call → MCP Server
→ Kubernetes/Prometheus → result → AI`

### Phase 1 — First MCP server (fake data only)
```text
ai-oncall-mcp/
├── ai-server/
├── mcp-server/
└── README.md
```
Fake tools: `get_logs()`, `get_metrics()`, `get_pod_status()`, `list_deployments()`.
Learn: server init, tool definition/schema, discovery, invocation, response, MCP
Inspector. No AI server yet.

### Phase 2 — AI Server (independent app)
```text
ai-server/
├── main.py
├── agent/
├── mcp/
├── config/
```
Tech: Python, FastAPI, LangGraph, LLM, MCP Client. The AI server contains **no**
Kubernetes code — it only knows "I have these MCP tools available."

### Phase 3 — HTTP transport between the two servers
Use Streamable HTTP, not stdio, as the final transport.
`AI Server (localhost:8000) → MCP / Streamable HTTP → MCP Server (localhost:9000)`
Key lesson: AI Server and MCP Server are fully separate applications that don't
share Python code.

### Phase 4 — Dockerize
`docker-compose.yml` running `ai-server:8000` and `mcp-server:9000` on a shared
network.

### Phase 5 — Fake production environment
Install Docker Desktop, kind, kubectl. Create a kind cluster and 3 tiny FastAPI
services: `payment-service`, `order-service`, `user-service`. Learn: Pod,
Deployment, Service, Namespace, ConfigMap, Secret, ReplicaSet.

### Phase 6 — Connect MCP to real Kubernetes
Replace fake tool bodies with real Kubernetes Python client calls. Tools:
`list_pods`, `get_pod_logs`, `get_pod_status`, `list_deployments`,
`get_deployment`.

### Phase 7 — Add Prometheus
`Applications → Prometheus → Prometheus MCP Server → AI Server`. Learn basic
PromQL: `rate()`, `increase()`, `sum()`, `avg()`, `histogram_quantile()`. Target
questions: error rate, CPU usage, recent error-rate increase, failing requests.

### Phase 8 — The actual On-Call Agent (LangGraph)
```text
START → Understand incident → Check pods → Check logs → Check metrics
→ Check deployment history → Correlate evidence → Determine probable cause
→ Generate incident report → END
```
Output format: Incident / Evidence / Likely cause / Recommended action.

### Phase 9 — Failure simulation
Controlled failures to investigate:
1. Database failure
2. Bad deployment (v1 working → v2 broken)
3. High CPU endpoint
4. Crash-looping pod
5. Artificial latency (`sleep(5)`)

### Phase 10 — Write tools (dangerous operations)
Introduce `restart_pod()`, `scale_deployment()`, `rollback_deployment()` — all
previously read-only. This is where MCP gets interesting security-wise.

### Phase 11 — Human-in-the-loop
`AI recommends action → human Approve/Reject → only then MCP tools/call
executes`. No direct AI → destructive-action path.

### Phase 12 — Authentication
`AI Server → Bearer Token → MCP Server` validates caller identity. Start with a
simple API key / service token, evolve later — not OAuth on day one.

### Phase 13 — Kubernetes RBAC
Scope the MCP server's ServiceAccount down from cluster-admin to least privilege
(get/list pods, get logs, get deployments; no delete namespace / modify secrets).
Split into a read-only MCP and a separate operations MCP.

### Phase 14 — Tool-level authorization
A second authorization layer on top of Kubernetes RBAC: which human/role may
invoke which MCP tool (e.g. `get_logs` → developer, `restart_pod` → senior
engineer, `rollback_deployment` → authorized operator).

### Phase 15 — Audit logging
Record every tool call: user, tool, resource, timestamp, reason, approval,
result. Must be able to answer who/why/when/which-agent/who-approved.

### Phase 16 — Security hardening
Authentication, authorization, RBAC, secrets management, tool allowlists, input
validation, rate limiting, audit logs, prompt-injection defenses, tool-injection
defenses, network policies, TLS. Never expose an unrestricted
`execute_command(command: str)` tool — keep tools narrowly scoped
(`get_pod_logs(service)`, `restart_service(service)`, `scale_service(service,
replicas)`) with strict validation.

### Phase 17 — Observability of the AI system itself
Metrics on AI requests, LLM latency/tokens, MCP tool calls/latency/failures,
approval rate, investigation duration.

### Phase 18 — Advanced MCP concepts
Resources, Prompts, Sampling, Elicitation, Notifications, Progress, multiple MCP
servers, dynamic tool discovery, MCP auth, MCP gateways. Deep-dive phase, not
needed for v1.

### Phase 19 — Multiple MCP servers
```text
                       AI SERVER
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
           K8s MCP      Prom MCP     GitHub MCP
              │            │            │
              ▼            ▼            ▼
         Kubernetes    Prometheus     GitHub
```
Correlate Kubernetes + Prometheus + GitHub to explain incidents end-to-end
(deploy time, commit, error-rate spike, exception in logs).

## First milestone (day 1-2 target)

```text
                    ┌───────────────┐
                    │   AI SERVER   │
                    │               │
User ──────────────►│ FastAPI       │
                    │ LangGraph     │
                    │ MCP Client    │
                    └───────┬───────┘
                            │
                       MCP / HTTP
                            │
                            ▼
                    ┌───────────────┐
                    │  MCP SERVER   │
                    │               │
                    │ get_logs()    │
                    │ get_metrics() │
                    └───────────────┘
```
No Kubernetes. No Prometheus. No RBAC. No OAuth. No complicated UI. Get this
working end-to-end first so later failures are isolated to one layer (AI, MCP
transport, Kubernetes, or Prometheus) instead of five at once.

## Final project structure (target)

```text
ai-oncall-mcp/
│
├── ai-server/
│   ├── api/
│   ├── agent/
│   ├── graph/
│   ├── mcp/
│   ├── models/
│   └── config/
│
├── mcp-server/
│   ├── tools/
│   │   ├── kubernetes/
│   │   ├── observability/
│   │   └── deployments/
│   ├── auth/
│   ├── permissions/
│   └── server.py
│
├── sample-services/
│   ├── payment/
│   ├── order/
│   └── user/
│
├── kubernetes/
│   ├── namespace.yaml
│   ├── deployments/
│   ├── services/
│   ├── rbac/
│   └── monitoring/
│
├── prometheus/
├── docker/
├── tests/
├── docker-compose.yml
├── Makefile
└── README.md
```

## Working with Claude Code

Give Claude Code **one phase at a time**, not the whole roadmap, so the codebase
stays understandable and you actually learn from it. Example prompts:

> "Implement Phase 1 only. Create a standalone MCP server using the current
> official Python MCP SDK. Add three read-only tools with fake data. Do not
> implement FastAPI, LangGraph, Kubernetes, Docker, authentication, or any
> future-phase functionality. Explain the MCP concepts used and create tests."

> "Implement Phase 2. Create a completely separate FastAPI AI server with an MCP
> client that connects to the MCP server over Streamable HTTP. Do not move any
> MCP server code into the AI server."

Review each phase's output before moving to the next.

See [CONTRIBUTING.md](./CONTRIBUTING.md) for git commit rules for this project.

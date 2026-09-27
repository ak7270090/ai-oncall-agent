# AI On-Call Agent (MCP)

An AI on-call assistant that investigates incidents through the Model Context
Protocol. See [PLAN.md](./PLAN.md) for the roadmap. **Phases 1–5 are done.**
Code rules are in [CODING_GUIDELINES.md](./CODING_GUIDELINES.md).

```text
 User ──HTTP──► AI server :8000 ──MCP / Streamable HTTP──► MCP server :9000
                FastAPI                                     list_deployments
                LangGraph + LangChain                       get_pod_status
                any LLM (config)                            get_logs
                MCP client                                  get_metrics
                                                            (fake data)
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
│   ├── tools/                 kubernetes.py, observability.py
│   ├── data/fake_cluster.py   the fake incident
│   └── tests/
├── ai-server/
│   ├── main.py                create_app(), error → HTTP status mapping
│   ├── api/                   routes, schemas, dependencies
│   ├── agent/                 chat_model.py, graph.py, investigation.py, prompts.py
│   ├── mcp_client/            connection.py, tools.py (MCP → LangChain adapter)
│   ├── config/settings.py
│   └── tests/                 unit tests + integration/ (real HTTP)
├── sample-services/       Phase 5 "production" apps: user-, payment-, order-service
├── kubernetes/            kind cluster config + kustomize manifests (namespace shop)
├── scripts/               cluster-up / smoke-test / cluster-down (config: cluster.config.psd1)
├── docker/python-service.Dockerfile   one image recipe for every Python service
├── docker-compose.yml
└── CODING_GUIDELINES.md
```

## Setup (Windows / PowerShell)

```powershell
cd mcp-server
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt

cd ..\ai-server
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
copy .env.example .env      # set LLM_MODEL and LLM_API_KEY
```

### Choosing the LLM

Set two lines in `ai-server/.env`. No code changes are needed:

```ini
LLM_MODEL=openai:gpt-5.4-mini        # or anthropic:claude-opus-5, openai:gpt-5.5, ...
LLM_API_KEY=<key for that provider>
```

## Run with Docker

Needs Docker Desktop running and `ai-server/.env` created (see above).

```powershell
docker compose up -d --build --wait   # builds both images, waits until healthy
docker compose logs -f                # follow logs
docker compose down                   # stop
```

- Both services run on a private `oncall` network. The AI server reaches the
  MCP server at `http://mcp-server:9000/mcp`.
- Ports are published on `127.0.0.1` only: AI server `8000`, MCP server `9000`
  (for the Inspector). To change them, copy `.env.example` in the repo root to
  `.env` and edit it.
- Images run as a non-root user and contain no `.env`, tests or dev
  dependencies. The API key is passed in at runtime from `ai-server/.env`.
- Inside Docker the MCP server listens on `0.0.0.0`, so DNS-rebinding protection
  is enabled explicitly with `MCP_ALLOWED_HOSTS`.

## Run locally (without Docker)

```powershell
# terminal 1 — MCP server on http://127.0.0.1:9000/mcp
cd mcp-server; .\.venv\Scripts\python server.py

# terminal 2 — AI server on http://127.0.0.1:8000 (Swagger UI at /docs)
cd ai-server; .\.venv\Scripts\python main.py
```

| Endpoint | What it does |
| --- | --- |
| `GET /health` | Liveness check for the AI server only |
| `GET /ready` | Confirms the MCP server is reachable (runs `tools/list`) |
| `GET /tools` | Lists the tools the MCP server advertises |
| `POST /investigate` | `{"question": "..."}` → report and the tool calls made to produce it |

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

```powershell
.\scripts\cluster-up.ps1     # create cluster, build + load images, deploy, wait until Available
.\scripts\smoke-test.ps1     # place an order end-to-end through the three services
.\scripts\cluster-down.ps1   # delete the cluster (frees CPU/RAM)
```

(If script execution is blocked, run with
`powershell -ExecutionPolicy Bypass -File .\scripts\cluster-up.ps1`.)

| Kubernetes object | Where to look |
| --- | --- |
| Namespace | `kubernetes/namespace.yaml` (`shop`) |
| Deployment → ReplicaSet → Pod | `kubernetes/deployments/*.yaml`, 2 replicas each, probes, limits, non-root |
| Service | `kubernetes/services/*.yaml`, ClusterIP. order-service reaches `http://user-service` by DNS. |
| ConfigMap | `kubernetes/configmaps/*.yaml`, injected with `envFrom` |
| Secret | Generated by kustomize from `kubernetes/secrets/payment-service.env` (gitignored; the script creates it with a random key) |
| Downward API | The pod's `version` label becomes `APP_VERSION` |

Useful commands: `kubectl get deploy,rs,pods,svc -n shop`,
`kubectl logs -n shop deploy/order-service`,
`kubectl describe pod -n shop -l app=payment-service`.

## Test

```powershell
cd mcp-server; .\.venv\Scripts\python -m pytest -q
cd ai-server;  .\.venv\Scripts\python -m pytest -q
# sample services (shared dev venv: sample-services\.venv, from sample-services\requirements-dev.txt)
cd sample-services\order-service; ..\.venv\Scripts\python -m pytest -q   # same for user-/payment-service
```

- MCP server tests call the tools through a real MCP client, in-process.
- AI server unit tests use a scripted chat model and a small in-process MCP
  server. No network and no API key needed.
- `ai-server/tests/integration/` starts the real MCP server as a separate
  process on a free port and tests the Streamable HTTP transport.

## How an investigation runs

1. `POST /investigate` opens an MCP session (`connect_to_mcp`).
2. `tools/list` → each MCP tool becomes a LangChain tool (`mcp_client/tools.py`).
3. The LangGraph graph alternates between two nodes: `call_model` (the LLM with
   the tools bound) and `call_tools` (LangGraph `ToolNode`, which calls MCP
   `tools/call`). It stops when the model answers or after `MAX_AGENT_STEPS`.
4. Tool errors go back to the model as error messages so it can recover.

## MCP concepts used

| Concept | Where |
| --- | --- |
| MCP server and tools | `mcp-server/server.py`. The JSON Schema for each tool comes from its type hints (`Literal` → `enum`, `Field(ge, le)` → `minimum`/`maximum`), and the docstring becomes the description the LLM reads. |
| Discovery / invocation | `tools/list` in `mcp_client/tools.py`, `tools/call` through each LangChain tool |
| Tool errors | Schema violations and `ToolError` come back as `is_error=True`. The SDK hides the text of unexpected exceptions. |
| Transport | Streamable HTTP at `/mcp`. stdio is available with `MCP_TRANSPORT=stdio`. |
| Host / client | The AI server is the host. `mcp.Client` is the client. |

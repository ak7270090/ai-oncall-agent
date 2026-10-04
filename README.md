# AI On-Call Agent (MCP)

[![CI](https://github.com/ak7270090/ai-oncall-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/ak7270090/ai-oncall-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)

An AI on-call assistant that investigates incidents through the Model Context
Protocol. See [PLAN.md](./PLAN.md) for the roadmap. **Phases 1–13, 15–20 and 22 are
done.** Code rules are in [CODING_GUIDELINES.md](./CODING_GUIDELINES.md); security
notes in [SECURITY.md](./SECURITY.md).

```text
 User ──HTTP──► AI server :8000 ──MCP──► agentgateway :3000 ─┬─► k8s MCP server :9000 ────────► kind cluster (shop)
   (API key)    FastAPI, LangGraph,    (optional: one URL,   │     pods, logs, deployments,      │ scrape /metrics
                any LLM (config),       token check, rules)  │     events, runbooks, approved    ▼
                approvals                                    │     changes                     Prometheus
                                                             └─► prometheus MCP server :9001 ◄── PromQL
                                                                   service overview, metrics
```

The apps are fully separate: they share no code, and each has its own virtualenv,
requirements and settings. The AI server knows only the MCP servers' URLs (or the
gateway's).

## Layout

The repository is organized by what things are for. Inside each app, code is
organized by domain (see [CODING_GUIDELINES.md](./CODING_GUIDELINES.md) §5).

```text
ai-oncall-agent/
├── ai-server/                 the agent (FastAPI + LangGraph), organized by domain
│   ├── main.py                create_app(): includes the routers, error → HTTP status mapping
│   ├── config.py, errors.py, health.py (/health, /ready, /tools), tracing.py (Langfuse)
│   ├── investigation/         POST /investigate(/stream): router, schemas, service (entry point), models,
│   │   │                      prompts, events (live events)
│   │   ├── workflow/          graph.py (wiring), nodes.py (the steps), state.py
│   │   └── evidence/          collection_steps.py (deterministic checks), analysis.py (rules), mcp_toolbox.py
│   ├── actions/               POST /actions: router, registry (waits for approval), schemas
│   ├── auth/                  API keys, MCP tokens and their key pair
│   ├── llm/                   chat model (provider-agnostic), model router, sampling
│   ├── mcp_client/            connections (one, several, or a gateway), LangChain adapter, MCP names
│   └── tests/                 unit + integration/ (real HTTP, real MCP server process)
├── mcp-platform/              the tool side of MCP
│   ├── server/                one codebase, run as the k8s and the prometheus MCP server (MCP_TOOLSETS)
│   │   ├── server.py, config.py, constants.py, tool_helpers.py, fake_incident.py
│   │   ├── k8s/               Kubernetes tools, write tools, runbook resources, backends, fakes
│   │   ├── prometheus/        metric tools, PromQL, backends, fakes
│   │   ├── access/            tokens, roles, four eyes, audit log
│   │   ├── knowledge/         runbooks/<service>.md, topology/<namespace>.json
│   │   ├── deploy/            the server's ServiceAccounts and RBAC (applied with the lab)
│   │   └── tests/             k8s/, prometheus/, shared; integration/ (live kind cluster)
│   └── gateway/               agentgateway.yaml; bin/ (downloaded binary, ignored)
├── lab/                       the fake production the agent investigates
│   ├── services/              user-, payment-, order-service (FastAPI), each with Dockerfile and tests
│   └── kubernetes/            kind-cluster.yaml; base/ (one folder per workload, ns shop),
│                              incidents/ (one Kustomize overlay per incident), monitoring/ (Prometheus)
├── evals/                     incident eval: incident_cases.py, run_eval.py, replay.py, experiment_tracking.py
├── docs/                      architecture, lab, evals, observability, MCP features, security (see below)
├── compose.yaml               AI server + both MCP servers (fake data);
│                              overlays: compose.kind.yaml (kind cluster), compose.gateway.yaml (gateway + tokens)
├── keys/                      MCP token key pair from `make mcp-keys` (ignored)
├── Makefile                   every command: make help
├── ruff.toml                  lint rules; each Python project's pyproject.toml extends them
├── .github/workflows/ci.yml   lint + tests on every push
└── CODING_GUIDELINES.md, PLAN.md, SECURITY.md, LICENSE (MIT)
```

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
| `make setup` | Virtualenv + dependencies for each app, creates `ai-server/.env` and `mcp-platform/server/.env` |
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
| `POST /investigate/stream` | Same investigation, streamed live as Server-Sent Events (see [Observability](./docs/observability.md#live-progress-phase-15)) |

With `API_KEYS` set, every endpoint except `/health` and `/ready` needs an
`X-API-Key` header (see [sign-in and roles](./docs/actions-and-security.md)).

Errors: MCP server unreachable → `503`; LLM provider failure → `502` (details go
to the server log only). The table is in `ai-server/errors.py`, shared by both
investigate endpoints.

To call MCP tools by hand, open the [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
with `npx @modelcontextprotocol/inspector` and connect with Streamable HTTP to
`http://127.0.0.1:9000/mcp` (with `MCP_AUTH_JWKS_PATH` set it needs a bearer token).

## Test

```bash
make test
```

This expects three virtualenvs: `mcp-platform/server/.venv`, `ai-server/.venv` and
`lab/services/.venv` (from `lab/services/requirements-dev.txt`).

- MCP server tests call the tools through a real MCP client, in-process.
- AI server unit tests use a scripted chat model and a small in-process MCP
  server. No network and no API key needed.
- `ai-server/tests/integration/` starts the real MCP server as a separate
  process on a free port and tests the Streamable HTTP transport.

## Documentation

| Topic | What's in it |
| --- | --- |
| [Architecture](./docs/architecture.md) | How an investigation runs and which MCP features the project uses. |
| [The lab: a fake production on kind](./docs/lab.md) | The system the agent investigates: sample services on a kind cluster, the read-only Kubernetes tools, and Prometheus. |
| [Evaluation](./docs/evals.md) | Injected incidents, grading, replay, and comparing runs as Langfuse experiments. |
| [Observability](./docs/observability.md) | Tracing every investigation in Langfuse, and streaming its progress live. |
| [Advanced MCP features](./docs/mcp-features.md) | Resources, annotations and completions, sampling and model routing. |
| [Changes, security and the gateway](./docs/actions-and-security.md) | Approved changes, sign-in, roles, four eyes, the audit log, and the MCP gateway. |
| [PLAN.md](./PLAN.md) | Roadmap: every phase, what was built and measured |
| [CODING_GUIDELINES.md](./CODING_GUIDELINES.md) | Structure, naming and code rules |
| [SECURITY.md](./SECURITY.md) | Reporting vulnerabilities; how the project protects itself |

## License

MIT, see [LICENSE](./LICENSE).

# AI On-Call Agent (MCP)

An AI on-call assistant that investigates incidents through the Model Context
Protocol. See [PLAN.md](./PLAN.md) for the roadmap. **Phases 1–4 are done.**
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
├── docker/python-service.Dockerfile   one image recipe for both services
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

## Test

```powershell
cd mcp-server; .\.venv\Scripts\python -m pytest -q
cd ai-server;  .\.venv\Scripts\python -m pytest -q
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

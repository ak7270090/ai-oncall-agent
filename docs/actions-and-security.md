# Changes, security and the gateway

Approved changes, sign-in, roles, four eyes, the audit log, and the MCP gateway.

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

- **Write tools** (`mcp-platform/server/k8s/deployments.py`, off unless `MCP_ENABLE_WRITE_TOOLS=true`):
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
  `mcp-platform/server/deploy/mcp-operator.yaml`). `make mcp-kubeconfig` writes its kubeconfig.
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
  (`MCPServer(token_verifier=…, auth=AuthSettings(…))`, `mcp-platform/server/access/tokens.py`)
  answers 401 without a valid one and publishes OAuth protected resource metadata at
  `/.well-known/oauth-protected-resource/mcp`.
- **Scopes:** investigations get `k8s:read`, so the MCP server doesn't even list the write
  tools to them; `POST /actions` gets `k8s:read k8s:write`.
- **Roles** (`MCP_USER_ROLES`, `MCP_ROLE_WRITE_TOOLS`): every role may read; `developer`
  no write tools, `oncall` restart and scale, `lead` also roll back. A server middleware
  (`mcp-platform/server/access/middleware.py`) refuses before the tool runs.
- **Four eyes:** the person who starts an action can't approve it (403 at the AI server),
  and the MCP server checks again: the approver named in the elicitation answer must be
  someone else whose role may run that tool.
- **Audit log** (one per MCP server, `logs/audit-k8s.jsonl`, JSON lines, append-only): every tool call with
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
`mcp-platform/server/.env`; `EVAL_API_KEY=<key> make eval`.

Verified on the kind cluster (bad-deploy): a developer's investigation proposed the
rollback; the oncall user was refused; the lead who started it couldn't approve it
(403); an oncall approver was refused by the MCP server; a second lead's approval rolled
it back (error rate → 0). `make audit` showed all of it with the trace links.

## Two MCP servers behind a gateway (Phase 22)

The tool side of MCP is **two servers** (`mcp-platform/server/`), each with its own entry
point, and **agentgateway** in front of them. The gateway is mandatory: the AI server
knows only the gateway's URL, and the MCP servers aren't reachable otherwise in Docker.

```text
AI server ──► agentgateway :3000 ─┬─► Kubernetes MCP server :9000   python -m k8s.server
 (one URL)    token check,        │     pods, deployments, events, runbooks, write tools
              which tools a token └─► Prometheus MCP server :9001   python -m prometheus.server
              may reach                 service overview, metrics
```

- **Two servers, one codebase:** `k8s/server.py` and `prometheus/server.py` each build
  their server on `base_server.py` (token check, audit and role middleware, `/health`)
  and add only their own tools and backends: the Prometheus server holds no Kubernetes
  credentials. Each has its own name, port and audit log (`MCP_K8S_SERVER__PORT`, …).
- **Who checks what:**

  | | Gateway | MCP servers |
  | --- | --- | --- |
  | Token valid? (401 otherwise) | yes | yes again: they learn the person from it |
  | Which tools a token may reach (read vs write scope) | yes (CEL rules) | no |
  | Roles, four eyes (approver ≠ requester, approver's role) | no | yes: needs the role map and the tool's approval answer |
  | Audit log | access log | every call, approval and outcome, with the trace id |

- **The gateway** (`mcp-platform/gateway/agentgateway.yaml`, agentgateway v1.6.0):
  multiplexes both servers on one URL. Tool names get the target as prefix
  (`k8s_list_pods`, `k8s+runbook://…`), which the AI server maps back
  (`MCP_GATEWAY_TARGETS`, `ai-server/mcp_client/server_group.py`). CEL rules: metrics and
  Kubernetes reads for everyone signed in, write tools only with scope `k8s:write`, the
  team-knowledge resources for everyone signed in. Whatever no rule allows is hidden and
  refused before it reaches a server. Progress, log summaries (sampling) and approvals
  (elicitation) pass through: protocol 2026-07-28's "input required" rounds are plain
  requests.
- **Tokens signed with a key pair (RS256):** the AI server signs with
  `keys/mcp-token-private.pem`; the gateway and the servers verify with `keys/jwks.json`
  (`make mcp-keys`, run by `make setup` and `make up`). Verifiers can't mint tokens.
- **Why agentgateway:** open source (Linux Foundation), one binary or container, YAML
  config, and it supports protocol 2026-07-28 (use ≥ v1.6.0: earlier versions broke tool
  calls with two or more servers). IBM ContextForge still implements 2025-11-25.

Verified on the kind cluster (when built): two serversVerified on the kind cluster: two servers directly: eval 6/6, proposed fixes 3/3. Through the gateway: the first run lost the runbooks (resources were renamed to `k8s+runbook://…` and no CEL rule allowed them); fixed, the evidence matched the direct run item for item. high-cpu then failed once because the incident's CPU load had faded (peak throttling 92% → 23%, then no symptom at all); in Docker (`make up-kind`) high-cpu and bad-deploy passed. Approvals through the gateway: four eyes enforced, rollback done, error rate → 0. Gateway overhead: +1 to +4 ms per tool call (median of 30). In Docker the gateway forwards `Host` without a port, so the servers' allowed hosts list the bare names.

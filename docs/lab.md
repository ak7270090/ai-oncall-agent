# The lab: a fake production on kind

You can't learn on-call without something to be on call *for*. So this project ships its own
small "production": a little online shop running on a Kubernetes cluster on your laptop, with
real traffic, real metrics and real things to break.

## The shop

Three small FastAPI services, a Postgres database and a traffic generator that keeps placing
orders, like customers would.

```text
                      namespace: shop
 traffic-generator ──► order-service ──► user-service       GET  /users/{id}
                            │
                            └──────────► payment-service    POST /payments ──► payments-db (Postgres)
```

When an order comes in, order-service checks the user and then asks payment-service to charge
them. If anything along that chain breaks, checkout fails, which is exactly the kind of thing the
agent has to untangle.

### Start it

You need Docker Desktop running, plus `kind` and `kubectl`
(`winget install Kubernetes.kind Kubernetes.kubectl` on Windows).

```bash
make cluster-up     # create the cluster, build and load the images, deploy, wait until ready
make smoke-test     # place one order from inside the cluster, to check it works
make cluster-down   # delete the cluster and free the CPU and memory
```

**Windows note:** Kubernetes 1.35+ needs WSL to use cgroup v2. Add this to
`%USERPROFILE%\.wslconfig`, then run `wsl --shutdown` and restart Docker:

```ini
[wsl2]
kernelCommandLine = cgroup_no_v1=all
```

### What's inside

It's a deliberately normal Kubernetes setup, so the agent sees what it would see in a real
cluster:

| Kubernetes object | Where it lives |
| --- | --- |
| Namespace `shop` | `lab/kubernetes/base/namespace.yaml` |
| Deployments (2 replicas each, health probes, CPU and memory limits, non-root) | `lab/kubernetes/base/<service>/deployment.yaml` |
| Services (order-service finds `http://user-service` by DNS) | `lab/kubernetes/base/<service>/service.yaml` |
| ConfigMaps | `lab/kubernetes/base/<service>/configmap.yaml` |
| Secrets (API key, database password), generated with random values by `make cluster-up` and never committed | `lab/kubernetes/base/<service>/secret.env` |

To poke around yourself: `kubectl get deploy,rs,pods,svc -n shop`,
`kubectl logs -n shop deploy/order-service`, `kubectl describe pod -n shop -l app=payment-service`.

## The agent's eyes on Kubernetes

The Kubernetes MCP server lets the agent look at the cluster, the same things you'd check with
`kubectl`, but **it can only look, never touch**.

| Tool | What the agent can see |
| --- | --- |
| `list_pods` | Every pod: running or not, ready or not, restart count, and a one-word status like `CrashLoopBackOff` |
| `get_pod_status` | Per container: what state it's in, why it last stopped, its exit code |
| `get_pod_logs` | The latest log lines, or the logs of the container that just crashed |
| `list_deployments` | Image, version, and how many replicas are wanted vs actually ready |
| `get_deployment` | Its conditions and rollout history, to spot "it broke right after the new version went out" |
| `list_events` | Recent warnings: crash back-offs, failed image pulls, failing health checks |

The tools return only these fields. They never return environment variables or anything else in
the pod spec, so secrets can't leak into the LLM's prompt.

### Why it can't break anything

There are two walls, and either one is enough on its own:

1. **Kubernetes itself says no.** The MCP server runs as a ServiceAccount that may only *read*
   pods, logs, events and deployments in the `shop` namespace: no Secrets, no other namespaces,
   no writes. Even a bug in our code can't get past the Kubernetes API server.
   (`mcp-platform/server/deploy/mcp-server.yaml`)
2. **The tools are careful too.** There's a namespace allowlist, the tool inputs are validated
   (at most 500 log lines, for example), the output is trimmed, and errors are readable.

It also never uses your own admin access. `make mcp-kubeconfig` (run by `make cluster-up`)
creates a **short-lived token** for that ServiceAccount, valid for 24 hours by default. Rerun it
when the token expires.

### Fake data or the real cluster

| `MCP_BACKEND` | When it's used | What the agent sees |
| --- | --- | --- |
| `kubernetes` (default) | `make up-kind`, `make run-mcp-servers` | The real kind cluster and its Prometheus |
| `fake` | `make up`, the unit tests | A canned incident, so you can try everything without a cluster |

**Try it:** run `make cluster-up`, break something
(`kubectl -n shop set image deploy/payment-service payment-service=payment-service:v2`), start
the stack with `make up-kind`, and ask `/investigate` what's wrong.

## Metrics with Prometheus

Logs tell you *what* went wrong. Metrics tell you *how bad* it is and *when* it started.

```text
shop services ──/metrics──► Prometheus ──HTTP API──► Prometheus MCP server ──► agent
traffic-generator: 4 workers × about 1 order per second
```

- **Every service reports its own numbers:** request counts by route and status, a latency
  histogram, CPU and memory.
- **Prometheus** runs in its own `monitoring` namespace, may only look at the `shop` namespace,
  keeps 6 hours of data, and is only reachable from your machine at `http://127.0.0.1:9090`.
- **The traffic generator** keeps orders flowing, including a few for users that don't exist,
  so some 404s are normal. That way there's always something real to measure.

| Tool | What the agent gets |
| --- | --- |
| `get_service_overview` | Request rate, error rate and p99 latency for every service right now, to find which one is in trouble |
| `get_metrics` | The history of one metric, one point per minute, to see *when* things changed |

<details>
<summary>The PromQL behind each metric</summary>

From `mcp-platform/server/prometheus/metrics/queries.py`, where `sel` is
`namespace="shop",service="…"`:

| Metric | PromQL |
| --- | --- |
| `request_rate` | `sum(rate(http_requests_total{sel}[1m]))` |
| `error_rate` | `(sum(rate(http_requests_total{sel,status="5xx"}[1m])) or vector(0)) / sum(rate(http_requests_total{sel}[1m]))` |
| `error_count` | `sum(increase(http_requests_total{sel,status="5xx"}[1m]))` |
| `latency_p99_ms` | `1000 * histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{sel}[1m])))` |
| `cpu_cores` | `sum(rate(process_cpu_seconds_total{sel}[1m]))` |
| `memory_mb` | `avg(process_resident_memory_bytes{sel}) / 1048576` |

Open `http://127.0.0.1:9090` to try them yourself.

</details>

**Safety:** service names are checked against a strict pattern before they go into a query, so a
crafted name can't rewrite the PromQL. The namespace allowlist applies here too.

**Try it:** with the cluster up, run `kubectl -n shop scale deploy/payment-service --replicas=0`.
Within about a minute order-service's error rate climbs and its logs say
`upstream unavailable: POST http://payment-service/payments`. Ask `/investigate` why checkout
fails, then bring payment-service back with `--replicas=2`.

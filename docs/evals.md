# Evaluation

Injected incidents, grading, replay, and comparing runs as Langfuse experiments.

## Incidents and evaluation (Phase 9)

Six realistic failures, each a kustomize overlay on the healthy base
(`lab/kubernetes/incidents/<name>`). Inject one with `make incident NAME=<name>`
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

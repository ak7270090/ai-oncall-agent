# payment-service

`POST /payments`: approves a payment and stores it in Postgres (payments-db, port 5432,
host from `DB_HOST`).

## Dependencies
- payments-db (Postgres)

## What its logs mean
- `database unavailable: payments-db:5432 (... connection refused / could not resolve
  host ...)`: payments-db is down, has no ready pod, or `DB_HOST` points at a host that
  doesn't exist. Root cause is payments-db (or its config), payment-service is the
  messenger.
- Startup crash with `could not resolve host` / exit code 1 and restarts: the pod can't
  start; check the previous container's logs and the deployment's recent changes.
- Tracebacks (`KeyError`, 500 responses) right after a new version rolled out: a bad
  release; compare with the previous revision.

## Known failure modes
| Signal | Usual cause |
| --- | --- |
| 503 + `database unavailable` | payments-db down or unreachable |
| CrashLoopBackOff | bad config or missing dependency at startup |
| 500s since a rollout, DB fine | bad deployment |
| p99 of seconds, no errors, CPU low | slow processing or a slow dependency |

## Safe actions
Rollback to the previous revision if a release broke it. Restart is safe. Never scale
to 0: checkout stops completely.

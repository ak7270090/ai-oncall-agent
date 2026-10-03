# payments-db

Postgres 16 for payment-service. Single replica, port 5432, data in an emptyDir volume
(lab only: data is lost when the pod is replaced).

## What to look at
- No pods / 0 ready replicas: payment-service logs `database unavailable ... connection
  refused`, order-service returns 502s. Root cause: payments-db.
- Readiness probe failures shortly after start are normal while Postgres boots.

## Safe actions
Scale back to 1 replica. Don't run two replicas: this is not a replicated setup.

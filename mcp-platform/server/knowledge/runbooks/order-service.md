# order-service

Entry point of checkout: `POST /orders`. For each order it calls
`GET user-service/users/{id}`, then `POST payment-service/payments`.

## Dependencies
- user-service (user lookup), payment-service (payment)

## What its logs mean
- `upstream unavailable: <METHOD> <url> (ConnectError...)`: the called service has no
  ready pods or refuses connections. The cause is in that service, not here.
- `upstream error <code>: <METHOD> <url>`: the called service answered with an error.
  Look at that service's logs and error rate.
- `slow upstream call: <METHOD> <url> took <n>s`: the called service is slow. Find out
  why there (its CPU throttling, its own dependencies).
- 404 for user 4 is expected: the traffic generator asks for a user that doesn't exist.

## Usually a victim
order-service errors and latency are almost always caused by a dependency. Check
user-service and payment-service before blaming order-service itself.

## Safe actions
Restart is safe (stateless). Scaling up does not help when a dependency is the cause.

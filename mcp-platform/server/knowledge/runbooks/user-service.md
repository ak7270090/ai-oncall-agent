# user-service

`GET /users/{id}`: user lookup for order-service. No dependencies of its own.

## Resources
CPU limit 250m per pod (2 pods). CPU-heavy work per request quickly hits that limit.

## What to look at
- Latency rising with `cpu_throttled_ratio` high and CPU close to the 250m limit: the
  service is CPU-starved (resource exhaustion), even when average CPU looks moderate.
  order-service then logs `slow upstream call: GET http://user-service/users/...`.
- 404 for user 4 is expected traffic, not an incident.

## Safe actions
Scale up or raise the CPU limit to relieve CPU starvation; find the change that made
requests expensive. Restart alone doesn't help.

#!/usr/bin/env bash
# Places an order through order-service, which calls user-service and payment-service
# inside the cluster. Exercises Service DNS, ConfigMap URLs and the payment Secret.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

require_tools kubectl curl

kubectl port-forward --namespace "$NAMESPACE" "service/$SMOKE_TEST_SERVICE" \
    "$SMOKE_TEST_LOCAL_PORT:$SMOKE_TEST_SERVICE_PORT" > /dev/null &
port_forward_pid=$!
trap 'kill "$port_forward_pid" 2> /dev/null || true' EXIT

base_url="http://127.0.0.1:$SMOKE_TEST_LOCAL_PORT"
for ((attempt = 0; attempt < SMOKE_TEST_STARTUP_SECONDS * 2; attempt++)); do
    curl --silent --fail "$base_url/health" > /dev/null && break
    sleep 0.5
done
curl --silent --fail "$base_url/health" > /dev/null || die "port-forward to $SMOKE_TEST_SERVICE never came up"

response="$(curl --silent --show-error --fail -X POST "$base_url/orders" \
    -H "content-type: application/json" -d '{"user_id": 1, "amount": 42.5}')"
echo "$response"
[[ $response == *'"status":"confirmed"'* ]] || die "order was not confirmed"
log "Smoke test passed"

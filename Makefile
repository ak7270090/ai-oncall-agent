CLUSTER         ?= oncall-lab
NAMESPACE       ?= shop
TAG             ?= v1
ROLLOUT_TIMEOUT ?= 180s
SMOKE_IMAGE     ?= curlimages/curl:8.10.1
SERVICES        := user-service payment-service order-service
SECRET_ENV      := kubernetes/secrets/payment-service.env
VENV_BIN        := $(if $(filter Windows_NT,$(OS)),Scripts,bin)

.PHONY: help up down logs test cluster-up cluster-down smoke-test

help:
	@echo "up / down / logs    AI server + MCP server with docker compose"
	@echo "test                run every test suite"
	@echo "cluster-up          kind cluster with the sample services (namespace $(NAMESPACE))"
	@echo "smoke-test          place an order through order-service inside the cluster"
	@echo "cluster-down        delete the kind cluster"

up:
	docker compose up -d --build --wait

down:
	docker compose down

logs:
	docker compose logs -f

test:
	cd mcp-server && .venv/$(VENV_BIN)/python -m pytest -q
	cd ai-server && .venv/$(VENV_BIN)/python -m pytest -q
	for svc in $(SERVICES); do (cd sample-services/$$svc && ../.venv/$(VENV_BIN)/python -m pytest -q) || exit 1; done

cluster-up: $(SECRET_ENV)
	kind get clusters | grep -qx $(CLUSTER) || kind create cluster --name $(CLUSTER) --config kubernetes/kind-cluster.yaml
	kubectl config use-context kind-$(CLUSTER)
	for svc in $(SERVICES); do \
		docker build -q -t $$svc:$(TAG) sample-services/$$svc && \
		kind load docker-image $$svc:$(TAG) --name $(CLUSTER) || exit 1; \
	done
	kubectl apply -k kubernetes
	kubectl wait deployment --all -n $(NAMESPACE) --for=condition=Available --timeout=$(ROLLOUT_TIMEOUT)
	kubectl get deployments,replicasets,pods,services -n $(NAMESPACE)

# Generated once with a random dev key; gitignored.
$(SECRET_ENV):
	sed "s/^PAYMENT_API_KEY=.*/PAYMENT_API_KEY=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')/" $@.example > $@

smoke-test:
	kubectl run smoke-test -n $(NAMESPACE) --rm -i --quiet --restart=Never --image=$(SMOKE_IMAGE) -- \
		curl -sS --fail -X POST http://order-service/orders \
		-H "content-type: application/json" -d '{"user_id": 1, "amount": 42.5}'

cluster-down:
	kind delete cluster --name $(CLUSTER)

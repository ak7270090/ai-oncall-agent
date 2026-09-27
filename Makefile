CLUSTER         ?= oncall-lab
NAMESPACE       ?= shop
MONITORING_NS   ?= monitoring
TAG             ?= v1
ROLLOUT_TIMEOUT ?= 180s
SMOKE_IMAGE     ?= curlimages/curl:8.10.1
SERVICES        := user-service payment-service order-service
SECRET_ENV      := kubernetes/secrets/payment-service.env
PYTHON_APPS     := mcp-server ai-server sample-services
PYTHON          ?= $(if $(filter Windows_NT,$(OS)),python,python3)
VENV_BIN        := $(if $(filter Windows_NT,$(OS)),Scripts,bin)
MCP_KUBE_DIR    := mcp-server/.kube
MCP_TOKEN_TTL   ?= 24h
KIND_API_INTERNAL = https://$(CLUSTER)-control-plane:6443
COMPOSE_KIND    := CLUSTER=$(CLUSTER) docker compose -f docker-compose.yml -f docker-compose.kind.yml

.PHONY: images redeploy help setup run-mcp-server run-ai-server up up-kind down logs test cluster-up cluster-down smoke-test mcp-kubeconfig

help:
	@echo "setup               create a virtualenv per app, install deps, create ai-server/.env"
	@echo "run-mcp-server      MCP server locally on http://127.0.0.1:9000/mcp"
	@echo "run-ai-server       AI server locally on http://127.0.0.1:8000"
	@echo "up / down / logs    AI server + MCP server with docker compose (fake cluster data)"
	@echo "up-kind             same, but the MCP server reads the kind cluster"
	@echo "test                run every test suite"
	@echo "cluster-up          kind cluster: sample services + traffic ($(NAMESPACE)), Prometheus on :9090 ($(MONITORING_NS))"
	@echo "redeploy            rebuild sample-service images and restart them in the cluster"
	@echo "smoke-test          place an order through order-service inside the cluster"
	@echo "mcp-kubeconfig      fresh read-only credentials for the MCP server (token TTL $(MCP_TOKEN_TTL))"
	@echo "cluster-down        delete the kind cluster"

setup:
	for app in $(PYTHON_APPS); do \
		$(PYTHON) -m venv $$app/.venv && \
		$$app/.venv/$(VENV_BIN)/python -m pip install -q --upgrade pip && \
		$$app/.venv/$(VENV_BIN)/python -m pip install -q -r $$app/requirements-dev.txt || exit 1; \
	done
	test -f ai-server/.env || cp ai-server/.env.example ai-server/.env

run-mcp-server:
	cd mcp-server && .venv/$(VENV_BIN)/python server.py

run-ai-server:
	cd ai-server && .venv/$(VENV_BIN)/python main.py

up:
	docker compose up -d --build --wait

up-kind: mcp-kubeconfig
	$(COMPOSE_KIND) up -d --build --wait

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
	$(MAKE) images
	kubectl apply -k kubernetes/monitoring
	kubectl apply -k kubernetes
	kubectl wait deployment --all -n $(NAMESPACE) --for=condition=Available --timeout=$(ROLLOUT_TIMEOUT)
	kubectl wait deployment --all -n $(MONITORING_NS) --for=condition=Available --timeout=$(ROLLOUT_TIMEOUT)
	kubectl get deployments,pods,services -n $(NAMESPACE)
	kubectl get deployments,pods,services -n $(MONITORING_NS)
	$(MAKE) mcp-kubeconfig

images:
	for svc in $(SERVICES); do \
		docker build -q -t $$svc:$(TAG) sample-services/$$svc && \
		kind load docker-image $$svc:$(TAG) --name $(CLUSTER) || exit 1; \
	done

# Same tag, new image: pods only pick it up after a restart.
redeploy: images
	for svc in $(SERVICES); do kubectl rollout restart deployment/$$svc -n $(NAMESPACE) || exit 1; done
	kubectl rollout status deployment -n $(NAMESPACE) -l app.kubernetes.io/part-of=shop --timeout=$(ROLLOUT_TIMEOUT)

# Kubeconfigs for the read-only `mcp-server` ServiceAccount: `config` for running on
# the host, `config.internal` for containers on kind's Docker network.
mcp-kubeconfig:
	mkdir -p $(MCP_KUBE_DIR)
	ca=$$(kubectl config view --raw --minify --context kind-$(CLUSTER) -o jsonpath='{.clusters[0].cluster.certificate-authority-data}') && \
	server=$$(kubectl config view --minify --context kind-$(CLUSTER) -o jsonpath='{.clusters[0].cluster.server}') && \
	token=$$(kubectl create token mcp-server -n $(NAMESPACE) --duration=$(MCP_TOKEN_TTL) --context kind-$(CLUSTER)) && \
	for target in "config $$server" "config.internal $(KIND_API_INTERNAL)"; do \
		set -- $$target; \
		printf '%s\n' "apiVersion: v1" "kind: Config" "current-context: mcp-server" \
			"clusters: [{name: kind, cluster: {server: '$$2', certificate-authority-data: '$$ca'}}]" \
			"users: [{name: mcp-server, user: {token: '$$token'}}]" \
			"contexts: [{name: mcp-server, context: {cluster: kind, user: mcp-server, namespace: $(NAMESPACE)}}]" \
			> $(MCP_KUBE_DIR)/$$1 || exit 1; \
	done
	@echo "wrote $(MCP_KUBE_DIR)/config and config.internal (expire in $(MCP_TOKEN_TTL))"

# Generated once with a random dev key; gitignored.
$(SECRET_ENV):
	sed "s/^PAYMENT_API_KEY=.*/PAYMENT_API_KEY=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')/" $@.example > $@

smoke-test:
	kubectl run smoke-test -n $(NAMESPACE) --rm -i --quiet --restart=Never --image=$(SMOKE_IMAGE) -- \
		curl -sS --fail -X POST http://order-service/orders \
		-H "content-type: application/json" -d '{"user_id": 1, "amount": 42.5}'

cluster-down:
	kind delete cluster --name $(CLUSTER)

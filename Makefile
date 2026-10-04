CLUSTER         ?= oncall-lab
NAMESPACE       ?= shop
MONITORING_NS   ?= monitoring
TAG             ?= v1
ROLLOUT_TIMEOUT ?= 180s
SMOKE_IMAGE     ?= curlimages/curl:8.10.1
SERVICES        := user-service payment-service order-service
BASE_DIR        := kubernetes/base
SECRET_ENVS     := $(BASE_DIR)/secrets/payment-service.env $(BASE_DIR)/secrets/payments-db.env
BAD_DEPLOY_TAG  ?= v2
INCIDENTS       := $(notdir $(wildcard kubernetes/incidents/*))
PYTHON_APPS     := mcp-server ai-server sample-services
PYTHON          ?= $(if $(filter Windows_NT,$(OS)),python,python3)
VENV_BIN        := $(if $(filter Windows_NT,$(OS)),Scripts,bin)
MCP_KUBE_DIR    := mcp-server/.kube
MCP_TOKEN_TTL   ?= 24h
K8S_MCP_PORT    ?= 9000
PROMETHEUS_MCP_PORT ?= 9001
GATEWAY_PORT    ?= 3000
GATEWAY_VERSION ?= v1.6.0
GATEWAY_ASSET   := agentgateway-$(if $(filter Windows_NT,$(OS)),windows-amd64.exe,$(if $(filter Darwin,$(shell uname -s)),darwin-arm64,linux-amd64))
GATEWAY_BIN     := gateway/bin/$(GATEWAY_VERSION)-$(GATEWAY_ASSET)
KEYS_DIR        := keys
KIND_API_INTERNAL = https://$(CLUSTER)-control-plane:6443
COMPOSE_KIND    := CLUSTER=$(CLUSTER) docker compose -f docker-compose.yml -f docker-compose.kind.yml
COMPOSE_GATEWAY := $(COMPOSE_KIND) -f docker-compose.gateway.yml

.PHONY: images redeploy help setup run-mcp-server run-mcp-servers run-gateway mcp-keys up-kind-gateway run-ai-server up up-kind down logs test lint cluster-up cluster-down smoke-test mcp-kubeconfig incident incident-reset eval replay audit new-secret

help:
	@echo "setup               create a virtualenv per app, install deps, create ai-server/.env"
	@echo "run-mcp-server      one MCP server with every tool, locally on http://127.0.0.1:9000/mcp"
	@echo "run-mcp-servers     two MCP servers: Kubernetes on :$(K8S_MCP_PORT), Prometheus on :$(PROMETHEUS_MCP_PORT)"
	@echo "mcp-keys            key pair for MCP tokens: $(KEYS_DIR)/mcp-token-private.pem (AI server), $(KEYS_DIR)/jwks.json"
	@echo "run-gateway         agentgateway $(GATEWAY_VERSION) on :$(GATEWAY_PORT) in front of run-mcp-servers"
	@echo "up-kind-gateway     like up-kind, with both MCP servers behind agentgateway"
	@echo "run-ai-server       AI server locally on http://127.0.0.1:8000"
	@echo "up / down / logs    AI server + MCP server with docker compose (fake cluster data)"
	@echo "up-kind             same, but the MCP server reads the kind cluster"
	@echo "test                run every test suite"
	@echo "lint                ruff over the whole repository (rules in ruff.toml)"
	@echo "cluster-up          kind cluster: sample services + traffic ($(NAMESPACE)), Prometheus on :9090 ($(MONITORING_NS))"
	@echo "redeploy            rebuild sample-service images and restart them in the cluster"
	@echo "smoke-test          place an order through order-service inside the cluster"
	@echo "mcp-kubeconfig      fresh read-only credentials for the MCP server (token TTL $(MCP_TOKEN_TTL))"
	@echo "cluster-down        delete the kind cluster"
	@echo "incident NAME=x     inject an incident: $(INCIDENTS)"
	@echo "incident-reset      back to the healthy base manifests"
	@echo "eval [NAME=a,b]     inject each incident, ask the agent, grade its answer (needs cluster + both servers)"
	@echo "replay [NAME=..] [TIMES=n] [RUN=..]  re-run only the LLM reasoning on evidence saved by an eval (seconds)"
	@echo "audit [DEPLOYMENT=x] [SINCE=hours] [ALL=1]  who changed what and who approved it (MCP audit log)"
	@echo "new-secret          print a random value for an API key"

setup:
	for app in $(PYTHON_APPS); do \
		$(PYTHON) -m venv $$app/.venv && \
		$$app/.venv/$(VENV_BIN)/python -m pip install -q --upgrade pip && \
		$$app/.venv/$(VENV_BIN)/python -m pip install -q -r $$app/requirements-dev.txt || exit 1; \
	done
	test -f ai-server/.env || cp ai-server/.env.example ai-server/.env
	test -f mcp-server/.env || cp mcp-server/.env.example mcp-server/.env

run-mcp-server:
	cd mcp-server && .venv/$(VENV_BIN)/python server.py

run-mcp-servers:
	cd mcp-server && trap 'kill 0' INT TERM EXIT; \
	MCP_TOOLSETS='["kubernetes"]' MCP_SERVER_NAME=oncall-k8s MCP_PORT=$(K8S_MCP_PORT) \
		MCP_PUBLIC_URL=http://127.0.0.1:$(K8S_MCP_PORT)/mcp .venv/$(VENV_BIN)/python server.py & \
	MCP_TOOLSETS='["prometheus"]' MCP_SERVER_NAME=oncall-prometheus MCP_PORT=$(PROMETHEUS_MCP_PORT) \
		MCP_PUBLIC_URL=http://127.0.0.1:$(PROMETHEUS_MCP_PORT)/mcp MCP_AUDIT_LOG_PATH=logs/audit-prometheus.jsonl \
		.venv/$(VENV_BIN)/python server.py & \
	wait

mcp-keys:
	cd ai-server && .venv/$(VENV_BIN)/python -c "from auth.token_keys import main; main()" ../$(KEYS_DIR)

# The agentgateway release binary, checked against its published SHA-256.
$(GATEWAY_BIN):
	mkdir -p gateway/bin
	url=https://github.com/agentgateway/agentgateway/releases/download/$(GATEWAY_VERSION)/$(GATEWAY_ASSET) && \
	curl -sfL $$url -o $@.download && expected=$$(curl -sfL $$url.sha256 | cut -d' ' -f1) && \
	actual=$$(sha256sum $@.download | cut -d' ' -f1) && \
	if [ "$$expected" = "$$actual" ]; then mv $@.download $@ && chmod +x $@; else rm -f $@.download; \
	echo "checksum mismatch for $(GATEWAY_ASSET)"; exit 1; fi

run-gateway: $(GATEWAY_BIN)
	K8S_MCP_URL=http://127.0.0.1:$(K8S_MCP_PORT)/mcp PROMETHEUS_MCP_URL=http://127.0.0.1:$(PROMETHEUS_MCP_PORT)/mcp \
	MCP_JWKS_PATH=$(CURDIR)/$(KEYS_DIR)/jwks.json $(GATEWAY_BIN) -f gateway/agentgateway.yaml

up-kind-gateway: mcp-kubeconfig
	test -f $(KEYS_DIR)/jwks.json || $(MAKE) mcp-keys
	$(COMPOSE_GATEWAY) up -d --build --wait

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

lint:
	ai-server/.venv/$(VENV_BIN)/python -m ruff check .

cluster-up: $(SECRET_ENVS)
	kind get clusters | grep -qx $(CLUSTER) || kind create cluster --name $(CLUSTER) --config kubernetes/kind-cluster.yaml
	kubectl config use-context kind-$(CLUSTER)
	$(MAKE) images
	kubectl apply -k kubernetes/monitoring
	kubectl apply -k $(BASE_DIR)
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
	# The bad-deploy incident's "new version": same code, FAULT_MODE set by the incident patch.
	docker tag payment-service:$(TAG) payment-service:$(BAD_DEPLOY_TAG)
	kind load docker-image payment-service:$(BAD_DEPLOY_TAG) --name $(CLUSTER)

# Same tag, new image: pods only pick it up after a restart.
redeploy: images
	for svc in $(SERVICES); do kubectl rollout restart deployment/$$svc -n $(NAMESPACE) || exit 1; done
	kubectl rollout status deployment -n $(NAMESPACE) -l app.kubernetes.io/part-of=shop --timeout=$(ROLLOUT_TIMEOUT)

# Kubeconfigs for the read-only `mcp-server` ServiceAccount (`config`) and the write
# `mcp-operator` one (`operator-config`): plain for the host, `.internal` for containers
# on kind's Docker network.
mcp-kubeconfig:
	mkdir -p $(MCP_KUBE_DIR)
	ca=$$(kubectl config view --raw --minify --context kind-$(CLUSTER) -o jsonpath='{.clusters[0].cluster.certificate-authority-data}') && \
	server=$$(kubectl config view --minify --context kind-$(CLUSTER) -o jsonpath='{.clusters[0].cluster.server}') && \
	for identity in "mcp-server config" "mcp-operator operator-config"; do \
		set -- $$identity; account=$$1; file=$$2; \
		token=$$(kubectl create token $$account -n $(NAMESPACE) --duration=$(MCP_TOKEN_TTL) --context kind-$(CLUSTER)) || exit 1; \
		for target in "$$file $$server" "$$file.internal $(KIND_API_INTERNAL)"; do \
			set -- $$target; \
			printf '%s\n' "apiVersion: v1" "kind: Config" "current-context: $$account" \
				"clusters: [{name: kind, cluster: {server: '$$2', certificate-authority-data: '$$ca'}}]" \
				"users: [{name: $$account, user: {token: '$$token'}}]" \
				"contexts: [{name: $$account, context: {cluster: kind, user: $$account, namespace: $(NAMESPACE)}}]" \
				> $(MCP_KUBE_DIR)/$$1 || exit 1; \
		done; \
	done
	@echo "wrote $(MCP_KUBE_DIR)/{config,operator-config}{,.internal} (expire in $(MCP_TOKEN_TTL))"

# Secret env files: generated once from their .example with a random value; gitignored.
%.env: %.env.example
	test -f $@ || sed "s/=$$/=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')/" $< > $@

smoke-test:
	kubectl run smoke-test -n $(NAMESPACE) --rm -i --quiet --restart=Never --image=$(SMOKE_IMAGE) -- \
		curl -sS --fail -X POST http://order-service/orders \
		-H "content-type: application/json" -d '{"user_id": 1, "amount": 42.5}'

incident:
	@test -n "$(NAME)" || (echo "usage: make incident NAME=<$(INCIDENTS)>" && exit 1)
	kubectl apply -k kubernetes/incidents/$(NAME)

incident-reset:
	kubectl apply -k $(BASE_DIR)
	kubectl wait deployment --all -n $(NAMESPACE) --for=condition=Available --timeout=$(ROLLOUT_TIMEOUT)

eval:
	cd ai-server && .venv/$(VENV_BIN)/python ../evals/run_eval.py $(if $(NAME),--only $(NAME))

replay:
	cd ai-server && .venv/$(VENV_BIN)/python ../evals/replay.py $(if $(RUN),--run ../$(RUN)) $(if $(NAME),--only $(NAME)) $(if $(TIMES),--times $(TIMES))

audit:
	cd mcp-server && .venv/$(VENV_BIN)/python -m access.audit_report $(if $(DEPLOYMENT),--deployment $(DEPLOYMENT)) $(if $(SINCE),--since-hours $(SINCE)) $(if $(ALL),--all)

new-secret:
	@$(PYTHON) -c "import secrets; print(secrets.token_urlsafe(32))"

cluster-down:
	kind delete cluster --name $(CLUSTER)

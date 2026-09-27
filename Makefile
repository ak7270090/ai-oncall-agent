.PHONY: cluster-up smoke-test cluster-down

cluster-up:
	bash scripts/cluster-up.sh

smoke-test:
	bash scripts/smoke-test.sh

cluster-down:
	bash scripts/cluster-down.sh

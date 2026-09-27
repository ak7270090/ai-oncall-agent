#!/usr/bin/env bash
# Deletes the kind cluster (all pods, loaded images and state).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

require_tools kind
require_docker
kind delete cluster --name "$CLUSTER_NAME"

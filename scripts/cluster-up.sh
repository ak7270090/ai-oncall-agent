#!/usr/bin/env bash
# Creates the kind cluster (if missing), builds and loads the sample-service images,
# and deploys the manifests. Safe to re-run: it redeploys changed code/manifests.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

random_hex() {
    od -An -N16 -tx1 /dev/urandom | tr -d ' \n'
}

ensure_secret_env_file() {
    local secret_file example
    secret_file="$(repo_path "$SECRET_ENV_FILE")"
    example="$(repo_path "$SECRET_ENV_EXAMPLE")"
    [[ -f $secret_file ]] && return
    sed "s/^PAYMENT_API_KEY=.*/PAYMENT_API_KEY=$(random_hex)/" "$example" > "$secret_file"
    log "Created $SECRET_ENV_FILE with a random dev key"
}

ensure_cluster() {
    if kind get clusters 2> /dev/null | grep -qx "$CLUSTER_NAME"; then
        log "Cluster '$CLUSTER_NAME' already exists"
    else
        kind create cluster --name "$CLUSTER_NAME" --config "$(repo_path "$KIND_CONFIG")"
    fi
    kubectl config use-context "kind-$CLUSTER_NAME" > /dev/null
}

# The manifests are the single source of truth for image names and tags.
manifest_images() {
    kubectl kustomize "$(repo_path "$MANIFESTS_DIR")" |
        sed -n 's/^[[:space:]]*image:[[:space:]]*//p' |
        sort -u
}

publish_image() {
    local image="$1"
    local service="${image%%:*}"
    log "Building and loading $image"
    docker build --quiet \
        --file "$(repo_path "$DOCKERFILE")" \
        --build-arg "APP_ENTRYPOINT=$SERVICE_ENTRYPOINT" \
        --build-arg "APP_PORT=$SERVICE_PORT" \
        --tag "$image" \
        "$(repo_path "$SERVICES_DIR/$service")" > /dev/null
    kind load docker-image "$image" --name "$CLUSTER_NAME"
}

require_tools docker kind kubectl
require_docker
ensure_secret_env_file
ensure_cluster

images="$(manifest_images)"
for image in $images; do
    publish_image "$image"
done

kubectl apply -k "$(repo_path "$MANIFESTS_DIR")"
kubectl wait deployment --for=condition=Available \
    --namespace "$NAMESPACE" --selector "$PART_OF_LABEL" --timeout "$ROLLOUT_TIMEOUT"
kubectl get deployments,replicasets,pods,services --namespace "$NAMESPACE"

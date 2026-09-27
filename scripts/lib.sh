# Shared setup for scripts/*.sh. Source it; don't run it.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPTS_DIR/.." && pwd)"

load_config() {
    local key value
    while IFS='=' read -r key value || [[ -n $key ]]; do
        key="${key%$'\r'}"; value="${value%$'\r'}"
        [[ -z $key || $key == \#* ]] && continue
        if [[ -z ${!key:-} ]]; then
            export "$key=$value"
        fi
    done < "$SCRIPTS_DIR/cluster.env"
}

# On Windows, Docker Desktop's bundled kubectl (too old for current kind) can
# shadow the winget-installed one; prefer winget's.
prefer_winget_tools() {
    [[ -n ${LOCALAPPDATA:-} ]] && command -v cygpath > /dev/null || return 0
    local links
    links="$(cygpath -u "$LOCALAPPDATA")/Microsoft/WinGet/Links"
    [[ -d $links ]] && export PATH="$links:$PATH"
    return 0
}

repo_path() {
    echo "$REPO_ROOT/$1"
}

log() {
    echo "==> $*"
}

die() {
    echo "error: $*" >&2
    exit 1
}

require_tools() {
    local tool
    for tool in "$@"; do
        command -v "$tool" > /dev/null || die "'$tool' not found on PATH"
    done
}

require_docker() {
    docker info > /dev/null 2>&1 || die "Docker is not running. Start Docker first."
}

load_config
prefer_winget_tools

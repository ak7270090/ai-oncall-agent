from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from constants import Toolset


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_", env_file=".env", extra="ignore")

    server_name: str = "oncall-mcp-server"
    server_version: str = "0.7.0"
    transport: Literal["streamable-http", "stdio"] = "streamable-http"
    host: str = "127.0.0.1"
    port: int = 9000
    path: str = "/mcp"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # Host headers accepted when bound to a non-localhost address (DNS rebinding
    # protection). Empty = SDK default: protection on for localhost binds only.
    allowed_hosts: list[str] = []

    # Which tools this process serves (Phase 22): kubernetes (pods, deployments, events,
    # resources, write tools) and/or prometheus (metrics). Run one process per tool set to
    # get two MCP servers, each with only its own credentials. Default: both.
    toolsets: list[Toolset] = [Toolset.KUBERNETES, Toolset.PROMETHEUS]

    backend: Literal["kubernetes", "fake"] = "kubernetes"
    # Credentials of the read-only `mcp-server` ServiceAccount (`make mcp-kubeconfig`),
    # not the cluster-admin kubeconfig.
    kubeconfig_path: str = ".kube/config"
    kube_request_timeout_seconds: float = 10
    # Write tools (restart / scale / roll back a Deployment), each asking a human for
    # approval (MCP elicitation). Off by default; they use the separate `mcp-operator`
    # ServiceAccount (`make mcp-kubeconfig` writes its kubeconfig).
    enable_write_tools: bool = False
    operator_kubeconfig_path: str = ".kube/operator-config"
    max_replicas: int = 5
    allowed_namespaces: list[str] = ["shop"]
    default_namespace: str = "shop"

    prometheus_url: str = "http://127.0.0.1:9090"
    prometheus_timeout_seconds: float = 10
    metrics_rate_window: str = "30s"
    metrics_step_seconds: int = 60

    # get_pod_logs(summarize=true): summarize only logs at least this long; limit the
    # summary's length; reuse fetched lines this long (the sampling retry must see the same).
    log_summary_min_lines: int = 40
    log_summary_max_tokens: int = 500
    log_cache_seconds: float = 30

    # Authentication (Phase 19): bearer tokens are JWTs the AI server signs (RS256) for its
    # signed-in user; checked with the public keys in this JWKS file (`make mcp-keys`).
    # Empty = no authentication (local dev only: anyone who reaches the port may call
    # every tool).
    auth_jwks_path: Path | None = None

    @field_validator("auth_jwks_path", mode="before")
    @classmethod
    def treat_empty_as_unset(cls, value):
        return value or None
    # Must match the tokens' `iss` and `aud` claims. The issuer is published as this
    # server's authorization server (OAuth protected resource metadata).
    auth_issuer_url: str = "http://127.0.0.1:8000"
    auth_audience: str = "oncall-mcp-server"
    # This server's public MCP URL, published in the protected resource metadata.
    public_url: str = "http://127.0.0.1:9000/mcp"

    # Authorization (Phase 20): each user's role, and the write tools each role may call
    # and approve. Every known role may call the read-only tools; unknown users nothing.
    user_roles: dict[str, str] = {}
    role_write_tools: dict[str, list[str]] = {
        "developer": [],
        "oncall": ["restart_deployment", "scale_deployment"],
        "lead": ["restart_deployment", "scale_deployment", "rollback_deployment"],
    }
    # Append-only audit log of tool calls and approvals (JSON lines).
    audit_log_path: Path = Path("logs/audit.jsonl")
    # Shown next to trace ids by `make audit`, e.g.
    # https://cloud.langfuse.com/project/<project-id>/traces/{trace_id}
    trace_url_template: str | None = None

    # Team knowledge published as MCP resources: runbooks/<service>.md and
    # topology/<namespace>.json (default: mcp-server/knowledge).
    knowledge_dir: Path = Path(__file__).resolve().parents[1] / "knowledge"
    # Most values returned for one completion request.
    max_completion_values: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()

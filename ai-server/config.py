from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_title: str = "AI On-Call Server"
    server_host: str = "127.0.0.1"
    server_port: int = 8000

    mcp_server_url: str = "http://127.0.0.1:9000/mcp"
    mcp_timeout_seconds: float = 30
    # Several MCP servers (Phase 22): name -> URL, e.g. {"k8s": "http://127.0.0.1:9000/mcp",
    # "prometheus": "http://127.0.0.1:9001/mcp"}, or one gateway. Empty = mcp_server_url only.
    mcp_servers: dict[str, str] = {}
    # Names of the gateway's targets when MCP_SERVERS is a gateway (e.g. ["k8s",
    # "prometheus"]): it renames tools and resource URIs after them (k8s_list_pods,
    # k8s+runbook://…); the AI server maps them back to the servers' own names.
    mcp_gateway_targets: list[str] = []

    # Sign-in (Phase 19): API key (X-API-Key header) -> user name. Empty = no sign-in
    # (local dev only): everyone is "anonymous".
    api_keys: dict[str, str] = {}
    # MCP bearer tokens, signed for the signed-in user with this private key (RS256, from
    # `make mcp-keys`); the MCP servers and the gateway verify them with the public JWKS.
    # Empty = no token sent. Issuer and audience must match theirs.
    mcp_token_private_key_path: Path | None = None

    @field_validator("mcp_token_private_key_path", mode="before")
    @classmethod
    def treat_empty_as_unset(cls, value):
        return value or None
    mcp_token_issuer: str = "http://127.0.0.1:8000"
    mcp_token_audience: str = "oncall-mcp-server"
    mcp_token_ttl_seconds: float = 60

    llm_model: str = "openai:gpt-5.4-mini"
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 120
    llm_max_retries: int = 2
    # Optional cheaper, faster model ("<provider>:<model>") for simple tasks: MCP sampling
    # requests that prefer cost/speed (log summaries) and the graph steps listed in
    # fast_model_steps. Empty = LLM_MODEL does everything. The key defaults to LLM_API_KEY.
    llm_model_fast: str | None = None
    llm_fast_api_key: SecretStr | None = None
    fast_model_steps: list[str] = []

    max_question_length: int = 2000

    # Investigation graph
    default_namespace: str = "shop"
    error_rate_threshold: float = 0.05
    latency_threshold_ms: float = 1000
    # A service counts as CPU-starved (stated to the LLM as a computed finding) when this
    # share of its CPU periods is throttled at the container limit AND it really uses
    # CPU: at least cpu_min_usage_of_limit of its limit (idle containers look throttled too).
    cpu_throttled_ratio_threshold: float = 0.25
    cpu_min_usage_of_limit: float = 0.15
    max_pods_to_inspect: int = 3
    max_services_to_inspect: int = 3
    log_lines: int = 50
    max_follow_up_rounds: int = 2
    # Read the team's knowledge from MCP resources: the service map and the runbooks of
    # flagged services become evidence.
    use_service_knowledge: bool = True
    # Ask the MCP server to summarize long logs with the client's LLM (MCP sampling).
    summarize_logs: bool = False
    max_samplings_per_investigation: int = 6

    # How long an action (POST /actions) waits for a human's approval before giving up.
    approval_timeout_seconds: float = 600

    # Tracing in Langfuse; off while the keys are empty.
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_environment: str = "local"

    @property
    def mcp_server_urls(self) -> dict[str, str]:
        return self.mcp_servers or {"mcp": self.mcp_server_url}


@lru_cache
def get_settings() -> Settings:
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]

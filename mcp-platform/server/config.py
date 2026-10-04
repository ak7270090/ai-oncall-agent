"""Settings both MCP servers share. Each domain adds its own (k8s/config.py,
prometheus/config.py, auth/config.py, audit/config.py); every class reads MCP_* variables
from the environment or .env, so the variable names don't depend on where a setting lives."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_", env_file=".env", extra="ignore", env_nested_delimiter="__")


class ServerIdentity(BaseModel):
    """What differs between the two MCP servers. Override one field with e.g.
    MCP_K8S_SERVER__PORT=9100."""

    name: str
    port: int
    # Public MCP URL, published in the OAuth protected resource metadata.
    public_url: str
    # Append-only audit log of this server's tool calls and approvals (JSON lines).
    audit_log_path: Path


class ServerSettings(McpSettings):
    server_version: str = "0.8.0"
    transport: Literal["streamable-http", "stdio"] = "streamable-http"
    host: str = "127.0.0.1"
    path: str = "/mcp"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # Host headers accepted when bound to a non-localhost address (DNS rebinding
    # protection). Empty = SDK default: protection on for localhost binds only.
    allowed_hosts: list[str] = []
    # kubernetes = the real cluster and Prometheus; fake = the canned incident (tests, demos).
    backend: Literal["kubernetes", "fake"] = "kubernetes"
    allowed_namespaces: list[str] = ["shop"]
    default_namespace: str = "shop"

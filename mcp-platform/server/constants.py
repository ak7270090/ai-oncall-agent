"""Fixed values both MCP servers use. Each domain keeps its own in <domain>/constants.py;
anything an operator may tune per environment is in config.py."""

# Kubernetes object/label value syntax; also keeps values safe to embed in PromQL.
NAME_PATTERN = r"^[a-z0-9]([a-z0-9.-]{0,61}[a-z0-9])?$"

HEALTH_STATUS_OK = "ok"

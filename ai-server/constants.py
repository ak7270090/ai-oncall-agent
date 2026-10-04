"""App-wide fixed values (tracing, health). Each domain keeps its own in
<domain>/constants.py; anything an operator may tune per environment is in config.py."""

# Names of the Langfuse traces recorded for an investigation and for an action.
INVESTIGATION_TRACE_NAME = "investigate"
ACTION_TRACE_NAME = "action"
# OpenTelemetry tracer name the mcp SDK uses for its own spans (not exported).
MCP_SDK_TRACER_NAME = "mcp-python-sdk"
# W3C Trace Context header (https://www.w3.org/TR/trace-context/): version-traceid-spanid-flags.
TRACEPARENT_PATTERN = r"00-(?P<trace_id>[0-9a-f]{32})-(?P<span_id>[0-9a-f]{16})-[0-9a-f]{2}"

# API status values.
HEALTH_STATUS_OK = "ok"
READY_STATUS = "ready"

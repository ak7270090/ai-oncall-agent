from config import McpSettings


class AuditSettings(McpSettings):
    # Shown next to trace ids by `make audit`, e.g.
    # https://cloud.langfuse.com/project/<project-id>/traces/{trace_id}
    trace_url_template: str | None = None

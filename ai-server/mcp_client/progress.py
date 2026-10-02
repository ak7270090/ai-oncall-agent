from collections.abc import Awaitable, Callable

from mcp.shared.dispatcher import ProgressFnT

# Receives MCP progress notifications of any tool: (tool name, progress, total, message).
ToolProgressCallback = Callable[[str, float, float | None, str | None], Awaitable[None]]


def progress_callback_for(tool: str, on_progress: ToolProgressCallback | None) -> ProgressFnT | None:
    """The per-call progress callback the MCP client expects, tagged with the tool name.
    None means the call carries no progress token, so the server sends no progress."""
    if on_progress is None:
        return None

    async def report(progress: float, total: float | None, message: str | None) -> None:
        await on_progress(tool, progress, total, message)

    return report

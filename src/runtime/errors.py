from src.runtime._markers import deadcode_ignore


@deadcode_ignore(reason="Defined as part of error taxonomy, used via type field")
class ToolExecutionError(Exception):
    """Raised when a tool execution fails."""
    pass
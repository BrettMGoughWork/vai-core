"""Panic guard decorator for unexpected error handling."""

from functools import wraps

from src.execution.safe_failure import make_safe_failure
from src.core.types.errors.AgentError import AgentError


def with_panic_guard(fn):
    """Decorator that guards against unexpected exceptions.
    
    Catches any Exception that is not an AgentError, converts it to a
    SafeFailure with panic metadata, and returns it. AgentErrors are
    re-raised unchanged.
    
    Args:
        fn: The function to guard.
    
    Returns:
        A wrapped function that handles unexpected exceptions.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AgentError:
            raise
        except Exception as e:
            return make_safe_failure(e, {"panic": True})

    return wrapper

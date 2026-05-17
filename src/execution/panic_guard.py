"""Panic guard decorator for unexpected error handling."""

from functools import wraps

from src.execution.safe_failure import make_safe_failure


def with_panic_guard(fn):
    """Decorator that guards against unexpected exceptions.
    
    Catches any Exception, converts it to a SafeFailure with panic metadata,
    and returns it instead of raising. Allows normal return values to pass through.
    
    Args:
        fn: The function to guard.
    
    Returns:
        A wrapped function that handles unexpected exceptions.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            return make_safe_failure(e, {"panic": True})

    return wrapper

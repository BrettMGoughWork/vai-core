"""Panic guard decorator for unexpected error handling."""

from functools import wraps

from src.runtime.safe_failure import make_safe_failure
from src.strategy.state.step_outcome import StepOutcome

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
            state = args[0] # ConversationState is expected to be the first argument
            failure = make_safe_failure(e, {"panic": True})
            return failure, state, StepOutcome.FATAL

    return wrapper

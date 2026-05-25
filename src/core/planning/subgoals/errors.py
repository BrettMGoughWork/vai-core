# /src/core/planning/subgoals/errors.py

class SubgoalError(Exception):
    """Base class for all subgoal-related errors."""
    pass


class SubgoalNotFoundError(SubgoalError):
    """Raised when a subgoal lookup fails."""
    def __init__(self, subgoal_id: str):
        super().__init__(f"Subgoal not found: {subgoal_id}")
        self.subgoal_id = subgoal_id


class InvalidSubgoalError(SubgoalError):
    """Raised when a subgoal fails structural or validator checks."""
    pass


class IllegalSubgoalTransitionError(SubgoalError):
    """Raised when a lifecycle transition violates the transition table."""
    pass


class SubgoalHierarchyError(SubgoalError):
    """Raised when parent/child invariants are violated."""
    pass
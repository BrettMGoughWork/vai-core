"""
Depth guard — caps deferral chain length to prevent runaway chains.

Even with an acyclic graph, a chain like A→B→C→D→E can produce
excessive context bloat.  The depth guard tracks the current depth
in the deferral chain and rejects deferrals that would exceed the
configured maximum.

The depth counter is stored in the agent's ``supervisor_metadata``
and passed through each deferral.
"""

from __future__ import annotations


class DeferralDepthError(Exception):
    """Raised when a deferral would exceed the maximum chain depth."""


class DepthGuard:
    """Configurable max-deferral-depth guard."""

    DEFAULT_MAX_DEPTH = 3

    def __init__(self, max_depth: int = DEFAULT_MAX_DEPTH) -> None:
        if max_depth < 1:
            raise ValueError(f"max_depth must be >= 1, got {max_depth}")
        self._max_depth = max_depth

    @property
    def max_depth(self) -> int:
        return self._max_depth

    def check(self, current_depth: int) -> None:
        """Check that *current_depth* does not exceed the limit.

        Parameters
        ----------
        current_depth:
            The depth of the current deferral chain (0-indexed: 0 = no
            prior defers, 1 = one prior defer, etc.).

        Raises
        ------
        DeferralDepthError:
            If *current_depth* >= *max_depth*.
        """
        if current_depth >= self._max_depth:
            raise DeferralDepthError(
                f"Deferral depth limit reached "
                f"(depth={current_depth}, max={self._max_depth}).  "
                f"Cannot defer further."
            )

    def get_next_depth(self, current_depth: int) -> int:
        """Return the depth for the next deferral and validate it.

        Returns the incremented depth if valid, otherwise raises
        ``DeferralDepthError``.
        """
        next_depth = current_depth + 1
        self.check(next_depth)
        return next_depth

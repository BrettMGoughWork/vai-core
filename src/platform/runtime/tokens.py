"""Resume token generation — Stratum-4 runtime.

A resume token uniquely identifies the next execution cycle for a job.
Tokens are opaque to S2/S3 — S4 carries them as an opaque envelope.
"""

from __future__ import annotations

import uuid


def new_resume_token() -> str:
    """Generate a new unique resume token.

    Returns:
        A UUID v4 string.
    """
    return str(uuid.uuid4())

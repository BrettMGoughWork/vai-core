class SegmentError(Exception):
    """Base class for all segment-related errors."""
    pass


class SegmentNotFoundError(SegmentError):
    """Raised when a segment lookup fails."""
    def __init__(self, segment_id: str):
        super().__init__(f"Segment not found: {segment_id}")
        self.segment_id = segment_id


class SegmentValidationError(SegmentError):
    """Raised when a segment fails structural or validator checks."""
    pass


class SegmentStitchingError(SegmentError):
    """Raised when segments cannot be stitched into a valid chain."""
    pass

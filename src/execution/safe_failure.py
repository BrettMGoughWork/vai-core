from dataclasses import dataclass


@dataclass
class SafeFailure:
    error_type: str
    message: str

    @staticmethod
    def from_exception(exc: Exception) -> "SafeFailure":
        return SafeFailure(
            error_type=exc.__class__.__name__,
            message=str(exc),
        )

    @property
    def is_error(self) -> bool:
        return True
"""Retry policy for batched ZOOMA requests.

The defaults preserve the Galaxy zooma tool's behaviour exactly: each batch
is attempted twice with no backoff, a batch that fails twice is skipped,
and two consecutive skipped batches abort the run with
:class:`zooma_client.errors.ServiceUnavailableError`.
"""

import dataclasses


def is_retryable_status(status_code: int) -> bool:
    """Whether an HTTP status is worth retrying.

    429 and 5xx are transient; every other 4xx is a permanent failure.
    Retrying a 400 only hammers the server and delays the inevitable skip.
    """
    return status_code == 429 or status_code >= 500


@dataclasses.dataclass(frozen=True)
class RetryPolicy:
    """How the client retries failed batches.

    Attributes:
        max_attempts: attempts per batch before it is skipped or raised.
        max_consecutive_failures: number of skipped batches in a row that
            abort the whole run (the service is then considered down).
        backoff: seconds to sleep before the first retry. ``0.0`` (the
            default) never sleeps.
        backoff_factor: multiplier applied to the backoff after each
            retry, giving exponential backoff.
    """

    max_attempts: int = 2
    max_consecutive_failures: int = 2
    backoff: float = 0.0
    backoff_factor: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be at least 1")
        if self.backoff < 0.0:
            raise ValueError("backoff must be non-negative")
        if self.backoff_factor < 1.0:
            raise ValueError("backoff_factor must be at least 1")

    def delay_before(self, attempt: int) -> float:
        """Seconds to sleep before the given retry attempt (2-based).

        ``backoff=0`` never sleeps; ``backoff=1.0`` with the default
        factor sleeps 1s before the second attempt, 2s before the third,
        4s before the fourth, and so on.
        """
        return self.backoff * self.backoff_factor ** max(0, attempt - 2)

    def retry_description(self, remaining: int) -> str:
        """Human-readable tail for a "failed, retrying ..." warning."""
        if remaining == 1:
            return "once"
        return f"({remaining} more times)"

    def attempts_description(self) -> str:
        """Human-readable attempt count for a final-failure warning."""
        if self.max_attempts == 1:
            return "once"
        if self.max_attempts == 2:
            return "twice"
        return f"{self.max_attempts} times"

"""Exception hierarchy for zooma-client.

Everything the client raises derives from :class:`ZoomaError`, so
``except ZoomaError`` catches the full range. :class:`InvalidRequestError`
and :class:`UnexpectedResponseError` additionally derive from
``ValueError``, so consumers with pre-existing
``except (SomeServiceError, ValueError)`` handlers keep working.
"""


class ZoomaError(RuntimeError):
    """Base class for every error raised by zooma-client."""


class ServiceUnavailableError(ZoomaError):
    """The health check failed, or too many batches failed in a row."""


class RequestError(ZoomaError):
    """A transport-level failure (connection error, timeout) or a
    retryable HTTP status (429, 5xx).

    The original exception, when there is one, is available as
    ``__cause__``.
    """


class InvalidRequestError(ZoomaError, ValueError):
    """The request was invalid: a client-side validation failure or a
    non-retryable 4xx response.

    Retrying cannot help — the value or the request itself must change.
    """


class UnexpectedResponseError(ZoomaError, ValueError):
    """The response violated the API contract: wrong content type (for
    example the web app's HTML, which the service returns with HTTP 200
    for any unknown path), malformed payload, or a mismatch between the
    submitted values and the returned mappings.
    """


class FilterViolation(UnexpectedResponseError):
    """The response contained candidate ontologies outside the requested
    ``target_ontologies``.

    The API's ``targetOntologies`` parameter is additive unless combined
    with ``includeOtherOntologies: false``, so this indicates the filter
    was not applied and the results are silently wrong.
    """

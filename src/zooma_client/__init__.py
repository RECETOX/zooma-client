"""zooma-client: a Python client for the EBI ZOOMA ontology mapping service.

ZOOMA (https://www.ebi.ac.uk/spot/zooma) maps free-text property values to
ontology terms. This package wraps both generations of its API behind one
synchronous, dependency-light client:

* v3 ``map`` — :func:`Client.map_all`, batched, returning
  :class:`Mapping` objects with ontology candidates;
* v2 ``annotate`` — :func:`Client.annotate` / :func:`Client.annotate_all`,
  one request per value, returning curated :class:`Annotation` objects;
* v3 metadata — :func:`Client.presets`, :func:`Client.sources`,
  :func:`Client.list_models`;
* the (v3-only) health endpoint — :func:`Client.health`.

The client encodes the service's traps (fail-open ``targetOntologies``,
HTML-behind-200, positional result matching, server request limits) so no
consumer has to know about them.
"""

from zooma_client.client import Client
from zooma_client.errors import (
    FilterViolation,
    InvalidRequestError,
    RequestError,
    ServiceUnavailableError,
    UnexpectedResponseError,
    ZoomaError,
)
from zooma_client.models import (
    AnnotatedProperty,
    Annotation,
    AnnotationProvenance,
    Candidate,
    Mapping,
    Model,
    Preset,
    Provenance,
    Source,
)
from zooma_client.retry import RetryPolicy, is_retryable_status
from zooma_client.util import preview_values

__version__ = "0.1.0"

__all__ = [
    "AnnotatedProperty",
    "Annotation",
    "AnnotationProvenance",
    "Candidate",
    "Client",
    "FilterViolation",
    "InvalidRequestError",
    "Mapping",
    "Model",
    "Preset",
    "Provenance",
    "RequestError",
    "RetryPolicy",
    "ServiceUnavailableError",
    "Source",
    "UnexpectedResponseError",
    "ZoomaError",
    "is_retryable_status",
    "preview_values",
]

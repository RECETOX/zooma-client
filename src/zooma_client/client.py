"""Synchronous client for the EBI ZOOMA service.

The client wraps both generations of the API behind one class:

* v3 ``POST /v3/api/services/map`` — :meth:`Client.map_all` maps many
  values to ontology term candidates in batched requests;
* v2 ``GET /v2/api/services/annotate`` — :meth:`Client.annotate` and
  :meth:`Client.annotate_all` return curated annotations, one value per
  request (the endpoint accepts a single ``propertyValue`` and silently
  ignores every other query parameter, so there is no request batching at
  this level);

plus the v3 metadata endpoints (:meth:`Client.presets`,
:meth:`Client.sources`, :meth:`Client.list_models`) and the only real
health endpoint (:meth:`Client.health` — v3, used for both modes, because
there is no usable v2 health route).

The implementation encodes several API traps so consumers cannot hit them:

* any unknown path under the ZOOMA base URL answers **HTTP 200 with the
  web app's HTML**, so every response is validated by content type and
  payload shape before parsing (:class:`UnexpectedResponseError`
  otherwise) — a 200 is never trusted on its own;
* v3 results are matched to inputs **by position**: the mapping count and
  the echoed ``textToMap`` are checked on every response, because
  matching by value would merge duplicate inputs;
* ``targetOntologies`` is **additive, not restrictive** — it only filters
  when combined with ``includeOtherOntologies: false``, which
  :meth:`Client.map_all` sends by default whenever ``target_ontologies``
  is non-empty; the returned candidates are then verified to stay inside
  the requested set, raising :class:`FilterViolation` if the server fails
  to apply the filter;
* the server-side request limits (1000 properties per request, 200 in
  deep mode, 1000 characters per value, 2 MiB per request) are enforced
  client-side, before any network call.

The client never writes to stdout/stderr itself: progress and skip
warnings go to the injected ``sink`` callable (discarded by default), so
consumers stay in full control of their logging.
"""

import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Literal, TypeVar

import requests

from zooma_client import batching, models
from zooma_client.batching import chunked
from zooma_client.endpoints import (
    ANNOTATE_PATH,
    DEFAULT_BASE_URL,
    HEALTH_PATH,
    MAP_PATH,
    MODELS_PATH,
    ONTOLOGY_PRESETS_PATH,
    SOURCES_PATH,
)
from zooma_client.errors import (
    FilterViolation,
    InvalidRequestError,
    RequestError,
    ServiceUnavailableError,
    UnexpectedResponseError,
    ZoomaError,
)
from zooma_client.retry import RetryPolicy, is_retryable_status
from zooma_client.util import preview_values

OnError = Literal["skip", "raise"]

T = TypeVar("T")

_SKIPPED = object()


def _discard(message: str) -> None:
    """Default sink: throw progress messages away."""


def _check_on_error(on_error: OnError) -> None:
    if on_error not in ("skip", "raise"):
        raise InvalidRequestError(f"on_error must be 'skip' or 'raise', got {on_error!r}")


class Client:
    """A reusable, thread-unsafe client for one ZOOMA deployment.

    Args:
        base_url: ZOOMA service root, without a trailing slash.
        timeout: per-request timeout in seconds.
        session: a ``requests.Session`` to use instead of an internal one
            (also the test seam).
        retry: retry/skip/abort policy for batched operations.
        sink: callable receiving progress and warning messages; the
            client never writes to a stream itself. Pass ``print`` or a
            logger method to see them.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        session: requests.Session | None = None,
        retry: RetryPolicy | None = None,
        sink: Callable[[str], None] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = session if session is not None else requests.Session()
        self._owns_session = session is None
        self._retry = retry if retry is not None else RetryPolicy()
        self._sink = sink if sink is not None else _discard

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying session, if this client created it."""
        if self._owns_session:
            self._session.close()

    # --- transport ---------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = self._url(path)
        try:
            response = self._session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={"Accept": "application/json"},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise RequestError(f"ZOOMA request to '{url}' failed: {exc}") from exc
        if response.status_code >= 400:
            message = f"ZOOMA returned HTTP {response.status_code} for '{url}'"
            body = response.text.strip()
            if body:
                message += f". Response: {body}"
            if is_retryable_status(response.status_code):
                raise RequestError(message)
            raise InvalidRequestError(message)
        content_type = response.headers.get("Content-Type", "")
        if "json" not in content_type.lower():
            raise UnexpectedResponseError(
                f"ZOOMA returned Content-Type '{content_type}' instead of JSON for "
                f"'{url}'. Any unknown path under the ZOOMA base URL answers 200 "
                "with the web app's HTML, so this usually means a wrong base_url."
            )
        try:
            return response.json()
        except ValueError as exc:
            raise UnexpectedResponseError(
                f"ZOOMA returned malformed JSON for '{url}': {exc}"
            ) from exc

    # --- health ------------------------------------------------------------

    def health(self) -> bool:
        """Return ``True`` if ZOOMA reports healthy, raise otherwise.

        Always checks the v3 health endpoint — there is no usable v2
        health route (unknown paths under ``/spot/zooma/`` return 200 with
        the web app's HTML, which would report healthy no matter what).
        """
        url = self._url(HEALTH_PATH)
        try:
            response = self._session.get(url, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ServiceUnavailableError(
                f"ZOOMA health check failed for '{url}'. "
                f"The service appears unavailable: {exc}"
            ) from exc
        if response.status_code >= 400:
            body = response.text.strip()
            details = f" Response: {body}" if body else ""
            raise ServiceUnavailableError(
                f"ZOOMA health check returned HTTP {response.status_code} "
                f"for '{url}'.{details}"
            )
        content_type = response.headers.get("Content-Type", "")
        if "html" in content_type.lower():
            raise UnexpectedResponseError(
                f"ZOOMA health check for '{url}' returned HTML (Content-Type "
                f"'{content_type}') — that is the web app, not the API, so the "
                "health result cannot be trusted."
            )
        return True

    # --- v3 map ------------------------------------------------------------

    def map_all(
        self,
        values: Sequence[str],
        *,
        batch_size: int = 10,
        property_type: str | None = None,
        target_ontologies: Sequence[str] = (),
        include_other_ontologies: bool | None = None,
        exclude_term_ids: Sequence[str] = (),
        defining_only: bool = False,
        return_all: bool = False,
        deep: bool = False,
        model: str | None = None,
        on_error: OnError = "skip",
    ) -> Iterator[models.Mapping]:
        """Map values to ontology term candidates via the v3 map endpoint.

        Values are sent in batches of ``batch_size`` (validated against
        the server's per-request limit, which is 200 in deep mode) and one
        :class:`~zooma_client.models.Mapping` is yielded per submitted
        value, in submission order — duplicate inputs stay separate, and
        a value whose batch was skipped is simply absent from the output.

        Args:
            values: the texts to map.
            batch_size: values per request (the request batching unit).
            property_type: optional ``propertyType`` sent with every value.
            target_ontologies: ontology names (e.g. ``["efo", "mondo"]``)
                the results are restricted to. The API's
                ``targetOntologies`` parameter is additive unless combined
                with ``includeOtherOntologies: false``; this method sends
                that combination whenever ``target_ontologies`` is
                non-empty and then verifies the filter was applied
                (:class:`~zooma_client.errors.FilterViolation` if not),
                so the filter cannot silently fail open.
            include_other_ontologies: ``None`` (the default) means
                ``False`` whenever ``target_ontologies`` is non-empty and
                "not sent" otherwise; pass ``True`` to explicitly opt into
                the API's fail-open behaviour.
            exclude_term_ids: term IDs dropped from the candidates.
            defining_only: only return defining (non-derived) terms.
            return_all: ask the server to return all known mappings.
            deep: enable deep lookup; lowers the per-request property
                limit from 1000 to 200.
            model: embedding model name, from
                :meth:`~zooma_client.Client.list_models`.
            on_error: ``"skip"`` (default) drops values whose batch fails
                even after retries, reporting them via the ``sink``;
                ``"raise"`` propagates the first failure. A response that
                violates the ontology filter always raises
                :class:`~zooma_client.errors.FilterViolation`, regardless
                of ``on_error`` — skipped violations would be silently
                wrong data. A per-value ``error`` mapping is dropped
                silently with ``"skip"`` and raised with ``"raise"``.

        Yields:
            one :class:`~zooma_client.models.Mapping` per successfully
            processed input value, in submission order.
        """
        _check_on_error(on_error)
        if isinstance(values, str):
            values = [values]
        values = list(values)
        batching.validate_batch_size(batch_size, deep)
        targets = tuple(target_ontologies)
        if include_other_ontologies is None:
            # §"targetOntologies fails open": the parameter is additive
            # unless combined with includeOtherOntologies=false.
            include_other_ontologies = False if targets else None
        return self._map_all(
            values,
            batch_size,
            property_type,
            targets,
            include_other_ontologies,
            tuple(exclude_term_ids),
            defining_only,
            return_all,
            deep,
            model,
            on_error,
        )

    def _map_all(
        self,
        values: list[str],
        batch_size: int,
        property_type: str | None,
        targets: tuple[str, ...],
        include_other_ontologies: bool | None,
        exclude_term_ids: tuple[str, ...],
        defining_only: bool,
        return_all: bool,
        deep: bool,
        model: str | None,
        on_error: OnError,
    ) -> Iterator[models.Mapping]:
        def operation(batch: list[str]) -> list[models.Mapping]:
            return self._map_batch(
                batch,
                property_type=property_type,
                targets=targets,
                include_other_ontologies=include_other_ontologies,
                exclude_term_ids=exclude_term_ids,
                defining_only=defining_only,
                return_all=return_all,
                deep=deep,
                model=model,
            )

        for result in self._process_batches(chunked(values, batch_size), operation, on_error):
            for mapping in result:
                if mapping.ok:
                    yield mapping
                elif on_error == "raise":
                    raise UnexpectedResponseError(
                        f"ZOOMA reported an error for value "
                        f"{mapping.text_to_map!r}: {mapping.error}"
                    )
                # else: per-value error, dropped silently ("skip" keeps
                # the tool's current behaviour of emitting no rows).

    def _map_batch(
        self,
        batch: list[str],
        *,
        property_type: str | None,
        targets: tuple[str, ...],
        include_other_ontologies: bool | None,
        exclude_term_ids: tuple[str, ...],
        defining_only: bool,
        return_all: bool,
        deep: bool,
        model: str | None,
    ) -> list[models.Mapping]:
        for value in batch:
            batching.validate_property_value(value)

        properties: list[dict[str, str]] = []
        for value in batch:
            entry: dict[str, str] = {"textToMap": value}
            if property_type is not None:
                entry["propertyType"] = property_type
            properties.append(entry)

        body: dict[str, Any] = {"properties": properties}
        if targets:
            body["targetOntologies"] = list(targets)
        if include_other_ontologies is not None:
            body["includeOtherOntologies"] = include_other_ontologies
        if exclude_term_ids:
            body["excludeTermIds"] = list(exclude_term_ids)
        if defining_only:
            body["definingOnly"] = True
        if return_all:
            body["returnAll"] = True
        if deep:
            body["deep"] = True
        if model is not None:
            body["model"] = model
        batching.validate_request_size(body)

        payload = self._request_json("POST", MAP_PATH, json_body=body)
        if not isinstance(payload, dict) or not isinstance(payload.get("mappings"), list):
            raise UnexpectedResponseError(
                f"ZOOMA map returned an unexpected payload for '{self._url(MAP_PATH)}': "
                "expected an object with a 'mappings' array"
            )
        raw_mappings = payload["mappings"]
        if len(raw_mappings) != len(batch):
            raise UnexpectedResponseError(
                f"ZOOMA map returned {len(raw_mappings)} mappings "
                f"for {len(batch)} submitted values"
            )

        mappings: list[models.Mapping] = []
        for value, raw in zip(batch, raw_mappings, strict=True):
            if not isinstance(raw, dict):
                raise UnexpectedResponseError(
                    f"ZOOMA map returned a non-object mapping entry for {value!r}"
                )
            echoed = raw.get("textToMap")
            if echoed is not None and echoed != value:
                raise UnexpectedResponseError(
                    f"ZOOMA map returned a mapping for {echoed!r} "
                    f"where {value!r} was submitted"
                )
            mappings.append(models.Mapping.from_dict(raw))

        if targets and not include_other_ontologies:
            self._check_ontology_filter(mappings, targets)
        return mappings

    def _check_ontology_filter(
        self, mappings: list[models.Mapping], targets: tuple[str, ...]
    ) -> None:
        requested = {target.lower() for target in targets}
        violations = sorted(
            {
                candidate.ontology.lower()
                for mapping in mappings
                for candidate in mapping.candidates
                if candidate.ontology and candidate.ontology.lower() not in requested
            }
        )
        if violations:
            raise FilterViolation(
                f"ZOOMA returned candidates from ontologies outside the requested "
                f"set {sorted(targets)}: {violations}. The API's targetOntologies "
                "parameter is additive unless combined with includeOtherOntologies="
                "false, so the filter was not applied."
            )

    # --- v2 annotate -------------------------------------------------------

    def annotate(self, value: str) -> list[models.Annotation]:
        """Annotate a single value via the legacy v2 annotate endpoint.

        The endpoint accepts exactly one ``propertyValue`` per call and
        silently ignores every other query parameter, so there is no way
        to batch several values into one request — use
        :meth:`annotate_all` for that; its ``batch_size`` only groups
        values for retry/skip purposes and does not reduce the number of
        requests.

        No retry policy is applied here; failures raise directly.
        """
        payload = self._request_json("GET", ANNOTATE_PATH, params={"propertyValue": value})
        if isinstance(payload, dict):
            items: list[Any] = [payload]
        elif isinstance(payload, list):
            items = payload
        else:
            raise UnexpectedResponseError(
                f"ZOOMA annotate returned an unexpected payload type for "
                f"value {value!r}: {type(payload).__name__}"
            )
        annotations = []
        for item in items:
            if not isinstance(item, dict):
                raise UnexpectedResponseError(
                    f"ZOOMA annotate returned a non-object annotation for value {value!r}"
                )
            annotations.append(models.Annotation.from_dict(item))
        return annotations

    def annotate_all(
        self,
        values: Sequence[str],
        *,
        batch_size: int = 10,
        on_error: OnError = "skip",
    ) -> Iterator[models.Annotation]:
        """Annotate values via the legacy v2 endpoint, one request per value.

        The v2 endpoint accepts a single ``propertyValue`` per call, so
        ``batch_size`` does not reduce the number of requests — it only
        groups values that are retried and skipped together. Values are
        cached, so a retried batch re-queries only what is still missing
        and duplicate values are queried exactly once.

        Yields one :class:`~zooma_client.models.Annotation` per
        (value, annotation) pair, in submission order; a value with no
        results, or whose batch was skipped, yields nothing.
        """
        _check_on_error(on_error)
        if isinstance(values, str):
            values = [values]
        values = list(values)
        cache: dict[str, list[models.Annotation]] = {}

        def operation(batch: list[str]) -> list[list[models.Annotation]]:
            for value in batch:
                if value not in cache:
                    cache[value] = self.annotate(value)
            return [cache[value] for value in batch]

        for batch_result in self._process_batches(
            chunked(values, batch_size), operation, on_error
        ):
            for annotations in batch_result:
                yield from annotations

    # --- v3 metadata -------------------------------------------------------

    def presets(self) -> list[models.Preset]:
        """Ontology presets from ``/v3/api/ontology-presets``."""
        return [
            models.Preset.from_dict(item)
            for item in self._get_items(ONTOLOGY_PRESETS_PATH, "ontology presets")
        ]

    def sources(self) -> list[models.Source]:
        """The provenance source catalogue from ``/v3/api/sources``."""
        return [models.Source.from_dict(item) for item in self._get_items(SOURCES_PATH, "sources")]

    def list_models(self) -> list[models.Model]:
        """Embedding models from ``/v3/api/models``.

        Named ``list_models`` to avoid clashing with the ``model``
        request option of :meth:`map_all`.
        """
        return [models.Model.from_dict(item) for item in self._get_items(MODELS_PATH, "models")]

    def _get_items(self, path: str, what: str) -> list[dict[str, Any]]:
        payload = self._request_json("GET", path)
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise UnexpectedResponseError(
                f"ZOOMA returned an unexpected payload for {what} "
                f"from '{self._url(path)}': expected an array of objects"
            )
        return payload

    # --- retry/skip/abort machinery -----------------------------------------

    def _process_batches(
        self,
        batches: Iterator[list[str]],
        operation: Callable[[list[str]], T],
        on_error: OnError,
    ) -> Iterator[T]:
        """Run ``operation`` per batch, yielding its results.

        A retryable failure (transport error, 429, 5xx) is retried up to
        ``RetryPolicy.max_attempts``. A non-retryable failure (client-side
        validation, 4xx, malformed response) is not retried. A batch whose
        attempts are exhausted is skipped (``on_error="skip"``) or raised
        (``on_error="raise"``). After ``RetryPolicy.max_consecutive_failures``
        skipped batches in a row, the run aborts with
        :class:`~zooma_client.errors.ServiceUnavailableError`.
        """
        consecutive_failures = 0
        for batch_number, batch in enumerate(batches, start=1):
            result = self._attempt_batch(batch_number, batch, operation, on_error)
            if result is _SKIPPED:
                consecutive_failures += 1
                if consecutive_failures >= self._retry.max_consecutive_failures:
                    raise ServiceUnavailableError(
                        f"{consecutive_failures} consecutive ZOOMA batches failed. "
                        "The service appears to be unavailable."
                    )
                continue
            consecutive_failures = 0
            yield result

    def _attempt_batch(
        self,
        batch_number: int,
        batch: list[str],
        operation: Callable[[list[str]], T],
        on_error: OnError,
    ) -> T | object:
        max_attempts = self._retry.max_attempts
        attempt = 1
        while True:
            try:
                return operation(batch)
            except FilterViolation:
                # A violated ontology filter means the server returned
                # data the caller explicitly excluded. Skipping it would
                # silently produce wrong results, so always raise.
                raise
            except RequestError as exc:
                if attempt < max_attempts:
                    remaining = max_attempts - attempt
                    self._sink(
                        f"WARNING: batch {batch_number} failed, retrying "
                        f"{self._retry.retry_description(remaining)}. Reason: {exc}"
                    )
                    time.sleep(self._retry.delay_before(attempt + 1))
                    attempt += 1
                    continue
                self._skip_or_raise(batch_number, batch, exc, on_error, retried=attempt > 1)
                return _SKIPPED
            except ZoomaError as exc:
                # Non-retryable: client-side validation, 4xx, or a
                # response that violates the API contract. Retrying
                # cannot change the outcome.
                self._skip_or_raise(batch_number, batch, exc, on_error, retried=False)
                return _SKIPPED

    def _skip_or_raise(
        self,
        batch_number: int,
        batch: list[str],
        exc: ZoomaError,
        on_error: OnError,
        *,
        retried: bool,
    ) -> None:
        if on_error == "raise":
            raise exc
        failure = f"failed {self._retry.attempts_description()}" if retried else "failed"
        self._sink(
            f"WARNING: batch {batch_number} {failure}, skipping "
            f"{len(batch)} value(s): {preview_values(batch)}. Reason: {exc}"
        )

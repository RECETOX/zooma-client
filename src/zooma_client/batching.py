"""Chunking and client-side enforcement of the ZOOMA server limits."""

import json
from collections.abc import Iterable, Iterator, Mapping
from typing import Any, TypeVar

from zooma_client.endpoints import (
    MAX_DEEP_PROPERTIES,
    MAX_PROPERTIES,
    MAX_PROPERTY_TEXT_LENGTH,
    MAX_REQUEST_BYTES,
)
from zooma_client.errors import InvalidRequestError

T = TypeVar("T")


def chunked(values: Iterable[T], size: int) -> Iterator[list[T]]:
    """Split ``values`` into consecutive lists of at most ``size`` items."""
    if size < 1:
        raise InvalidRequestError("batch size must be at least 1")
    batch: list[T] = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def max_batch_size(deep: bool) -> int:
    """The server's ceiling on the number of properties per map request.

    ``deep`` requests are capped at ``MAX_DEEP_PROPERTIES`` (200) instead
    of ``MAX_PROPERTIES`` (1000).
    """
    return MAX_DEEP_PROPERTIES if deep else MAX_PROPERTIES


def validate_batch_size(batch_size: int, deep: bool) -> None:
    """Raise if ``batch_size`` exceeds the server's per-request limit."""
    limit = max_batch_size(deep)
    if batch_size > limit:
        mode = "deep" if deep else "standard"
        raise InvalidRequestError(
            f"batch size {batch_size} exceeds the server limit of {limit} "
            f"properties per request in {mode} mode"
        )


def validate_property_value(value: str) -> None:
    """Raise if a single map value exceeds the server's text length limit."""
    if len(value) > MAX_PROPERTY_TEXT_LENGTH:
        raise InvalidRequestError(
            f"value of {len(value)} characters exceeds the server limit of "
            f"{MAX_PROPERTY_TEXT_LENGTH} characters per property"
        )


def validate_request_size(payload: Mapping[str, Any]) -> None:
    """Raise if the serialized request body would exceed the server's size limit."""
    size = len(json.dumps(payload).encode("utf-8"))
    if size > MAX_REQUEST_BYTES:
        raise InvalidRequestError(
            f"request body of {size} bytes exceeds the server limit of "
            f"{MAX_REQUEST_BYTES} bytes; use a smaller batch size"
        )

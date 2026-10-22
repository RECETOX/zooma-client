"""Chunking and client-side limit enforcement (§4.3, §7.3)."""

import pytest

from zooma_client import batching
from zooma_client.errors import InvalidRequestError


def test_chunked_splits_with_remainder():
    assert list(batching.chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]


def test_chunked_exact_division():
    assert list(batching.chunked([1, 2, 3, 4], 2)) == [[1, 2], [3, 4]]


def test_chunked_size_larger_than_input():
    assert list(batching.chunked([1], 10)) == [[1]]


def test_chunked_empty_input():
    assert list(batching.chunked([], 3)) == []


def test_chunked_invalid_size():
    with pytest.raises(InvalidRequestError, match="at least 1"):
        list(batching.chunked([1], 0))


def test_max_batch_size_depends_on_deep():
    assert batching.max_batch_size(deep=False) == 1000
    assert batching.max_batch_size(deep=True) == 200


@pytest.mark.parametrize(
    ("batch_size", "deep"),
    [(1001, False), (201, True), (5000, False)],
)
def test_validate_batch_size_raises_over_limit(batch_size, deep):
    with pytest.raises(InvalidRequestError, match="exceeds the server limit"):
        batching.validate_batch_size(batch_size, deep)


@pytest.mark.parametrize(
    ("batch_size", "deep"),
    [(1000, False), (200, True), (10, False), (10, True)],
)
def test_validate_batch_size_accepts_within_limit(batch_size, deep):
    batching.validate_batch_size(batch_size, deep)


def test_validate_property_value_accepts_boundary():
    batching.validate_property_value("x" * 1000)


def test_validate_property_value_rejects_overlong():
    with pytest.raises(InvalidRequestError, match="characters"):
        batching.validate_property_value("x" * 1001)


def test_validate_request_size_accepts_small_body():
    batching.validate_request_size({"properties": [{"textToMap": "asthma"}]})


def test_validate_request_size_rejects_oversized_body():
    payload = {"properties": [{"textToMap": "x" * 1024} for _ in range(4096)]}
    with pytest.raises(InvalidRequestError, match="bytes"):
        batching.validate_request_size(payload)

"""Formatting helpers."""

from zooma_client.util import preview_values


def test_preview_values_bounds_count():
    values = [str(number) for number in range(10)]
    # The "... (N more)" marker is repr'd like a real value, matching the
    # Galaxy tool's format exactly.
    assert preview_values(values) == "'0', '1', '2', '3', '4', '... (5 more)'"


def test_preview_values_bounds_length():
    long_value = "x" * 50
    assert preview_values([long_value]) == "'" + "x" * 40 + "...'"


def test_preview_values_few_short_values():
    assert preview_values(["a", "b"]) == "'a', 'b'"


def test_preview_values_empty():
    assert preview_values([]) == ""

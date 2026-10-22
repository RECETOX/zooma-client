"""RetryPolicy construction, backoff math and status classification."""

import pytest

from zooma_client.retry import RetryPolicy, is_retryable_status


def test_defaults_preserve_tool_behaviour():
    # The Galaxy zooma tool: two attempts, no backoff, abort after two
    # consecutive skipped batches.
    policy = RetryPolicy()
    assert policy.max_attempts == 2
    assert policy.max_consecutive_failures == 2
    assert policy.backoff == 0.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_attempts", 0),
        ("max_consecutive_failures", 0),
        ("backoff", -1.0),
        ("backoff_factor", 0.5),
    ],
)
def test_invalid_policies_rejected(field, value):
    with pytest.raises(ValueError):
        RetryPolicy(**{field: value})


def test_no_backoff_by_default():
    policy = RetryPolicy()
    assert policy.delay_before(2) == 0.0
    assert policy.delay_before(3) == 0.0


def test_exponential_backoff():
    policy = RetryPolicy(max_attempts=4, backoff=1.0)
    assert policy.delay_before(2) == 1.0
    assert policy.delay_before(3) == 2.0
    assert policy.delay_before(4) == 4.0


def test_is_retryable_status():
    assert is_retryable_status(429)
    assert is_retryable_status(500)
    assert is_retryable_status(503)
    # 4xx is permanent: retrying only hammers the server.
    assert not is_retryable_status(400)
    assert not is_retryable_status(404)
    assert not is_retryable_status(418)


def test_descriptions():
    policy = RetryPolicy()
    assert policy.retry_description(1) == "once"
    assert policy.retry_description(3) == "(3 more times)"
    assert policy.attempts_description() == "twice"

    single = RetryPolicy(max_attempts=1)
    assert single.attempts_description() == "once"

    triple = RetryPolicy(max_attempts=3)
    assert triple.attempts_description() == "3 times"

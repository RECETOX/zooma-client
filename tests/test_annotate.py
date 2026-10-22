"""Annotate mode: single-value v2 calls, caching, retry grouping (Phase 4)."""

import re

import pytest
import responses

from zooma_client import Client, ServiceUnavailableError

BASE = "https://zooma.test"
ANNOTATE_URL = f"{BASE}/v2/api/services/annotate"


def annotation(property_value, source="gwas"):
    return {
        "uri": None,
        "annotatedProperty": {
            "uri": None,
            "propertyType": "unspecified",
            "propertyValue": property_value,
        },
        "semanticTags": [f"http://purl.obolibrary.org/obo/HP_{property_value}"],
        "confidence": "HIGH",
        "derivedFrom": {
            "annotatedProperty": {"propertyValue": property_value, "propertyType": "unspecified"},
            "semanticTags": [],
            "provenance": {
                "source": {"type": "DATABASE", "name": source, "uri": source},
                "evidence": "ZOOMA_INFERRED_FROM_CURATED",
                "generator": "ZOOMA",
            },
        },
        "provenance": {
            "source": {"type": "DATABASE", "name": "zooma", "uri": "www.ebi.ac.uk/spot/zooma"},
            "evidence": "ZOOMA_INFERRED_FROM_CURATED",
            "generator": "ZOOMA",
        },
    }


@responses.activate
def test_annotate_single_value(load_fixture):
    responses.get(ANNOTATE_URL, json=load_fixture("annotate_asthma.json"))
    annotations = Client(base_url=BASE).annotate("asthma")

    assert len(annotations) == 64
    first = annotations[0]
    assert first.property.property_value == "asthma"
    assert first.confidence == "HIGH"
    assert first.semantic_tags == ("http://purl.obolibrary.org/obo/HP_0002099",)
    # One propertyValue per call; nothing else is sent.
    assert "propertyValue=asthma" in responses.calls[0].request.url
    assert len(responses.calls) == 1


@responses.activate
def test_annotate_all_issues_one_call_per_value():
    # Three values at batch size 2: the v2 endpoint accepts one
    # propertyValue per call, so exactly 3 requests are made.
    for value in ("a", "b", "c"):
        responses.get(f"{ANNOTATE_URL}?propertyValue={value}", json=[annotation(value)])

    annotations = list(Client(base_url=BASE).annotate_all(["a", "b", "c"], batch_size=2))

    assert len(responses.calls) == 3
    assert [a.property.property_value for a in annotations] == ["a", "b", "c"]


@responses.activate
def test_annotate_all_caches_duplicate_values():
    responses.get(f"{ANNOTATE_URL}?propertyValue=a", json=[annotation("a")])
    responses.get(f"{ANNOTATE_URL}?propertyValue=b", json=[annotation("b")])

    result = list(Client(base_url=BASE).annotate_all(["a", "b", "a", "b"], batch_size=1))

    # Duplicates answered from the cache: 2 calls, 4 results.
    assert len(responses.calls) == 2
    assert [a.property.property_value for a in result] == ["a", "b", "a", "b"]


@responses.activate
def test_annotate_all_retry_requeries_only_missing_values():
    # Batch ["a", "b"]: a succeeds, b fails with a retryable 503, then
    # succeeds on the retry — a must not be queried again.
    responses.get(f"{ANNOTATE_URL}?propertyValue=a", json=[annotation("a")])
    responses.get(f"{ANNOTATE_URL}?propertyValue=b", json={}, status=503)
    responses.get(f"{ANNOTATE_URL}?propertyValue=b", json=[annotation("b")])

    messages = []
    client = Client(base_url=BASE, sink=messages.append)
    result = list(client.annotate_all(["a", "b"]))

    assert [a.property.property_value for a in result] == ["a", "b"]
    urls = [call.request.url for call in responses.calls]
    assert len(urls) == 3
    assert sum("propertyValue=a" in url for url in urls) == 1
    assert re.fullmatch(r"WARNING: batch 1 failed, retrying once\. Reason: .*", messages[0])


@responses.activate
def test_annotate_all_skips_permanently_failing_values():
    responses.get(f"{ANNOTATE_URL}?propertyValue=bad", body="nope", status=400)
    responses.get(f"{ANNOTATE_URL}?propertyValue=good", json=[annotation("good")])

    messages = []
    client = Client(base_url=BASE, sink=messages.append)
    result = list(client.annotate_all(["bad", "good"], batch_size=1))

    assert [a.property.property_value for a in result] == ["good"]
    assert len(responses.calls) == 2  # the 400 is not retried
    assert re.fullmatch(
        r"WARNING: batch 1 failed, skipping 1 value\(s\): 'bad'\. Reason: .*",
        messages[0],
    )


@responses.activate
def test_annotate_all_aborts_after_consecutive_failures():
    responses.get(ANNOTATE_URL, json={}, status=503)

    with pytest.raises(ServiceUnavailableError, match="consecutive"):
        list(Client(base_url=BASE).annotate_all(["a", "b"], batch_size=1))
    assert len(responses.calls) == 4  # two batches, two attempts each


@responses.activate
def test_annotate_all_empty_result_yields_nothing():
    responses.get(f"{ANNOTATE_URL}?propertyValue=a", json=[])
    assert list(Client(base_url=BASE).annotate_all(["a"])) == []


@responses.activate
def test_annotate_all_on_error_raise_propagates():
    from zooma_client import RequestError

    responses.get(ANNOTATE_URL, json={}, status=503)
    with pytest.raises(RequestError, match="HTTP 503"):
        list(Client(base_url=BASE).annotate_all(["a"], on_error="raise"))


@responses.activate
def test_annotate_all_groups_skip_by_batch():
    # batch_size 2: both values go in one skipped batch together.
    responses.get(f"{ANNOTATE_URL}?propertyValue=a", json={}, status=500)
    responses.get(f"{ANNOTATE_URL}?propertyValue=b", json={}, status=500)

    messages = []
    client = Client(base_url=BASE, sink=messages.append)
    result = list(client.annotate_all(["a", "b"]))

    assert result == []
    # The operation aborts at the first failing value, so a retried batch
    # re-queries only "a"; "b" is never reached and both are skipped.
    assert len(responses.calls) == 2
    assert "skipping 2 value(s): 'a', 'b'" in messages[-1]

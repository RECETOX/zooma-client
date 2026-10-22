"""Map mode: batching, positional matching, filters, retry/skip/abort."""

import json
import re

import pytest
import responses

from zooma_client import (
    Client,
    FilterViolation,
    InvalidRequestError,
    ServiceUnavailableError,
    UnexpectedResponseError,
)

BASE = "https://zooma.test"
MAP_URL = f"{BASE}/v3/api/services/map"


def candidate(term_id, ontology="efo", label="label"):
    return {
        "termId": term_id,
        "label": label,
        "ontology": ontology,
        "uri": f"http://www.ebi.ac.uk/efo/{term_id}",
        "confidence": 1.0,
        "datasource": ontology,
        "mappingProvenance": [
            {
                "method": "lexical",
                "matchType": "OLS_LEXICAL_FUZZY_LABEL",
                "source": f"ols:{ontology}",
                "model": None,
                "confidence": 1.0,
                "input": "input",
                "matchedText": label,
                "similarity": 1.0,
                "target": f"http://www.ebi.ac.uk/efo/{term_id}",
            }
        ],
    }


def mapping_payload(values):
    return {
        "mappings": [
            {
                "propertyType": None,
                "textToMap": value,
                "candidates": [candidate(f"EFO_{index}")],
                "error": None,
            }
            for index, value in enumerate(values)
        ]
    }


def request_body(call_index=0):
    return json.loads(responses.calls[call_index].request.body)


# --- happy path -------------------------------------------------------------


@responses.activate
def test_map_all_yields_one_mapping_per_value_with_duplicates(load_fixture):
    responses.post(MAP_URL, json=load_fixture("map_duplicate_values.json"))
    client = Client(base_url=BASE)

    values = ["body mass index", "asthma", "body mass index"]
    mappings = list(client.map_all(values))

    # Positional: duplicate inputs stay separate, in submission order.
    assert [m.text_to_map for m in mappings] == values
    assert mappings[0].candidates == mappings[2].candidates
    # One request carries the whole batch.
    assert len(responses.calls) == 1
    assert [p["textToMap"] for p in request_body()["properties"]] == values


@responses.activate
def test_map_all_empty_candidates_yields_mapping_without_candidates():
    responses.post(
        MAP_URL,
        json={
            "mappings": [
                {"textToMap": "unknown", "propertyType": None, "candidates": [], "error": None}
            ]
        },
    )
    mappings = list(Client(base_url=BASE).map_all(["unknown"]))
    assert len(mappings) == 1
    assert mappings[0].candidates == ()
    assert mappings[0].ok


@responses.activate
def test_map_all_across_multiple_batches():
    responses.post(MAP_URL, json=mapping_payload(["a", "b"]))
    responses.post(MAP_URL, json=mapping_payload(["c"]))
    mappings = list(Client(base_url=BASE).map_all(["a", "b", "c"], batch_size=2))
    assert [m.text_to_map for m in mappings] == ["a", "b", "c"]
    assert len(responses.calls) == 2


@responses.activate
def test_map_all_request_options_sent(load_fixture):
    responses.post(MAP_URL, json=mapping_payload(["asthma"]))
    list(
        Client(base_url=BASE).map_all(
            ["asthma"],
            property_type="efo",
            exclude_term_ids=["EFO_1"],
            defining_only=True,
            return_all=True,
            deep=True,
            model="llama-embed-nemotron-8b_pca512",
        )
    )
    body = request_body()
    assert body["properties"] == [{"textToMap": "asthma", "propertyType": "efo"}]
    assert body["excludeTermIds"] == ["EFO_1"]
    assert body["definingOnly"] is True
    assert body["returnAll"] is True
    assert body["deep"] is True
    assert body["model"] == "llama-embed-nemotron-8b_pca512"
    assert "targetOntologies" not in body
    assert "includeOtherOntologies" not in body


# --- ontology filter (§4.1: fails open) --------------------------------------


@responses.activate
def test_target_ontologies_send_include_other_false(load_fixture):
    responses.post(MAP_URL, json=load_fixture("map_filtered_efo.json"))
    list(Client(base_url=BASE).map_all(["body mass index"], target_ontologies=["efo"]))

    body = request_body()
    assert body["targetOntologies"] == ["efo"]
    # The filter only restricts in combination with includeOtherOntologies=false,
    # which the client sends by default.
    assert body["includeOtherOntologies"] is False


@responses.activate
def test_target_ontologies_no_filter_means_no_flag():
    responses.post(MAP_URL, json=mapping_payload(["asthma"]))
    list(Client(base_url=BASE).map_all(["asthma"]))
    body = request_body()
    assert "targetOntologies" not in body
    assert "includeOtherOntologies" not in body


@responses.activate
def test_include_other_ontologies_true_is_sent_verbatim():
    responses.post(MAP_URL, json=mapping_payload(["asthma"]))
    list(
        Client(base_url=BASE).map_all(
            ["asthma"], target_ontologies=["efo"], include_other_ontologies=True
        )
    )
    body = request_body()
    assert body["includeOtherOntologies"] is True


@responses.activate
def test_filter_violation_always_raises_even_in_skip_mode(load_fixture):
    # The unfiltered payload contains cmo/ncit/... candidates; asking for
    # efo-only must not silently return them.
    responses.post(MAP_URL, json=load_fixture("map_duplicate_values.json"))
    client = Client(base_url=BASE)

    with pytest.raises(FilterViolation, match="outside the requested set"):
        list(client.map_all(["body mass index", "asthma", "body mass index"],
                             target_ontologies=["efo"]))


@responses.activate
def test_filter_respecting_response_passes(load_fixture):
    responses.post(MAP_URL, json=load_fixture("map_filtered_efo.json"))
    mappings = list(Client(base_url=BASE).map_all(["body mass index"], target_ontologies=["EFO"]))
    assert all(c.ontology == "efo" for m in mappings for c in m.candidates)


@responses.activate
def test_filter_check_is_case_insensitive(load_fixture):
    responses.post(MAP_URL, json=load_fixture("map_filtered_efo.json"))
    mappings = list(Client(base_url=BASE).map_all(["body mass index"], target_ontologies=["EFO"]))
    assert len(mappings) == 1


# --- response shape validation (§4.2: a 200 can be the web app) --------------


@responses.activate
def test_html_response_raises():
    responses.post(MAP_URL, body="<html><body>Zooma</body></html>", content_type="text/html")
    with pytest.raises(UnexpectedResponseError, match="Content-Type"):
        list(Client(base_url=BASE).map_all(["asthma"], on_error="raise"))


@responses.activate
def test_count_mismatch_raises():
    responses.post(MAP_URL, json=mapping_payload(["a"]))
    with pytest.raises(UnexpectedResponseError, match=r"1 mappings.*2 submitted"):
        list(Client(base_url=BASE).map_all(["a", "b"], on_error="raise"))


@responses.activate
def test_echo_mismatch_raises():
    payload = {"mappings": [{"textToMap": "wrong", "candidates": [], "error": None}]}
    responses.post(MAP_URL, json=payload)
    with pytest.raises(UnexpectedResponseError, match=r"'wrong'.*'asthma'"):
        list(Client(base_url=BASE).map_all(["asthma"], on_error="raise"))


@responses.activate
def test_missing_mappings_key_raises():
    responses.post(MAP_URL, json={"unexpected": []})
    with pytest.raises(UnexpectedResponseError, match="mappings"):
        list(Client(base_url=BASE).map_all(["asthma"], on_error="raise"))


@responses.activate
def test_malformed_json_raises():
    responses.post(MAP_URL, body="{not json", content_type="application/json")
    with pytest.raises(UnexpectedResponseError, match="malformed JSON"):
        list(Client(base_url=BASE).map_all(["asthma"], on_error="raise"))


# --- per-value error mappings (§3) -------------------------------------------


@responses.activate
def test_error_mapping_skipped_silently():
    responses.post(MAP_URL, json={"mappings": [{"textToMap": "bad", "error": "boom"}]})
    messages = []
    client = Client(base_url=BASE, sink=messages.append)
    assert list(client.map_all(["bad"])) == []
    assert messages == []  # matches the tool's silent drop


@responses.activate
def test_error_mapping_raises_in_raise_mode():
    responses.post(MAP_URL, json={"mappings": [{"textToMap": "bad", "error": "boom"}]})
    with pytest.raises(UnexpectedResponseError, match="boom"):
        list(Client(base_url=BASE).map_all(["bad"], on_error="raise"))


# --- client-side validation (§7.3: fail before any network call) -------------


@responses.activate
def test_overlong_value_fails_without_network():
    client = Client(base_url=BASE)
    # Length is validated per batch (so the skip machinery handles it),
    # i.e. when the generator is iterated — never over the network.
    with pytest.raises(InvalidRequestError, match="characters"):
        list(client.map_all(["x" * 1001], on_error="raise"))
    assert len(responses.calls) == 0


def test_batch_size_over_limit_raises_immediately():
    # Eager validation: raises at call time, not on first iteration.
    with pytest.raises(InvalidRequestError, match="server limit"):
        Client(base_url=BASE).map_all(["a"], batch_size=1001)


def test_deep_mode_batch_size_over_limit_raises_immediately():
    with pytest.raises(InvalidRequestError, match="deep mode"):
        Client(base_url=BASE).map_all(["a"], batch_size=201, deep=True)


def test_invalid_on_error_raises():
    with pytest.raises(InvalidRequestError, match="on_error"):
        Client(base_url=BASE).map_all(["a"], on_error="ignore")  # type: ignore[arg-type]


# --- retry / skip / abort (§7.2) ---------------------------------------------


@responses.activate
def test_retryable_error_recovers_with_tool_warning_format():
    responses.post(MAP_URL, status=503)
    responses.post(MAP_URL, json=mapping_payload(["asthma"]))
    messages = []
    client = Client(base_url=BASE, sink=messages.append)

    mappings = list(client.map_all(["asthma"]))

    assert len(responses.calls) == 2
    assert [m.text_to_map for m in mappings] == ["asthma"]
    # Byte-compatible with the Galaxy tool's asserted stdout lines.
    assert re.fullmatch(r"WARNING: batch 1 failed, retrying once\. Reason: .*", messages[0])


@responses.activate
def test_client_error_is_not_retried():
    # A 400 is permanent: retrying only hammers the server.
    responses.post(MAP_URL, body="value too long", status=400)
    messages = []
    client = Client(base_url=BASE, sink=messages.append)

    assert list(client.map_all(["asthma"])) == []
    assert len(responses.calls) == 1
    assert re.fullmatch(
        r"WARNING: batch 1 failed, skipping 1 value\(s\): 'asthma'\. Reason: .*",
        messages[0],
    )


@responses.activate
def test_transport_error_is_retried():
    import requests as requests_lib

    responses.post(MAP_URL, body=requests_lib.ConnectionError("reset"))
    responses.post(MAP_URL, json=mapping_payload(["asthma"]))

    mappings = list(Client(base_url=BASE).map_all(["asthma"]))
    assert [m.text_to_map for m in mappings] == ["asthma"]
    assert len(responses.calls) == 2


@responses.activate
def test_two_consecutive_failures_abort_with_tool_warning_format():
    responses.post(MAP_URL, status=503)
    messages = []
    client = Client(base_url=BASE, sink=messages.append)

    with pytest.raises(ServiceUnavailableError, match="consecutive"):
        list(client.map_all(["a", "b"], batch_size=1))

    # Both batches attempted twice, then the run aborts.
    assert len(responses.calls) == 4
    assert re.fullmatch(
        r"WARNING: batch 1 failed twice, skipping 1 value\(s\): 'a'\. Reason: .*",
        messages[1],
    )
    assert re.fullmatch(
        r"WARNING: batch 2 failed twice, skipping 1 value\(s\): 'b'\. Reason: .*",
        messages[3],
    )


@responses.activate
def test_failure_streak_resets_on_success():
    # Batch "a" fails twice (skipped), "ok" succeeds, "b" fails twice
    # (skipped), "fine" succeeds: never two consecutive failures, no abort.
    responses.post(MAP_URL, status=503)
    responses.post(MAP_URL, status=503)
    responses.post(MAP_URL, json=mapping_payload(["ok"]))
    responses.post(MAP_URL, status=503)
    responses.post(MAP_URL, status=503)
    responses.post(MAP_URL, json=mapping_payload(["fine"]))

    client = Client(base_url=BASE)
    results = list(client.map_all(["a", "ok", "b", "fine"], batch_size=1))

    assert [m.text_to_map for m in results] == ["ok", "fine"]


@responses.activate
def test_backoff_sleeps_between_retries(monkeypatch):
    sleeps = []
    monkeypatch.setattr("zooma_client.client.time.sleep", sleeps.append)
    responses.post(MAP_URL, status=503)
    responses.post(MAP_URL, status=503)
    responses.post(MAP_URL, json=mapping_payload(["asthma"]))

    from zooma_client import RetryPolicy

    client = Client(
        base_url=BASE, retry=RetryPolicy(max_attempts=3, backoff=1.0, backoff_factor=2.0)
    )
    mappings = list(client.map_all(["asthma"]))

    assert [m.text_to_map for m in mappings] == ["asthma"]
    assert sleeps == [1.0, 2.0]


@responses.activate
def test_on_error_raise_propagates_first_failure():
    responses.post(MAP_URL, status=503)
    client = Client(base_url=BASE)

    from zooma_client import RequestError

    with pytest.raises(RequestError, match="HTTP 503"):
        list(client.map_all(["asthma"], on_error="raise"))


@responses.activate
def test_custom_retry_policy_three_attempts():
    from zooma_client import RetryPolicy

    responses.post(MAP_URL, status=500)
    responses.post(MAP_URL, status=500)
    responses.post(MAP_URL, json=mapping_payload(["asthma"]))

    client = Client(base_url=BASE, retry=RetryPolicy(max_attempts=3))
    mappings = list(client.map_all(["asthma"]))

    assert [m.text_to_map for m in mappings] == ["asthma"]
    assert len(responses.calls) == 3


# --- never writes to a stream itself (§7.1) -----------------------------------


@responses.activate
def test_library_never_writes_to_stdout_or_stderr(capsys):
    responses.post(MAP_URL, status=503)
    responses.post(MAP_URL, json=mapping_payload(["asthma"]))

    list(Client(base_url=BASE).map_all(["asthma"]))
    list(Client(base_url=BASE).map_all(["asthma"]))

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

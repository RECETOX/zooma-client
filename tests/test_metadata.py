"""Metadata endpoints: presets, sources, models (Phase 5)."""

import pytest
import responses

from zooma_client import Client, UnexpectedResponseError

BASE = "https://zooma.test"


@responses.activate
def test_presets(load_fixture):
    responses.get(f"{BASE}/v3/api/ontology-presets", json=load_fixture("presets.json"))
    presets = Client(base_url=BASE).presets()

    assert len(presets) == 2
    assert presets[0].name == "EFO and OBO Foundry"
    assert "efo" in presets[0].ontologies
    assert len(responses.calls) == 1


@responses.activate
def test_sources(load_fixture):
    responses.get(f"{BASE}/v3/api/sources", json=load_fixture("sources.json"))
    sources = Client(base_url=BASE).sources()

    assert len(sources) == 301
    assert sources[0].name == "sysmicro"
    assert any(source.type == "ONTOLOGY" for source in sources)


@responses.activate
def test_list_models(load_fixture):
    responses.get(f"{BASE}/v3/api/models", json=load_fixture("models.json"))
    models = Client(base_url=BASE).list_models()

    assert len(models) == 4
    assert [model.name for model in models if model.can_embed] == [
        "llama-embed-nemotron-8b_pca512"
    ]


@responses.activate
def test_metadata_html_trap_raises():
    # The SPA answers 200 with HTML on any unknown path; the metadata
    # parsers must not silently return [] for it.
    responses.get(f"{BASE}/v3/api/models", body="<html></html>", content_type="text/html")
    with pytest.raises(UnexpectedResponseError, match="Content-Type"):
        Client(base_url=BASE).list_models()


@responses.activate
def test_metadata_non_list_payload_raises():
    responses.get(f"{BASE}/v3/api/models", json={"models": []})
    with pytest.raises(UnexpectedResponseError, match="array of objects"):
        Client(base_url=BASE).list_models()

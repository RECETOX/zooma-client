"""Model parsing against captured live payloads (Phase 1 validation)."""

from zooma_client.models import (
    AnnotatedProperty,
    Annotation,
    Candidate,
    Mapping,
    Model,
    Preset,
    Source,
)


def test_mapping_parses_captured_payload(load_fixture):
    payload = load_fixture("map_duplicate_values.json")
    mappings = [Mapping.from_dict(raw) for raw in payload["mappings"]]

    # Positional echo: one mapping per submitted value, in order, with the
    # repeated value appearing twice.
    assert [m.text_to_map for m in mappings] == [
        "body mass index",
        "asthma",
        "body mass index",
    ]
    # "propertyType": null is real in live responses.
    assert mappings[0].property_type is None
    assert mappings[0].error is None
    assert mappings[0].ok

    assert len(mappings[0].candidates) == 8
    assert len(mappings[1].candidates) == 10

    # Duplicate inputs must stay separate and identical.
    assert mappings[2].candidates == mappings[0].candidates

    candidate = mappings[0].candidates[0]
    assert candidate.term_id == "CMO_0000105"
    assert candidate.label == "body mass index"
    assert candidate.ontology == "cmo"
    assert candidate.datasource == "cmo"
    assert candidate.confidence == 1.0
    assert candidate.uri == "http://purl.obolibrary.org/obo/CMO_0000105"

    provenance = candidate.provenance[0]
    assert provenance.method == "lexical"
    assert provenance.match_type == "OLS_LEXICAL_FUZZY_LABEL"
    assert provenance.source == "ols:cmo"
    assert provenance.similarity == 1.0
    assert provenance.matched_text == "body mass index"
    # "model": null is genuinely exercised by live responses.
    assert provenance.model is None


def test_candidate_parses_supporting_provenance(load_fixture):
    payload = load_fixture("map_filtered_efo.json")
    mapping = Mapping.from_dict(payload["mappings"][0])
    candidate = mapping.candidates[0]

    assert candidate.term_id == "EFO_0004340"
    assert candidate.ontology == "efo"
    assert len(candidate.provenance) == 1
    assert candidate.provenance[0].match_type == "OLS_LEXICAL_FUZZY_LABEL"

    supporting = candidate.supporting_provenance
    assert len(supporting) == 1
    assert len(supporting[0]) == 1
    assert supporting[0][0].match_type == "OLS_EMBEDDING"
    assert supporting[0][0].model == "llama-embed-nemotron-8b_pca512"
    assert supporting[0][0].similarity == 0.926111


def test_mapping_with_error_field():
    mapping = Mapping.from_dict({"textToMap": "x" * 1001, "error": "value too long"})
    assert not mapping.ok
    assert mapping.error == "value too long"
    assert mapping.candidates == ()


def test_mapping_with_empty_candidates():
    mapping = Mapping.from_dict({"textToMap": "unknown", "candidates": [], "error": None})
    assert mapping.ok
    assert mapping.candidates == ()


def test_models_tolerate_missing_and_null_keys():
    # Every None default must be reachable through a sparse payload.
    assert Mapping.from_dict({}) == Mapping()
    assert Candidate.from_dict({}) == Candidate()
    assert AnnotatedProperty.from_dict({}) == AnnotatedProperty()
    assert Annotation.from_dict({}) == Annotation()
    assert Preset.from_dict({}) == Preset()
    assert Source.from_dict({}) == Source()
    assert Model.from_dict({}) == Model()

    # Nulls are not errors either.
    nulls = Mapping.from_dict({"textToMap": None, "propertyType": None, "error": None})
    assert nulls.candidates == ()


def test_annotation_parses_captured_payload(load_fixture):
    payload = load_fixture("annotate_asthma.json")
    annotations = [Annotation.from_dict(raw) for raw in payload]
    assert len(annotations) == 64

    first = annotations[0]
    assert first.property is not None
    assert first.property.property_value == "asthma"
    assert first.property.property_type == "unspecified"
    assert first.semantic_tags == ("http://purl.obolibrary.org/obo/HP_0002099",)
    assert first.confidence == "HIGH"

    # Top-level provenance.
    assert first.provenance is not None
    assert first.provenance.source is not None
    assert first.provenance.source.name == "zooma"
    assert first.provenance.source.type == "DATABASE"
    assert first.provenance.evidence == "ZOOMA_INFERRED_FROM_CURATED"
    assert first.provenance.generator == "ZOOMA"

    # derivedFrom is a nested annotation record with its own provenance.
    assert len(first.derived_from) == 1
    derived = first.derived_from[0]
    assert derived.provenance is not None
    assert derived.provenance.source is not None
    assert derived.provenance.source.name == "hp"
    assert derived.provenance.source.type == "ONTOLOGY"
    assert derived.provenance.evidence == "OLS_LEXICAL_FUZZY_LABEL"
    assert derived.confidence is None


def test_annotation_tolerates_derived_from_as_list():
    # The v2 schema has drifted between dict and list for derivedFrom;
    # both shapes must parse.
    raw = {
        "annotatedProperty": {"propertyValue": "x", "propertyType": None},
        "semanticTags": ["http://example.org/a"],
        "derivedFrom": [
            {"provenance": {"source": {"name": "gwas", "type": "DATABASE", "uri": "gwas"}}},
            {"provenance": None},
        ],
    }
    annotation = Annotation.from_dict(raw)
    assert len(annotation.derived_from) == 2
    assert annotation.derived_from[0].provenance.source.name == "gwas"
    assert annotation.derived_from[1].provenance is None


def test_preset_parses_captured_payload(load_fixture):
    presets = [Preset.from_dict(raw) for raw in load_fixture("presets.json")]
    assert len(presets) == 2
    assert presets[0].name == "EFO and OBO Foundry"
    assert presets[0].description is None  # genuinely null in the live response
    assert "efo" in presets[0].ontologies
    assert len(presets[0].ontologies) > len(presets[1].ontologies)


def test_source_parses_captured_payload(load_fixture):
    sources = [Source.from_dict(raw) for raw in load_fixture("sources.json")]
    assert len(sources) == 301
    assert sources[0] == Source(name="sysmicro", type="DATABASE", uri="https://www.ebi.ac.uk/fg/sym")
    assert any(source.type == "ONTOLOGY" for source in sources)


def test_model_parses_captured_payload(load_fixture):
    models = [Model.from_dict(raw) for raw in load_fixture("models.json")]
    assert len(models) == 4
    embedders = [model for model in models if model.can_embed]
    assert [model.name for model in embedders] == ["llama-embed-nemotron-8b_pca512"]

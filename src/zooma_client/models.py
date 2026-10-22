"""Frozen dataclasses mirroring the ZOOMA API response payloads.

Every model has a ``from_dict`` classmethod that tolerates missing and
``null`` keys: the live API genuinely returns ``"propertyType": null``,
``"uri": null`` and ``"model": null`` in ordinary responses, and a field
being ``None`` is not an error.

The v3 map and v2 annotate APIs carry genuinely different evidence
(``mappingProvenance[].method/similarity`` vs ``provenance.source.name``),
so they get distinct result types — :class:`Mapping` and
:class:`Annotation` — instead of a merged "common" shape. Field names are
snake_case; the original JSON keys are mapped explicitly in ``from_dict``.
"""

# Deferred annotations: this module defines its own ``Mapping`` result type,
# which would otherwise shadow ``collections.abc.Mapping`` in the
# ``from_dict`` signatures defined after it.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _text(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return None if value is None else str(value)


def _number(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _texts(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if item is not None)


# --- v3 map -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Provenance:
    """One ``mappingProvenance`` entry: how a candidate was matched."""

    method: str | None = None
    match_type: str | None = None
    source: str | None = None
    model: str | None = None
    confidence: float | None = None
    input: str | None = None
    matched_text: str | None = None
    similarity: float | None = None
    target: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Provenance:
        return cls(
            method=_text(data, "method"),
            match_type=_text(data, "matchType"),
            source=_text(data, "source"),
            model=_text(data, "model"),
            confidence=_number(data, "confidence"),
            input=_text(data, "input"),
            matched_text=_text(data, "matchedText"),
            similarity=_number(data, "similarity"),
            target=_text(data, "target"),
        )


@dataclass(frozen=True, slots=True)
class Candidate:
    """One ontology term candidate for a mapped value."""

    term_id: str | None = None
    label: str | None = None
    ontology: str | None = None
    uri: str | None = None
    confidence: float | None = None
    datasource: str | None = None
    provenance: tuple[Provenance, ...] = ()
    supporting_provenance: tuple[tuple[Provenance, ...], ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Candidate:
        supporting: list[tuple[Provenance, ...]] = []
        raw_supporting = data.get("supportingProvenance")
        if isinstance(raw_supporting, list):
            for group in raw_supporting:
                if isinstance(group, list):
                    supporting.append(
                        tuple(Provenance.from_dict(p) for p in group if isinstance(p, dict))
                    )
                elif isinstance(group, dict):
                    supporting.append((Provenance.from_dict(group),))
        raw_provenance = data.get("mappingProvenance")
        return cls(
            term_id=_text(data, "termId"),
            label=_text(data, "label"),
            ontology=_text(data, "ontology"),
            uri=_text(data, "uri"),
            confidence=_number(data, "confidence"),
            datasource=_text(data, "datasource"),
            provenance=tuple(
                Provenance.from_dict(p) for p in raw_provenance if isinstance(p, dict)
            )
            if isinstance(raw_provenance, list)
            else (),
            supporting_provenance=tuple(supporting),
        )


@dataclass(frozen=True, slots=True)
class Mapping:
    """The v3 map result for one submitted value.

    ``text_to_map`` echoes the submitted value; results are matched to
    inputs by position, never by value (value matching would merge
    duplicate inputs). ``error`` is set when the server failed on this
    value instead of returning candidates; ``ok`` is then ``False``.
    """

    text_to_map: str | None = None
    property_type: str | None = None
    candidates: tuple[Candidate, ...] = ()
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Mapping:
        raw_candidates = data.get("candidates")
        return cls(
            text_to_map=_text(data, "textToMap"),
            property_type=_text(data, "propertyType"),
            candidates=tuple(
                Candidate.from_dict(c) for c in raw_candidates if isinstance(c, dict)
            )
            if isinstance(raw_candidates, list)
            else (),
            error=_text(data, "error"),
        )

    @property
    def ok(self) -> bool:
        """False when the server reported a per-value error."""
        return self.error is None


# --- v2 annotate ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Source:
    """A provenance source, from ``/v3/api/sources`` or a v2 annotation's
    provenance (both use the same ``{type, name, uri}`` shape)."""

    name: str | None = None
    type: str | None = None
    uri: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Source:
        return cls(
            name=_text(data, "name"),
            type=_text(data, "type"),
            uri=_text(data, "uri"),
        )


@dataclass(frozen=True, slots=True)
class AnnotationProvenance:
    """The ``provenance`` block of a v2 annotation."""

    source: Source | None = None
    evidence: str | None = None
    accuracy: float | None = None
    generator: str | None = None
    annotator: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnnotationProvenance:
        raw_source = data.get("source")
        return cls(
            source=Source.from_dict(raw_source) if isinstance(raw_source, dict) else None,
            evidence=_text(data, "evidence"),
            accuracy=_number(data, "accuracy"),
            generator=_text(data, "generator"),
            annotator=_text(data, "annotator"),
        )


@dataclass(frozen=True, slots=True)
class AnnotatedProperty:
    """The ``annotatedProperty`` block of a v2 annotation."""

    property_value: str | None = None
    property_type: str | None = None
    uri: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnnotatedProperty:
        return cls(
            property_value=_text(data, "propertyValue"),
            property_type=_text(data, "propertyType"),
            uri=_text(data, "uri"),
        )


@dataclass(frozen=True, slots=True)
class Annotation:
    """One v2 annotate result for the submitted value."""

    property: AnnotatedProperty | None = None
    semantic_tags: tuple[str, ...] = ()
    confidence: str | None = None
    provenance: AnnotationProvenance | None = None
    derived_from: tuple[Annotation, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Annotation:
        raw_derived = data.get("derivedFrom")
        if isinstance(raw_derived, dict):
            derived_items: list[dict[str, Any]] = [raw_derived]
        elif isinstance(raw_derived, list):
            derived_items = [item for item in raw_derived if isinstance(item, dict)]
        else:
            derived_items = []
        raw_property = data.get("annotatedProperty")
        raw_provenance = data.get("provenance")
        return cls(
            property=AnnotatedProperty.from_dict(raw_property)
            if isinstance(raw_property, dict)
            else None,
            semantic_tags=_texts(data, "semanticTags"),
            confidence=_text(data, "confidence"),
            provenance=AnnotationProvenance.from_dict(raw_provenance)
            if isinstance(raw_provenance, dict)
            else None,
            derived_from=tuple(cls.from_dict(item) for item in derived_items),
        )


# --- v3 metadata ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Preset:
    """An ontology preset from ``/v3/api/ontology-presets``."""

    name: str | None = None
    description: str | None = None
    ontologies: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Preset:
        return cls(
            name=_text(data, "name"),
            description=_text(data, "description"),
            ontologies=_texts(data, "ontologies"),
        )


@dataclass(frozen=True, slots=True)
class Model:
    """An embedding model from ``/v3/api/models``.

    ``name`` is the value accepted by ``Client.map_all(model=...)``; the
    API's JSON key is ``"model"``.
    """

    name: str | None = None
    can_embed: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Model:
        return cls(
            name=_text(data, "model"),
            can_embed=bool(data.get("can_embed", False)),
        )

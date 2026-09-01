"""Validation and normalization for metadata already extracted by a model.

This module never interprets article prose. It only checks structured extraction
or triage fields against reviewed local vocabularies and reports conflicts.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from episignal_backend.db.types import EventType, Precision
from episignal_backend.geocode.normalize import ascii_form, normalized_form
from episignal_backend.ingestion.gdelt.locale import COUNTRY_CODES


@dataclass(frozen=True)
class DiseaseVocabularyEntry:
    id: UUID
    canonical_name: str
    slug: str
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True)
class Admin1VocabularyEntry:
    name: str
    country_code: str
    code: str
    alternate_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetadataFields:
    """One accepted metadata answer from extraction or triage."""

    disease: str | None = None
    country: str | None = None
    admin1: str | None = None
    admin2: str | None = None
    location_text: str | None = None
    place_name: str | None = None


@dataclass(frozen=True)
class MetadataEvidence:
    title: str
    text: str
    extraction: MetadataFields | None = None
    triage: MetadataFields | None = None


MetadataSource = Literal["extraction", "triage", "unresolved"]


@dataclass(frozen=True)
class MetadataRepairEvent:
    event_id: UUID
    country_code: str | None
    admin1: str | None
    disease_id: UUID | None
    signals: tuple[MetadataEvidence, ...]
    event_type: EventType | None = None


@dataclass(frozen=True)
class EventMetadataPatch:
    country_code: str | None = None
    admin1: str | None = None
    disease_id: UUID | None = None
    event_type: EventType | None = None

    @property
    def changed(self) -> bool:
        return any(
            value is not None
            for value in (self.country_code, self.admin1, self.disease_id, self.event_type)
        )


def metadata_fields_from_extraction(extraction: Any) -> MetadataFields | None:
    if extraction is None:
        return None
    locations = tuple(getattr(extraction, "locations", ()) or ())
    source = next(
        (item for item in locations if getattr(item.role, "value", item.role) == "primary"),
        next(iter(locations), None),
    )
    return MetadataFields(
        disease=extraction.disease.name if extraction.disease is not None else None,
        country=getattr(source, "country", None),
        admin1=getattr(source, "admin1", None),
        place_name=getattr(source, "place_name", None),
    )


def metadata_evidence_for_signal(signal: Any, extraction: Any) -> MetadataEvidence:
    return MetadataEvidence(
        title=signal.title,
        text=getattr(signal, "raw_text", None) or "",
        extraction=metadata_fields_from_extraction(extraction),
        triage=MetadataFields(
            disease=getattr(signal, "triage_disease_text", None),
            country=getattr(signal, "triage_country_code", None),
            admin1=getattr(signal, "triage_admin1", None),
            admin2=getattr(signal, "triage_admin2", None),
            location_text=getattr(signal, "triage_location_text", None),
        ),
    )


def repair_event_metadata(
    event: MetadataRepairEvent, resolver: "LocalMetadataResolver"
) -> EventMetadataPatch:
    resolved = resolve_repair_evidence(event.signals, resolver)
    country_code = resolved.country_code if event.country_code is None else None
    disease_id = resolved.disease_id if event.disease_id is None else None
    wanted_country = event.country_code or country_code
    admin1 = None
    if (
        event.admin1 is None
        and wanted_country is not None
        and resolved.country_code == wanted_country
    ):
        admin1 = resolved.admin1
    event_type = (
        EventType.OUTBREAK
        if disease_id is not None
        and event.disease_id is None
        and event.event_type == EventType.UNKNOWN_DISEASE_EVENT
        else None
    )
    return EventMetadataPatch(
        country_code=country_code,
        admin1=admin1,
        disease_id=disease_id,
        event_type=event_type,
    )


def resolve_repair_evidence(
    evidence: Sequence[MetadataEvidence], resolver: "LocalMetadataResolver"
) -> "ResolvedMetadata":
    """Conservatively combine validated metadata from linked signals."""
    values = tuple(resolver.resolve(item) for item in evidence)
    conflicts: list[str] = []

    def choose(field: str) -> tuple[Any, MetadataSource]:
        populated = [
            (getattr(value, field), getattr(value, f"{field}_source", "unresolved"))
            for value in values
            if getattr(value, field) is not None
        ]
        unique = {value for value, _ in populated}
        if len(unique) != 1:
            if len(unique) > 1:
                conflicts.append(field)
            return None, "unresolved"
        selected = next(iter(unique))
        sources = {source for value, source in populated if value == selected}
        source: MetadataSource = "extraction" if "extraction" in sources else "triage"
        return selected, source

    disease_id, disease_source = choose("disease_id")
    disease_text, _ = choose("disease_text")
    country_code, country_source = choose("country_code")
    admin1, admin1_source = choose("admin1")
    admin2, _ = choose("admin2")
    place_name, _ = choose("place_name")
    location_text, _ = choose("location_text")
    if admin1 is not None and resolver._country_for_admin1(admin1) != country_code:
        conflicts.append("admin1")
        admin1 = None
        admin1_source = "unresolved"

    return ResolvedMetadata(
        disease_id=disease_id,
        disease_text=disease_text,
        country_code=country_code,
        admin1=admin1,
        admin2=admin2,
        place_name=place_name,
        location_text=location_text,
        disease_source=disease_source,
        country_source=country_source,
        admin1_source=admin1_source,
        conflicts=tuple(dict.fromkeys(conflicts)),
    )


@dataclass(frozen=True)
class ResolvedMetadata:
    disease_id: UUID | None = None
    disease_text: str | None = None
    country_code: str | None = None
    admin1: str | None = None
    admin2: str | None = None
    place_name: str | None = None
    location_text: str | None = None
    disease_source: MetadataSource = "unresolved"
    country_source: MetadataSource = "unresolved"
    admin1_source: MetadataSource = "unresolved"
    conflicts: tuple[str, ...] = ()

    @property
    def precision(self) -> Precision:
        if self.admin1 is not None:
            return Precision.ADMIN1
        if self.country_code is not None:
            return Precision.COUNTRY
        return Precision.UNRESOLVED

    @property
    def has_location(self) -> bool:
        return any(
            value is not None
            for value in (
                self.country_code,
                self.admin1,
                self.admin2,
                self.place_name,
                self.location_text,
            )
        )


@dataclass(frozen=True)
class _Admin1Match:
    entry: Admin1VocabularyEntry
    matched_name: str


class LocalMetadataResolver:
    """Validate structured metadata with exact, reviewed local data only."""

    def __init__(
        self,
        *,
        country_aliases: Mapping[str, str],
        country_codes: Sequence[str] = (),
        diseases: Sequence[DiseaseVocabularyEntry] = (),
        admin1s: Sequence[Admin1VocabularyEntry] = (),
    ) -> None:
        aliases = {
            normalized_form(name): code for name, code in COUNTRY_CODES.items() if name != "congo"
        }
        aliases.update(
            {normalized_form(name): code.upper() for name, code in country_aliases.items()}
        )
        self._country_aliases = aliases
        self._country_codes = frozenset(
            {code.upper() for code in country_codes if len(code) == 2}
            | set(self._country_aliases.values())
        )
        self._diseases = tuple(diseases)
        self._admin1s = tuple(admin1s)
        disease_aliases: dict[str, set[UUID]] = defaultdict(set)
        for disease in self._diseases:
            for name in (disease.canonical_name, disease.slug, *disease.synonyms):
                key = normalized_form(name)
                if key:
                    disease_aliases[key].add(disease.id)
        self._disease_aliases = {name: frozenset(ids) for name, ids in disease_aliases.items()}
        self._diseases_by_id = {disease.id: disease for disease in self._diseases}

    def validate_metadata(self, fields: MetadataFields) -> ResolvedMetadata:
        """Normalize one structured model answer without reading article text."""
        country_code = self._resolve_country_value(fields.country)
        disease_id = self._resolve_disease_value(fields.disease)
        disease = self._diseases_by_id[disease_id].canonical_name if disease_id else None
        admin1_match = self._resolve_admin1_value(fields.admin1, country_code)
        if fields.admin1 is not None and admin1_match is None:
            # A model supplied a geographic hierarchy that cannot be validated
            # together. Keep the whole location unresolved rather than pairing
            # a country with a rejected province.
            country_code = None
        location_text = fields.location_text or fields.place_name
        return ResolvedMetadata(
            disease_id=disease_id,
            disease_text=disease,
            country_code=country_code,
            admin1=admin1_match.entry.code if admin1_match is not None else None,
            admin2=fields.admin2,
            place_name=fields.place_name,
            location_text=location_text,
        )

    def resolve(self, evidence: MetadataEvidence) -> ResolvedMetadata:
        """Choose extraction metadata before triage metadata, field by field."""
        source_values: list[tuple[MetadataSource, ResolvedMetadata]] = []
        if evidence.extraction is not None:
            source_values.append(("extraction", self.validate_metadata(evidence.extraction)))
        if evidence.triage is not None:
            source_values.append(("triage", self.validate_metadata(evidence.triage)))

        conflicts: list[str] = []

        def choose(field: str) -> tuple[Any, MetadataSource]:
            populated = [
                (source, getattr(value, field))
                for source, value in source_values
                if getattr(value, field) is not None
            ]
            unique = {value for _, value in populated}
            if len(unique) > 1:
                conflicts.append(field)
            return (populated[0][1], populated[0][0]) if populated else (None, "unresolved")

        disease_id, disease_source = choose("disease_id")
        disease_text, _ = choose("disease_text")
        country_code, country_source = choose("country_code")
        admin1, admin1_source = choose("admin1")
        admin2, _ = choose("admin2")
        place_name, _ = choose("place_name")
        location_text, _ = choose("location_text")

        if admin1 is not None:
            admin1_country = self._country_for_admin1(admin1)
            if admin1_country != country_code:
                conflicts.append("admin1")
                admin1 = None
                admin1_source = "unresolved"

        return ResolvedMetadata(
            disease_id=disease_id,
            disease_text=disease_text,
            country_code=country_code,
            admin1=admin1,
            admin2=admin2,
            place_name=place_name,
            location_text=location_text,
            disease_source=disease_source,
            country_source=country_source,
            admin1_source=admin1_source,
            conflicts=tuple(dict.fromkeys(conflicts)),
        )

    def _resolve_country_value(self, value: str | None) -> str | None:
        if value is None:
            return None
        code = value.strip().upper()
        if len(code) == 2 and code.isalpha() and code in self._country_codes:
            return code
        return self._country_aliases.get(normalized_form(value))

    def _resolve_disease_value(self, value: str | None) -> UUID | None:
        if value is None:
            return None
        ids = self._disease_aliases.get(normalized_form(value), frozenset())
        return next(iter(ids)) if len(ids) == 1 else None

    def _resolve_admin1_value(
        self, value: str | None, country_code: str | None
    ) -> _Admin1Match | None:
        if value is None:
            return None
        for form in (normalized_form(value), ascii_form(value)):
            matches = [
                _Admin1Match(entry, entry.name)
                for entry in self._admin1s
                if country_code in (None, entry.country_code)
                and form
                in {
                    normalized_form(entry.name),
                    ascii_form(entry.name),
                    *(normalized_form(alias) for alias in entry.alternate_names),
                    *(ascii_form(alias) for alias in entry.alternate_names),
                }
            ]
            unique = {(match.entry.country_code, match.entry.code): match for match in matches}
            if len(unique) == 1:
                return next(iter(unique.values()))
            if unique:
                return None
        return None

    def _country_for_admin1(self, code: str) -> str | None:
        countries = {entry.country_code for entry in self._admin1s if entry.code == code}
        return next(iter(countries)) if len(countries) == 1 else None

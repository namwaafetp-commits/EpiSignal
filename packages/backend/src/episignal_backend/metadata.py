"""Conservative metadata resolution from accepted fields and local references.

The resolver never calls a model or a network service. It first accepts exact
metadata already produced by extraction or triage, then checks the reviewed
disease vocabulary and gazetteer for exact names in the title and text.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from episignal_backend.db.types import Precision
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


@dataclass(frozen=True)
class MetadataRepairEvent:
    event_id: UUID
    country_code: str | None
    admin1: str | None
    disease_id: UUID | None
    signals: tuple[MetadataEvidence, ...]


@dataclass(frozen=True)
class EventMetadataPatch:
    country_code: str | None = None
    admin1: str | None = None
    disease_id: UUID | None = None

    @property
    def changed(self) -> bool:
        return any(value is not None for value in (self.country_code, self.admin1, self.disease_id))


def metadata_fields_from_extraction(extraction: Any) -> MetadataFields | None:
    if extraction is None:
        return None
    locations = tuple(getattr(extraction, "locations", ()) or ())
    source = next(
        (item for item in locations if item.role.value == "primary"),
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
    resolved = tuple(resolver.resolve(evidence) for evidence in event.signals)
    country_code = (
        _unique(value.country_code for value in resolved) if event.country_code is None else None
    )
    disease_id = (
        _unique(value.disease_id for value in resolved) if event.disease_id is None else None
    )
    wanted_country = event.country_code or country_code
    admin1 = None
    if event.admin1 is None and wanted_country is not None:
        admin1 = _unique(
            value.admin1
            for value in resolved
            if value.admin1 is not None and value.country_code == wanted_country
        )
    return EventMetadataPatch(country_code=country_code, admin1=admin1, disease_id=disease_id)


@dataclass(frozen=True)
class ResolvedMetadata:
    disease_id: UUID | None = None
    disease_text: str | None = None
    country_code: str | None = None
    admin1: str | None = None
    admin2: str | None = None
    place_name: str | None = None
    location_text: str | None = None

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
    """Resolve metadata with exact, reviewed local data only."""

    def __init__(
        self,
        *,
        country_aliases: Mapping[str, str],
        country_codes: Sequence[str] = (),
        diseases: Sequence[DiseaseVocabularyEntry] = (),
        admin1s: Sequence[Admin1VocabularyEntry] = (),
    ) -> None:
        aliases = {name: code for name, code in COUNTRY_CODES.items() if name != "congo"}
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

    def resolve(self, evidence: MetadataEvidence) -> ResolvedMetadata:
        sources = tuple(source for source in (evidence.extraction, evidence.triage) if source)
        disease_id = None
        disease_text = None
        for source in sources:
            if source.disease:
                disease_id = self._resolve_disease_value(source.disease)
                if disease_id is not None:
                    disease_text = source.disease
                    break
        if disease_id is None:
            disease_id, fallback_text = self._resolve_disease_in_text(
                f"{evidence.title}\n{evidence.text}"
            )
            if disease_id is not None:
                disease_text = fallback_text

        country_code = next(
            (
                code
                for source in sources
                for value in (source.country, source.location_text, source.place_name)
                if (code := self._resolve_country_value(value)) is not None
            ),
            None,
        )
        all_text = f"{evidence.title}\n{evidence.text}"
        if country_code is None:
            country_code = self._resolve_country_in_text(all_text)

        location_text = next(
            (
                value
                for source in sources
                for value in (source.location_text, source.place_name)
                if value
            ),
            None,
        )
        if location_text is None and country_code is None:
            location_text = next(
                (source.country for source in sources if source.country),
                None,
            )
        admin1_name = next(
            (
                value
                for source in sources
                for value in (source.admin1, source.location_text, source.place_name)
                if value
            ),
            None,
        )
        admin1_match = self._resolve_admin1_value(admin1_name, country_code)
        if admin1_match is None:
            admin1_match = self._resolve_admin1_in_text(all_text, country_code)
        if admin1_match is not None:
            if country_code is None:
                country_code = admin1_match.entry.country_code
            if location_text is None:
                location_text = admin1_match.matched_name

        admin2 = next((source.admin2 for source in sources if source.admin2), None)
        return ResolvedMetadata(
            disease_id=disease_id,
            disease_text=disease_text,
            country_code=country_code,
            admin1=admin1_match.entry.code if admin1_match is not None else None,
            admin2=admin2,
            place_name=location_text,
            location_text=location_text,
        )

    def _resolve_country_value(self, value: str | None) -> str | None:
        if value is None:
            return None
        code = value.strip().upper()
        if len(code) == 2 and code.isalpha() and code in self._country_codes:
            return code
        return self._country_aliases.get(normalized_form(value))

    def _resolve_country_in_text(self, text: str) -> str | None:
        normalized = normalized_form(text)
        found = {
            code
            for alias, code in self._country_aliases.items()
            if _contains_phrase(normalized, alias)
        }
        for match in re.finditer(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])", text):
            code = match.group(1)
            if code in self._country_codes:
                found.add(code)
        return next(iter(found)) if len(found) == 1 else None

    def _resolve_disease_value(self, value: str | None) -> UUID | None:
        if value is None:
            return None
        ids = self._disease_aliases.get(normalized_form(value), frozenset())
        return next(iter(ids)) if len(ids) == 1 else None

    def _resolve_disease_in_text(self, text: str) -> tuple[UUID | None, str | None]:
        normalized = normalized_form(text)
        matches: list[tuple[int, UUID]] = []
        for alias, ids in self._disease_aliases.items():
            if len(ids) == 1 and _contains_phrase(normalized, alias):
                matches.append((len(alias), next(iter(ids))))
        if not matches:
            return None, None
        best_length = max(length for length, _ in matches)
        best_ids = {disease_id for length, disease_id in matches if length == best_length}
        if len(best_ids) != 1:
            return None, None
        disease = self._diseases_by_id[next(iter(best_ids))]
        return disease.id, disease.canonical_name

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

    def _resolve_admin1_in_text(self, text: str, country_code: str | None) -> _Admin1Match | None:
        normalized = normalized_form(text)
        matches: list[tuple[int, _Admin1Match]] = []
        for entry in self._admin1s:
            if country_code is not None and entry.country_code != country_code:
                continue
            for name in (entry.name, *entry.alternate_names):
                phrase = normalized_form(name)
                if phrase and _contains_phrase(normalized, phrase):
                    matches.append((len(phrase), _Admin1Match(entry, name)))
        if not matches:
            return None
        best_length = max(length for length, _ in matches)
        unique = {
            (match.entry.country_code, match.entry.code): match
            for length, match in matches
            if length == best_length
        }
        return next(iter(unique.values())) if len(unique) == 1 else None


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _unique[T](values: Iterable[T]) -> T | None:
    found = {value for value in values if value is not None}
    return next(iter(found)) if len(found) == 1 else None

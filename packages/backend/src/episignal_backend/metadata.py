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

        structured_country = next(
            (
                code
                for source in sources
                for value in (source.country, source.location_text, source.place_name)
                if (code := self._resolve_country_value(value)) is not None
            ),
            None,
        )
        all_text = f"{evidence.title}\n{evidence.text}"
        location_text = next(
            (
                value
                for source in sources
                for value in (source.location_text, source.place_name)
                if value
            ),
            None,
        )
        if location_text is None and structured_country is None:
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
        structured_admin1 = self._resolve_admin1_value(admin1_name, None)
        text_admin1s = self._admin1_matches_in_text(all_text)
        admin1_match = structured_admin1
        if admin1_match is None and len(text_admin1s) == 1:
            admin1_match = next(iter(text_admin1s.values()))
        elif admin1_match is not None and text_admin1s:
            text_admin1_ids = set(text_admin1s)
            if text_admin1_ids != {(admin1_match.entry.country_code, admin1_match.entry.code)}:
                admin1_match = None

        text_admin1_countries = {country for country, _ in text_admin1s}
        country_codes = self._resolve_country_in_text(
            all_text,
            ignored_phrases=(
                tuple(
                    name
                    for match in text_admin1s.values()
                    for name in self._admin1_names(match.entry)
                )
                if text_admin1s
                else ()
            ),
        )
        if structured_country is not None:
            if (
                admin1_match is not None
                and structured_country != admin1_match.entry.country_code
                or text_admin1s
                and structured_country not in text_admin1_countries
            ):
                country_code = None
                admin1_match = None
            else:
                country_code = structured_country
        elif admin1_match is not None:
            if country_codes is not None and country_codes != admin1_match.entry.country_code:
                country_code = None
                admin1_match = None
            else:
                country_code = admin1_match.entry.country_code
        elif text_admin1s:
            if country_codes is not None:
                country_code = country_codes if country_codes in text_admin1_countries else None
            elif len(text_admin1_countries) == 1:
                country_code = next(iter(text_admin1_countries))
            else:
                country_code = None
        else:
            country_code = country_codes

        if admin1_match is None and country_code is not None:
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

    def _resolve_country_in_text(
        self, text: str, *, ignored_phrases: Sequence[str] = ()
    ) -> str | None:
        normalized = normalized_form(text)
        ignored_spans = tuple(
            span
            for phrase in ignored_phrases
            for span in _phrase_spans(normalized, normalized_form(phrase))
        )
        found = {
            code
            for alias, code in self._country_aliases.items()
            if any(
                not _span_is_inside(candidate, ignored_spans)
                for candidate in _phrase_spans(normalized, alias)
            )
        }
        return next(iter(found)) if len(found) == 1 else None

    def _resolve_disease_value(self, value: str | None) -> UUID | None:
        if value is None:
            return None
        ids = self._disease_aliases.get(normalized_form(value), frozenset())
        return next(iter(ids)) if len(ids) == 1 else None

    def _resolve_disease_in_text(self, text: str) -> tuple[UUID | None, str | None]:
        normalized = normalized_form(text)
        matches: set[UUID] = set()
        for alias, ids in self._disease_aliases.items():
            if len(ids) == 1 and _contains_phrase(normalized, alias):
                matches.add(next(iter(ids)))
        if len(matches) != 1:
            return None, None
        disease = self._diseases_by_id[next(iter(matches))]
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
        matches = self._admin1_matches_in_text(text, country_code=country_code)
        if len(matches) != 1:
            return None
        return next(iter(matches.values()))

    def _admin1_matches_in_text(
        self, text: str, *, country_code: str | None = None
    ) -> dict[tuple[str, str], _Admin1Match]:
        normalized = normalized_form(text)
        matches: dict[tuple[str, str], _Admin1Match] = {}
        for entry in self._admin1s:
            if country_code is not None and entry.country_code != country_code:
                continue
            names = (entry.name, *entry.alternate_names)
            matching_names = [
                name
                for name in names
                if normalized_form(name) and _contains_phrase(normalized, normalized_form(name))
            ]
            if matching_names:
                key = (entry.country_code, entry.code)
                name = max(matching_names, key=lambda value: len(normalized_form(value)))
                matches[key] = _Admin1Match(entry, name)
        return matches

    @staticmethod
    def _admin1_names(entry: Admin1VocabularyEntry) -> tuple[str, ...]:
        return (entry.name, *entry.alternate_names)


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(_phrase_spans(text, phrase))


def _phrase_spans(text: str, phrase: str) -> tuple[tuple[int, int], ...]:
    if not phrase:
        return ()
    pattern = rf"(?<![\w]){re.escape(phrase)}(?![\w])"
    return tuple((match.start(), match.end()) for match in re.finditer(pattern, text))


def _span_is_inside(span: tuple[int, int], containers: Sequence[tuple[int, int]]) -> bool:
    return any(start <= span[0] and span[1] <= end for start, end in containers)


def _unique[T](values: Iterable[T]) -> T | None:
    found = {value for value in values if value is not None}
    return next(iter(found)) if len(found) == 1 else None

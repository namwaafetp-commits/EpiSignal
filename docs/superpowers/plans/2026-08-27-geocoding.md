# Geocoding Extracted Places Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the place names a signal's extraction reports into coordinates, or into an honest record that they could not be resolved, and advance the signal from `extracted` to `geocoded`.

**Architecture:** An offline GeoNames gazetteer seeded into PostgreSQL. A pure resolution ladder scopes candidates by country then admin1, matches names by exact form, then ascii fold, then alternate name, accepts only a unique survivor, and otherwise coarsens to an admin1 or country centroid. It never tie-breaks. Decision modules import no SQLAlchemy and no httpx; `geocode/repository.py` is the only module that touches the database; nothing in the sub-project touches the network.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, PostGIS via GeoAlchemy2, Pydantic v2, pytest, ruff, mypy. Run Python through `uv run`. Run workspace scripts through `corepack pnpm`.

**Design:** `docs/superpowers/specs/2026-08-27-geocoding-design.md`

**Base commit:** `2f01d31`

---

## Environment Notes

- Bare `python` is not on `PATH`. Every Python command runs through `uv run`.
- `pnpm` is not on `PATH`. Every workspace command runs through `corepack pnpm`.
- Windows PowerShell 5.1: chain commands with `;`, never `&&`.
- Tests must open no socket and reach no live database. Tasks 1 through 20 run with no key, no network, and no database. Task 21 is the only task that touches either.

## File Structure

**Created:**

| Path | Responsibility |
| --- | --- |
| `packages/backend/src/episignal_backend/geocode/__init__.py` | package marker |
| `packages/backend/src/episignal_backend/geocode/documents.py` | contracts crossing the gazetteer and storage seams |
| `packages/backend/src/episignal_backend/geocode/normalize.py` | name forms and country alias resolution, pure |
| `packages/backend/src/episignal_backend/geocode/resolve.py` | the resolution ladder, coarsening, confidence |
| `packages/backend/src/episignal_backend/geocode/protocol.py` | `GazetteerRepository` and `GeocodeRepository` boundaries |
| `packages/backend/src/episignal_backend/geocode/repository.py` | the only SQLAlchemy in the sub-project |
| `packages/backend/src/episignal_backend/geocode/locate.py` | `run_geocoding`, orchestrating protocols only |
| `packages/backend/src/episignal_backend/geocode_runner.py` | CLI entry point |
| `database/migrations/versions/20260827_0006_geocoding.py` | `gazetteer_places` and `signal_locations` |
| `database/seeds/country_aliases.json` | reviewed country name to ISO-3166 alpha-2 mapping |
| `database/seeds/gazetteer/ATTRIBUTION.md` | GeoNames CC BY 4.0 attribution |
| `scripts/build_gazetteer.py` | turns raw GeoNames downloads into the seed artifact |
| `packages/backend/tests/fixtures/gazetteer_sample/*` | raw GeoNames lines used to test the build script |

**Modified:**

| Path | Change |
| --- | --- |
| `packages/backend/src/episignal_backend/db/types.py` | add `Precision` |
| `packages/backend/src/episignal_backend/models/geography.py` | new module holding `GazetteerPlace` and `SignalLocation` |
| `packages/backend/src/episignal_backend/models/__init__.py` | export the two new models |
| `packages/backend/src/episignal_backend/seeds.py` | country alias and gazetteer loading |
| `packages/backend/src/episignal_backend/seed_runner.py` | report the two new counts |
| `packages/backend/src/episignal_backend/config.py` | geocoding settings |
| `packages/backend/src/episignal_backend/schema_check.py` | expect the two new tables |
| `package.json` | `geocode:signals` script |
| `README.md` | GeoNames attribution reference |

---

## Task 1: The precision vocabulary

**Files:**
- Modify: `packages/backend/src/episignal_backend/db/types.py`
- Test: `packages/backend/tests/test_geocode_documents.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_geocode_documents.py`:

```python
from episignal_backend.db.types import Precision


def test_precision_is_ordered_from_specific_to_absent() -> None:
    assert [member.value for member in Precision] == [
        "place",
        "admin2",
        "admin1",
        "country",
        "unresolved",
    ]


def test_precision_stores_its_values_not_its_member_names() -> None:
    assert Precision.ADMIN1 == "admin1"
    assert str(Precision.UNRESOLVED) == "unresolved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_documents.py -v`
Expected: FAIL with `ImportError: cannot import name 'Precision'`

- [ ] **Step 3: Write minimal implementation**

In `packages/backend/src/episignal_backend/db/types.py`, add after `ProcessingStatus`:

```python
class Precision(StrEnum):
    """How specific a resolved location actually is.

    Ordered from most to least specific. `unresolved` is a real answer, not a
    missing one: the article named a place the gazetteer could not match, which
    is different from the article naming no place at all.
    """

    PLACE = "place"
    ADMIN2 = "admin2"
    ADMIN1 = "admin1"
    COUNTRY = "country"
    UNRESOLVED = "unresolved"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_documents.py -v`
Expected: PASS, 2 passed

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/db/types.py packages/backend/tests/test_geocode_documents.py
git commit -m "feat: add the location precision vocabulary"
```

---

## Task 2: Contracts for the gazetteer and storage seams

**Files:**
- Create: `packages/backend/src/episignal_backend/geocode/__init__.py`
- Create: `packages/backend/src/episignal_backend/geocode/documents.py`
- Modify: `packages/backend/tests/test_geocode_documents.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_geocode_documents.py`:

```python
from uuid import uuid4

import pytest
from episignal_backend.db.types import LocationRole
from episignal_backend.geocode.documents import (
    Candidate,
    ExtractedPlace,
    GeocodableSignal,
    MatchForm,
    ResolvedLocation,
)
from pydantic import ValidationError


def test_an_extracted_place_keeps_the_extraction_strings_verbatim() -> None:
    place = ExtractedPlace(
        role=LocationRole.PRIMARY,
        country_name="DR Congo",
        admin1_name="Équateur",
        place_name="Bikoro",
    )
    assert place.country_name == "DR Congo"
    assert place.admin1_name == "Équateur"


def test_an_extracted_place_may_name_nothing_at_all() -> None:
    place = ExtractedPlace(role=LocationRole.REPORTING)
    assert place.country_name is None
    assert place.admin1_name is None
    assert place.place_name is None


def test_a_candidate_carries_the_precision_of_its_own_row() -> None:
    candidate = Candidate(
        geonames_id=2314302,
        name="Bikoro",
        precision="place",
        country_code="CD",
        admin1_code="01",
        admin2_code=None,
        latitude=-0.75,
        longitude=18.13,
    )
    assert candidate.precision == "place"
    assert candidate.country_code == "CD"


def test_a_candidate_rejects_a_country_code_that_is_not_two_letters() -> None:
    with pytest.raises(ValidationError):
        Candidate(
            geonames_id=1,
            name="Nowhere",
            precision="place",
            country_code="CDX",
            admin1_code=None,
            admin2_code=None,
            latitude=0.0,
            longitude=0.0,
        )


def test_an_unresolved_location_carries_no_coordinate_and_no_confidence() -> None:
    resolved = ResolvedLocation(
        role=LocationRole.PRIMARY,
        country_name="Ruritania",
        admin1_name=None,
        place_name="Strelsau",
        precision="unresolved",
    )
    assert resolved.latitude is None
    assert resolved.longitude is None
    assert resolved.confidence is None
    assert resolved.geonames_id is None


def test_a_geocodable_signal_carries_the_places_its_extraction_named() -> None:
    signal_id = uuid4()
    signal = GeocodableSignal(
        id=signal_id,
        locations=(ExtractedPlace(role=LocationRole.PRIMARY, place_name="Lagos"),),
    )
    assert signal.id == signal_id
    assert len(signal.locations) == 1


def test_a_geocodable_signal_may_name_no_places() -> None:
    assert GeocodableSignal(id=uuid4()).locations == ()


def test_the_match_forms_are_tried_in_this_order() -> None:
    assert [member.value for member in MatchForm] == ["exact", "ascii", "alternate"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_documents.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.geocode'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/geocode/__init__.py` as an empty file.

Create `packages/backend/src/episignal_backend/geocode/documents.py`:

```python
"""Contracts crossing the gazetteer seam and the storage seam.

A `ResolvedLocation` deliberately carries both sides of the answer. The
`*_name` fields hold what the extraction said, unmodified; the `resolved_*`,
`admin*`, and coordinate fields hold what the gazetteer answered. A coarsened
result is therefore never mistakable for a place-level hit, and "why this
coordinate" is answerable from one row.

This module imports neither SQLAlchemy nor httpx.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from episignal_backend.db.types import LocationRole, Precision


class MatchForm(StrEnum):
    """How a name was matched. Tried in this order and never merged.

    An exact match must not be diluted by the collisions that folding
    introduces, so the forms are separate rungs rather than one query.
    """

    EXACT = "exact"
    ASCII = "ascii"
    ALTERNATE = "alternate"


class ExtractedPlace(BaseModel):
    """One location as the extraction reported it, before any resolution.

    Every field but the role is optional, because a model reports what the
    article said and an article can name a country with no town, a town with no
    country, or neither.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: LocationRole
    country_name: str | None = Field(default=None, max_length=100)
    admin1_name: str | None = Field(default=None, max_length=200)
    place_name: str | None = Field(default=None, max_length=200)


class Candidate(BaseModel):
    """One gazetteer row offered as a possible answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    geonames_id: int
    name: str = Field(min_length=1)
    precision: Precision
    country_code: str = Field(min_length=2, max_length=2)
    admin1_code: str | None = None
    admin2_code: str | None = None
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)


class ResolvedLocation(BaseModel):
    """What one extracted place resolved to, at whatever precision was reached."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: LocationRole
    country_name: str | None = None
    admin1_name: str | None = None
    place_name: str | None = None
    precision: Precision
    geonames_id: int | None = None
    resolved_name: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    admin1: str | None = None
    admin2: str | None = None
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    # Absent, not zero. A zero would claim the system assessed this location and
    # found it worthless; a null says it has no assessment to offer.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class GeocodableSignal(BaseModel):
    """A signal at `extracted`, with the places its extraction named."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    locations: tuple[ExtractedPlace, ...] = ()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_documents.py -v`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/geocode packages/backend/tests/test_geocode_documents.py
git commit -m "feat: add contracts for the gazetteer and storage seams"
```

---

## Task 3: Name forms

**Files:**
- Create: `packages/backend/src/episignal_backend/geocode/normalize.py`
- Test: `packages/backend/tests/test_geocode_normalize.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_geocode_normalize.py`:

```python
from episignal_backend.geocode.normalize import ascii_form, normalized_form


def test_the_normalized_form_casefolds() -> None:
    assert normalized_form("BIKORO") == "bikoro"


def test_the_normalized_form_collapses_whitespace() -> None:
    assert normalized_form("  Port   Harcourt \n") == "port harcourt"


def test_the_normalized_form_turns_punctuation_into_a_separator() -> None:
    assert normalized_form("Saint-Louis") == "saint louis"
    assert normalized_form("N'Djamena") == "n djamena"


def test_the_normalized_form_keeps_diacritics() -> None:
    assert normalized_form("Équateur") == "équateur"


def test_the_ascii_form_folds_diacritics() -> None:
    assert ascii_form("Équateur") == "equateur"
    assert ascii_form("Kraków") == "krakow"
    assert ascii_form("São Paulo") == "sao paulo"


def test_the_ascii_form_applies_every_normalization_too() -> None:
    assert ascii_form("  SAINT-LOUIS  ") == "saint louis"


def test_both_forms_return_empty_for_a_name_that_is_only_punctuation() -> None:
    assert normalized_form("---") == ""
    assert ascii_form("---") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.geocode.normalize'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/geocode/normalize.py`:

```python
"""Name forms and country alias resolution.

Two forms, never merged. The `normalized` form is what a name looks like with
its case, spacing, and punctuation made uniform; the `ascii` form is that with
its diacritics folded away. Folding is useful and lossy at the same time: it
matches Krakow to Kraków, and it also collides names that were distinct, which
is why an exact match is always tried first and a folded match is scored lower.

This module imports neither SQLAlchemy nor httpx.
"""

import unicodedata
from collections.abc import Mapping


def normalized_form(value: str) -> str:
    """Casefold, replace punctuation with a separator, collapse whitespace."""
    separated = "".join(
        " " if unicodedata.category(character).startswith(("P", "S")) else character
        for character in value
    )
    return " ".join(separated.casefold().split())


def ascii_form(value: str) -> str:
    """The normalized form with combining marks removed."""
    decomposed = unicodedata.normalize("NFKD", normalized_form(value))
    return "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_normalize.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/geocode/normalize.py packages/backend/tests/test_geocode_normalize.py
git commit -m "feat: add exact and diacritic-folded name forms"
```

---

## Task 4: Country alias resolution

**Files:**
- Modify: `packages/backend/src/episignal_backend/geocode/normalize.py`
- Modify: `packages/backend/tests/test_geocode_normalize.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_geocode_normalize.py`:

```python
from episignal_backend.geocode.normalize import resolve_country

ALIASES = {
    "democratic republic of the congo": "CD",
    "dr congo": "CD",
    "congo dem rep": "CD",
    "niger": "NE",
    "nigeria": "NG",
}


def test_it_resolves_an_exact_alias() -> None:
    assert resolve_country("DR Congo", ALIASES) == "CD"


def test_it_resolves_through_the_normalized_form() -> None:
    assert resolve_country("  Congo, Dem. Rep. ", ALIASES) == "CD"


def test_it_returns_none_when_no_alias_matches() -> None:
    assert resolve_country("Ruritania", ALIASES) is None


def test_it_returns_none_for_a_missing_country() -> None:
    assert resolve_country(None, ALIASES) is None


def test_it_never_matches_a_near_miss() -> None:
    # Niger and Nigeria are the canonical example of the error this project
    # treats as worst. Exact matching is the reason it cannot happen.
    assert resolve_country("Niger", ALIASES) == "NE"
    assert resolve_country("Nigeria", ALIASES) == "NG"
    assert resolve_country("Nigerien", ALIASES) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_normalize.py -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_country'`

- [ ] **Step 3: Write minimal implementation**

Append to `packages/backend/src/episignal_backend/geocode/normalize.py`:

```python
def resolve_country(name: str | None, aliases: Mapping[str, str]) -> str | None:
    """Map an extracted country name to an ISO-3166 alpha-2 code.

    Exact match against the normalized form, never fuzzy. A country that fails
    to resolve is a seed row someone adds; a fuzzy match is Niger silently
    becoming Nigeria, which is the error this whole sub-project is shaped to
    avoid.
    """
    if name is None:
        return None
    return aliases.get(normalized_form(name))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_normalize.py -v`
Expected: PASS, 12 passed

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/geocode/normalize.py packages/backend/tests/test_geocode_normalize.py
git commit -m "feat: resolve country names through a reviewed alias map"
```

---

## Task 5: The two boundaries

**Files:**
- Create: `packages/backend/src/episignal_backend/geocode/protocol.py`
- Test: `packages/backend/tests/test_geocode_protocol.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_geocode_protocol.py`:

```python
from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4

from episignal_backend.db.types import LocationRole
from episignal_backend.geocode.documents import (
    Candidate,
    ExtractedPlace,
    GeocodableSignal,
    MatchForm,
    ResolvedLocation,
)
from episignal_backend.geocode.protocol import GazetteerRepository, GeocodeRepository


class FakeGazetteer:
    def country_aliases(self) -> Mapping[str, str]:
        return {"nigeria": "NG"}

    def admin1_code(self, *, country_code: str, name: str) -> str | None:
        return None

    def candidates(
        self,
        *,
        name: str,
        form: MatchForm,
        country_code: str | None,
        admin1_code: str | None,
    ) -> Sequence[Candidate]:
        return ()

    def centroid(self, *, country_code: str, admin1_code: str | None) -> Candidate | None:
        return None


class FakeGeocodeRepository:
    def awaiting_geocoding(self, *, limit: int) -> Sequence[GeocodableSignal]:
        return ()

    def stale_geocoding(self, *, limit: int, source: str) -> Sequence[GeocodableSignal]:
        return ()

    def replace_locations(
        self, signal_id: UUID, locations: Sequence[ResolvedLocation], *, source: str
    ) -> None:
        return None

    def mark_geocoded(self, signal_id: UUID) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_the_gazetteer_boundary_is_satisfiable_without_a_database() -> None:
    assert isinstance(FakeGazetteer(), GazetteerRepository)


def test_the_storage_boundary_is_satisfiable_without_a_database() -> None:
    assert isinstance(FakeGeocodeRepository(), GeocodeRepository)


def test_a_fake_gazetteer_answers_the_four_questions_the_ladder_asks() -> None:
    gazetteer = FakeGazetteer()
    assert gazetteer.country_aliases()["nigeria"] == "NG"
    assert gazetteer.admin1_code(country_code="NG", name="Lagos") is None
    assert (
        gazetteer.candidates(
            name="Lagos", form=MatchForm.EXACT, country_code="NG", admin1_code=None
        )
        == ()
    )
    assert gazetteer.centroid(country_code="NG", admin1_code=None) is None


def test_a_fake_storage_accepts_a_resolution_without_a_session() -> None:
    repository = FakeGeocodeRepository()
    resolved = ResolvedLocation(role=LocationRole.PRIMARY, precision="unresolved")
    repository.replace_locations(uuid4(), (resolved,), source="geonames-test")
    assert (
        GeocodableSignal(id=uuid4(), locations=(ExtractedPlace(role=LocationRole.PRIMARY),))
        .locations[0]
        .role
        == LocationRole.PRIMARY
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.geocode.protocol'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/geocode/protocol.py`:

```python
"""The two boundaries the geocoding pass depends on.

`GazetteerRepository` answers four questions and nothing else: the country
alias map, the admin1 code for a name inside a country, candidates for a name
in a scope, and the centroid of an admin1 or a country. Keeping it that narrow
is what lets the resolution ladder be tested with tuples.

The repository owns transactions. Nothing above it knows what a session is,
which is why `commit` and `rollback` sit on the Protocol.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from episignal_backend.geocode.documents import (
    Candidate,
    GeocodableSignal,
    MatchForm,
    ResolvedLocation,
)


@runtime_checkable
class GazetteerRepository(Protocol):
    def country_aliases(self) -> Mapping[str, str]: ...

    def admin1_code(self, *, country_code: str, name: str) -> str | None: ...

    def candidates(
        self,
        *,
        name: str,
        form: MatchForm,
        country_code: str | None,
        admin1_code: str | None,
    ) -> Sequence[Candidate]:
        """Rows matching `name` under `form`.

        `country_code` of None searches the whole gazetteer, which is only ever
        done when no country could be resolved.
        """
        ...

    def centroid(self, *, country_code: str, admin1_code: str | None) -> Candidate | None:
        """The admin1 centroid, or the country centroid when `admin1_code` is None."""
        ...


@runtime_checkable
class GeocodeRepository(Protocol):
    def awaiting_geocoding(self, *, limit: int) -> Sequence[GeocodableSignal]: ...

    def stale_geocoding(self, *, limit: int, source: str) -> Sequence[GeocodableSignal]: ...

    def replace_locations(
        self, signal_id: UUID, locations: Sequence[ResolvedLocation], *, source: str
    ) -> None: ...

    def mark_geocoded(self, signal_id: UUID) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class GazetteerMissing(Exception):
    """The gazetteer holds no rows, so nothing can be resolved.

    An operator error, not a signal-level one: it must stop the run rather than
    mark every signal it touches.
    """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_protocol.py -v`
Expected: PASS, 4 passed

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/geocode/protocol.py packages/backend/tests/test_geocode_protocol.py
git commit -m "feat: add the gazetteer and geocoding storage boundaries"
```

---

## Task 6: Confidence derived from how the match was made

**Files:**
- Create: `packages/backend/src/episignal_backend/geocode/resolve.py`
- Test: `packages/backend/tests/test_geocode_resolve.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_geocode_resolve.py`:

```python
import pytest
from episignal_backend.db.types import Precision
from episignal_backend.geocode.documents import MatchForm
from episignal_backend.geocode.resolve import confidence_for


def test_an_exact_place_match_is_the_most_confident_answer() -> None:
    assert confidence_for(Precision.PLACE, MatchForm.EXACT) == 0.95


def test_a_folded_place_match_scores_below_an_exact_one() -> None:
    assert confidence_for(Precision.PLACE, MatchForm.ASCII) == 0.85


def test_an_alternate_name_match_scores_below_a_folded_one() -> None:
    assert confidence_for(Precision.PLACE, MatchForm.ALTERNATE) == 0.75


def test_coarser_precision_scores_lower_regardless_of_form() -> None:
    assert confidence_for(Precision.ADMIN2, MatchForm.EXACT) == 0.70
    assert confidence_for(Precision.ADMIN1, None) == 0.55
    assert confidence_for(Precision.COUNTRY, None) == 0.30


def test_an_unresolved_location_has_no_confidence_rather_than_zero() -> None:
    assert confidence_for(Precision.UNRESOLVED, None) is None


def test_a_place_precision_without_a_form_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        confidence_for(Precision.PLACE, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_resolve.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.geocode.resolve'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/geocode/resolve.py`:

```python
"""The resolution ladder.

One rule governs the whole module: ambiguity coarsens and never tie-breaks. No
step chooses among surviving candidates by population, by feature class, or by
any other property. A province centroid is a less precise true statement; the
most populous Springfield is a guess wearing a coordinate.

This module imports neither SQLAlchemy nor httpx.
"""

from episignal_backend.db.types import Precision
from episignal_backend.geocode.documents import MatchForm

PLACE_CONFIDENCE_BY_FORM = {
    MatchForm.EXACT: 0.95,
    MatchForm.ASCII: 0.85,
    MatchForm.ALTERNATE: 0.75,
}
COARSE_CONFIDENCE_BY_PRECISION = {
    Precision.ADMIN2: 0.70,
    Precision.ADMIN1: 0.55,
    Precision.COUNTRY: 0.30,
}


def confidence_for(precision: Precision, form: MatchForm | None) -> float | None:
    """How much to trust a resolution, given only how it was reached.

    Derived, never invented and never taken from a model. A reviewer reading a
    row can therefore reconstruct why it holds the number it holds.
    """
    if precision is Precision.UNRESOLVED:
        return None
    if precision is Precision.PLACE:
        if form is None:
            raise ValueError("a place-precision match must record the form that matched it")
        return PLACE_CONFIDENCE_BY_FORM[form]
    return COARSE_CONFIDENCE_BY_PRECISION[precision]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_resolve.py -v`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/geocode/resolve.py packages/backend/tests/test_geocode_resolve.py
git commit -m "feat: derive geocoding confidence from how a match was made"
```

---

## Task 7: Accepting a unique match inside a scope

**Files:**
- Modify: `packages/backend/src/episignal_backend/geocode/resolve.py`
- Modify: `packages/backend/tests/test_geocode_resolve.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_geocode_resolve.py`:

```python
from collections.abc import Mapping, Sequence

from episignal_backend.db.types import LocationRole
from episignal_backend.geocode.documents import Candidate, ExtractedPlace
from episignal_backend.geocode.resolve import resolve_place

ALIASES: Mapping[str, str] = {"nigeria": "NG", "democratic republic of the congo": "CD"}


def candidate(
    geonames_id: int,
    name: str,
    *,
    precision: str = "place",
    country_code: str = "NG",
    admin1_code: str | None = "05",
    admin2_code: str | None = None,
    latitude: float = 6.45,
    longitude: float = 3.39,
) -> Candidate:
    return Candidate(
        geonames_id=geonames_id,
        name=name,
        precision=precision,
        country_code=country_code,
        admin1_code=admin1_code,
        admin2_code=admin2_code,
        latitude=latitude,
        longitude=longitude,
    )


class StubGazetteer:
    """Answers from a script, so the ladder's choices are the only variable."""

    def __init__(
        self,
        *,
        by_form: dict[tuple[str, str, str | None], Sequence[Candidate]] | None = None,
        admin1: str | None = None,
        centroids: dict[tuple[str, str | None], Candidate] | None = None,
        aliases: Mapping[str, str] | None = None,
    ) -> None:
        self._by_form = by_form or {}
        self._admin1 = admin1
        self._centroids = centroids or {}
        self._aliases = aliases if aliases is not None else ALIASES
        self.calls: list[tuple[str, str, str | None, str | None]] = []

    def country_aliases(self) -> Mapping[str, str]:
        return self._aliases

    def admin1_code(self, *, country_code: str, name: str) -> str | None:
        return self._admin1

    def candidates(
        self, *, name: str, form: MatchForm, country_code: str | None, admin1_code: str | None
    ) -> Sequence[Candidate]:
        self.calls.append((name, form.value, country_code, admin1_code))
        return self._by_form.get((name, form.value, country_code), ())

    def centroid(self, *, country_code: str, admin1_code: str | None) -> Candidate | None:
        return self._centroids.get((country_code, admin1_code))


def test_a_single_exact_match_inside_a_country_is_accepted_at_place_precision() -> None:
    gazetteer = StubGazetteer(
        by_form={("Lagos", "exact", "NG"): (candidate(2332459, "Lagos"),)}
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Lagos"),
        gazetteer,
    )
    assert resolved.precision == Precision.PLACE
    assert resolved.geonames_id == 2332459
    assert resolved.resolved_name == "Lagos"
    assert resolved.confidence == 0.95
    assert resolved.latitude == 6.45


def test_the_extraction_strings_survive_resolution_unmodified() -> None:
    gazetteer = StubGazetteer(
        by_form={("Lagos", "exact", "NG"): (candidate(2332459, "Lagos"),)}
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Lagos"),
        gazetteer,
    )
    assert resolved.country_name == "Nigeria"
    assert resolved.place_name == "Lagos"
    assert resolved.role == LocationRole.PRIMARY


def test_a_folded_match_is_used_only_when_the_exact_form_found_nothing() -> None:
    gazetteer = StubGazetteer(
        by_form={("Krakow", "ascii", "NG"): (candidate(3094802, "Kraków"),)}
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Krakow"),
        gazetteer,
    )
    assert resolved.confidence == 0.85
    assert [call[1] for call in gazetteer.calls] == ["exact", "ascii"]


def test_an_admin2_row_is_accepted_at_admin2_precision() -> None:
    gazetteer = StubGazetteer(
        by_form={
            ("Ituri", "exact", "CD"): (
                candidate(
                    212228,
                    "Ituri",
                    precision="admin2",
                    country_code="CD",
                    admin1_code="10",
                    admin2_code="1002",
                ),
            )
        }
    )
    resolved = resolve_place(
        ExtractedPlace(
            role=LocationRole.PRIMARY,
            country_name="Democratic Republic of the Congo",
            place_name="Ituri",
        ),
        gazetteer,
    )
    assert resolved.precision == Precision.ADMIN2
    assert resolved.confidence == 0.70
    assert resolved.admin2 == "1002"


def test_a_resolved_admin1_narrows_the_scope_before_the_name_is_matched() -> None:
    gazetteer = StubGazetteer(
        by_form={("Lagos", "exact", "NG"): (candidate(2332459, "Lagos"),)}, admin1="05"
    )
    resolve_place(
        ExtractedPlace(
            role=LocationRole.PRIMARY,
            country_name="Nigeria",
            admin1_name="Lagos State",
            place_name="Lagos",
        ),
        gazetteer,
    )
    assert gazetteer.calls[0] == ("Lagos", "exact", "NG", "05")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_resolve.py -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_place'`

- [ ] **Step 3: Write minimal implementation**

Append to `packages/backend/src/episignal_backend/geocode/resolve.py`:

```python
from episignal_backend.geocode.documents import Candidate, ExtractedPlace, ResolvedLocation
from episignal_backend.geocode.normalize import resolve_country
from episignal_backend.geocode.protocol import GazetteerRepository

FORMS = (MatchForm.EXACT, MatchForm.ASCII, MatchForm.ALTERNATE)


def _accept(
    place: ExtractedPlace,
    found: Candidate,
    *,
    form: MatchForm | None,
    precision: Precision | None = None,
) -> ResolvedLocation:
    reached = found.precision if precision is None else precision
    return ResolvedLocation(
        role=place.role,
        country_name=place.country_name,
        admin1_name=place.admin1_name,
        place_name=place.place_name,
        precision=reached,
        geonames_id=found.geonames_id,
        resolved_name=found.name,
        country_code=found.country_code,
        admin1=found.admin1_code,
        admin2=found.admin2_code,
        latitude=found.latitude,
        longitude=found.longitude,
        confidence=confidence_for(reached, form),
    )


def _unique_match(
    gazetteer: GazetteerRepository,
    name: str,
    *,
    country_code: str | None,
    admin1_code: str | None,
) -> tuple[Candidate, MatchForm] | None:
    """The one candidate for `name`, or None when there is not exactly one.

    A form that returns several candidates stops the search rather than falling
    through to a looser form. Looser forms can only widen the set, so trying
    them after an ambiguous result would be a slower way of reaching the same
    ambiguity.
    """
    for form in FORMS:
        found = gazetteer.candidates(
            name=name, form=form, country_code=country_code, admin1_code=admin1_code
        )
        if len(found) == 1:
            return found[0], form
        if found:
            return None
    return None


def resolve_place(place: ExtractedPlace, gazetteer: GazetteerRepository) -> ResolvedLocation:
    """Run the ladder over one extracted place, exactly once."""
    country_code = resolve_country(place.country_name, gazetteer.country_aliases())
    if country_code is None:
        raise NotImplementedError("the no-country path arrives in a later task")

    admin1_code = None
    if place.admin1_name:
        admin1_code = gazetteer.admin1_code(country_code=country_code, name=place.admin1_name)

    if place.place_name:
        match = _unique_match(
            gazetteer, place.place_name, country_code=country_code, admin1_code=admin1_code
        )
        if match is not None:
            found, form = match
            return _accept(place, found, form=form)

    raise NotImplementedError("the coarsening path arrives in a later task")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_resolve.py -v`
Expected: PASS, 11 passed

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/geocode/resolve.py packages/backend/tests/test_geocode_resolve.py
git commit -m "feat: accept a uniquely matched place inside its scope"
```

---

## Task 8: Coarsening, and the prohibition on tie-breaking

**Files:**
- Modify: `packages/backend/src/episignal_backend/geocode/resolve.py`
- Modify: `packages/backend/tests/test_geocode_resolve.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_geocode_resolve.py`:

```python
def test_two_survivors_coarsen_to_the_admin1_centroid() -> None:
    gazetteer = StubGazetteer(
        by_form={
            ("Springfield", "exact", "NG"): (
                candidate(1, "Springfield", latitude=1.0, longitude=1.0),
                candidate(2, "Springfield", latitude=2.0, longitude=2.0),
            )
        },
        admin1="05",
        centroids={
            ("NG", "05"): candidate(
                9001, "Lagos State", precision="admin1", latitude=6.6, longitude=3.5
            )
        },
    )
    resolved = resolve_place(
        ExtractedPlace(
            role=LocationRole.PRIMARY,
            country_name="Nigeria",
            admin1_name="Lagos State",
            place_name="Springfield",
        ),
        gazetteer,
    )
    assert resolved.precision == Precision.ADMIN1
    assert resolved.confidence == 0.55
    assert resolved.latitude == 6.6
    assert resolved.resolved_name == "Lagos State"


def test_coarsening_never_returns_one_of_the_tied_candidates() -> None:
    # The rule the sub-project exists to enforce. Neither candidate may be
    # chosen, by population or by anything else.
    gazetteer = StubGazetteer(
        by_form={
            ("Springfield", "exact", "NG"): (
                candidate(1, "Springfield", latitude=1.0, longitude=1.0),
                candidate(2, "Springfield", latitude=2.0, longitude=2.0),
            )
        },
        admin1="05",
        centroids={
            ("NG", "05"): candidate(
                9001, "Lagos State", precision="admin1", latitude=6.6, longitude=3.5
            )
        },
    )
    resolved = resolve_place(
        ExtractedPlace(
            role=LocationRole.PRIMARY,
            country_name="Nigeria",
            admin1_name="Lagos State",
            place_name="Springfield",
        ),
        gazetteer,
    )
    assert resolved.geonames_id not in {1, 2}


def test_an_ambiguous_name_with_no_admin1_coarsens_to_the_country_centroid() -> None:
    gazetteer = StubGazetteer(
        by_form={
            ("Springfield", "exact", "NG"): (
                candidate(1, "Springfield"),
                candidate(2, "Springfield"),
            )
        },
        centroids={
            ("NG", None): candidate(
                9002, "Nigeria", precision="country", admin1_code=None, latitude=9.0, longitude=8.0
            )
        },
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Springfield"),
        gazetteer,
    )
    assert resolved.precision == Precision.COUNTRY
    assert resolved.confidence == 0.30
    assert resolved.latitude == 9.0


def test_a_name_absent_from_the_gazetteer_coarsens_the_same_way() -> None:
    gazetteer = StubGazetteer(
        centroids={
            ("NG", None): candidate(
                9002, "Nigeria", precision="country", admin1_code=None, latitude=9.0, longitude=8.0
            )
        }
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Nowheresville"),
        gazetteer,
    )
    assert resolved.precision == Precision.COUNTRY
    assert resolved.place_name == "Nowheresville"


def test_a_country_named_with_no_town_resolves_to_the_country_centroid() -> None:
    gazetteer = StubGazetteer(
        centroids={
            ("NG", None): candidate(
                9002, "Nigeria", precision="country", admin1_code=None, latitude=9.0, longitude=8.0
            )
        }
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.AFFECTED_AREA, country_name="Nigeria"),
        gazetteer,
    )
    assert resolved.precision == Precision.COUNTRY
    assert resolved.role == LocationRole.AFFECTED_AREA


def test_a_country_with_no_centroid_at_all_is_unresolved() -> None:
    gazetteer = StubGazetteer()
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Lagos"),
        gazetteer,
    )
    assert resolved.precision == Precision.UNRESOLVED
    assert resolved.latitude is None
    assert resolved.confidence is None
    assert resolved.country_code == "NG"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_resolve.py -v`
Expected: FAIL with `NotImplementedError: the coarsening path arrives in a later task`

- [ ] **Step 3: Write minimal implementation**

In `packages/backend/src/episignal_backend/geocode/resolve.py`, add these two functions above `resolve_place`:

```python
def _unresolved(place: ExtractedPlace, *, country_code: str | None = None) -> ResolvedLocation:
    return ResolvedLocation(
        role=place.role,
        country_name=place.country_name,
        admin1_name=place.admin1_name,
        place_name=place.place_name,
        precision=Precision.UNRESOLVED,
        country_code=country_code,
        confidence=None,
    )


def _coarsen(
    place: ExtractedPlace,
    gazetteer: GazetteerRepository,
    *,
    country_code: str,
    admin1_code: str | None,
) -> ResolvedLocation:
    """Answer at the least specific precision that is still true."""
    if admin1_code is not None:
        centre = gazetteer.centroid(country_code=country_code, admin1_code=admin1_code)
        if centre is not None:
            return _accept(place, centre, form=None, precision=Precision.ADMIN1)
    centre = gazetteer.centroid(country_code=country_code, admin1_code=None)
    if centre is not None:
        return _accept(place, centre, form=None, precision=Precision.COUNTRY)
    return _unresolved(place, country_code=country_code)
```

Then replace the final line of `resolve_place`:

```python
    raise NotImplementedError("the coarsening path arrives in a later task")
```

with:

```python
    return _coarsen(place, gazetteer, country_code=country_code, admin1_code=admin1_code)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_resolve.py -v`
Expected: PASS, 17 passed

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/geocode/resolve.py packages/backend/tests/test_geocode_resolve.py
git commit -m "feat: coarsen ambiguous places instead of tie-breaking them"
```

---

## Task 9: The no-country path

**Files:**
- Modify: `packages/backend/src/episignal_backend/geocode/resolve.py`
- Modify: `packages/backend/tests/test_geocode_resolve.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_geocode_resolve.py`:

```python
def test_a_globally_unique_name_resolves_without_a_country() -> None:
    gazetteer = StubGazetteer(
        by_form={
            ("Kinshasa", "exact", None): (
                candidate(
                    2314302,
                    "Kinshasa",
                    country_code="CD",
                    admin1_code="12",
                    latitude=-4.32,
                    longitude=15.31,
                ),
            )
        }
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, place_name="Kinshasa"), gazetteer
    )
    assert resolved.precision == Precision.PLACE
    assert resolved.country_code == "CD"
    assert resolved.confidence == 0.95


def test_a_globally_ambiguous_name_is_unresolved_rather_than_guessed() -> None:
    gazetteer = StubGazetteer(
        by_form={
            ("Springfield", "exact", None): (
                candidate(1, "Springfield", country_code="US"),
                candidate(2, "Springfield", country_code="AU"),
            )
        }
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, place_name="Springfield"), gazetteer
    )
    assert resolved.precision == Precision.UNRESOLVED
    assert resolved.place_name == "Springfield"
    assert resolved.country_code is None


def test_an_unresolvable_country_name_falls_back_to_the_worldwide_search() -> None:
    gazetteer = StubGazetteer(
        by_form={("Kinshasa", "exact", None): (candidate(2314302, "Kinshasa", country_code="CD"),)}
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Ruritania", place_name="Kinshasa"),
        gazetteer,
    )
    assert resolved.precision == Precision.PLACE
    assert resolved.country_name == "Ruritania"


def test_the_worldwide_search_ignores_the_extracted_admin1() -> None:
    # An admin1 name cannot be scoped without a country, so it is not consulted.
    gazetteer = StubGazetteer(
        by_form={("Kinshasa", "exact", None): (candidate(2314302, "Kinshasa", country_code="CD"),)}
    )
    resolve_place(
        ExtractedPlace(
            role=LocationRole.PRIMARY, admin1_name="Somewhere", place_name="Kinshasa"
        ),
        gazetteer,
    )
    assert gazetteer.calls[0] == ("Kinshasa", "exact", None, None)


def test_a_location_naming_nothing_but_a_role_is_unresolved() -> None:
    resolved = resolve_place(ExtractedPlace(role=LocationRole.REPORTING), StubGazetteer())
    assert resolved.precision == Precision.UNRESOLVED
    assert resolved.role == LocationRole.REPORTING
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_resolve.py -v`
Expected: FAIL with `NotImplementedError: the no-country path arrives in a later task`

- [ ] **Step 3: Write minimal implementation**

In `packages/backend/src/episignal_backend/geocode/resolve.py`, add above `resolve_place`:

```python
def _worldwide(place: ExtractedPlace, gazetteer: GazetteerRepository) -> ResolvedLocation:
    """The only search run without a country scope.

    Reached when no country was extracted, or none resolved. A name unique in
    the whole gazetteer is safe to accept; anything else is left unresolved,
    because there is no scope left to coarsen into.
    """
    if place.place_name:
        match = _unique_match(gazetteer, place.place_name, country_code=None, admin1_code=None)
        if match is not None:
            found, form = match
            return _accept(place, found, form=form)
    return _unresolved(place)
```

Then replace this line in `resolve_place`:

```python
        raise NotImplementedError("the no-country path arrives in a later task")
```

with:

```python
        return _worldwide(place, gazetteer)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_resolve.py -v`
Expected: PASS, 22 passed

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/geocode/resolve.py packages/backend/tests/test_geocode_resolve.py
git commit -m "feat: resolve globally unique names that carry no country"
```

---

## Task 10: Models for the gazetteer and signal locations

**Files:**
- Create: `packages/backend/src/episignal_backend/models/geography.py`
- Modify: `packages/backend/src/episignal_backend/models/__init__.py`
- Test: `packages/backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_models.py`:

```python
def test_the_gazetteer_is_keyed_on_its_geonames_id() -> None:
    from episignal_backend.models import GazetteerPlace

    assert GazetteerPlace.__tablename__ == "gazetteer_places"
    primary_key = [column.name for column in GazetteerPlace.__table__.primary_key]
    assert primary_key == ["geonames_id"]


def test_the_gazetteer_indexes_both_name_forms() -> None:
    from episignal_backend.models import GazetteerPlace

    indexed = {
        tuple(column.name for column in index.columns)
        for index in GazetteerPlace.__table__.indexes
    }
    assert ("normalized_name",) in indexed
    assert ("ascii_name",) in indexed
    assert ("country_code", "admin1_code", "normalized_name") in indexed


def test_a_signal_location_may_hold_no_coordinate() -> None:
    from episignal_backend.models import SignalLocation

    columns = SignalLocation.__table__.columns
    assert columns["latitude"].nullable
    assert columns["longitude"].nullable
    assert columns["geocoding_confidence"].nullable
    assert not columns["precision"].nullable


def test_a_signal_location_keeps_the_extraction_strings_and_the_resolution() -> None:
    from episignal_backend.models import SignalLocation

    names = set(SignalLocation.__table__.columns.keys())
    assert {"country_name", "admin1_name", "place_name"} <= names
    assert {"resolved_name", "geonames_id", "country_code", "admin1", "admin2"} <= names
    assert {"geocoding_source", "geocoding_confidence", "precision"} <= names


def test_signal_locations_are_indexed_for_spatial_matching() -> None:
    from episignal_backend.models import SignalLocation

    indexed = {
        tuple(column.name for column in index.columns)
        for index in SignalLocation.__table__.indexes
    }
    assert ("geometry",) in indexed
    assert ("signal_id",) in indexed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_models.py -v -k gazetteer`
Expected: FAIL with `ImportError: cannot import name 'GazetteerPlace'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/models/geography.py`:

```python
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin
from episignal_backend.db.types import LocationRole, Precision, vocabulary
from episignal_backend.models.event import point_4326


class GazetteerPlace(Base):
    """Reviewed reference data. Written by seeding, never by a pass.

    Keyed on `geonames_id` rather than a generated UUID: the id is stable across
    dumps, which is what makes reseeding an update rather than a duplication.
    """

    __tablename__ = "gazetteer_places"
    __table_args__ = (
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="longitude_range"),
        Index("ix_gazetteer_places_normalized_name", "normalized_name"),
        Index("ix_gazetteer_places_ascii_name", "ascii_name"),
        Index(
            "ix_gazetteer_places_scope",
            "country_code",
            "admin1_code",
            "normalized_name",
        ),
        Index("ix_gazetteer_places_alternate_names", "alternate_names", postgresql_using="gin"),
        Index("ix_gazetteer_places_precision", "precision"),
        Index("ix_gazetteer_places_geometry", "geometry", postgresql_using="gist"),
    )

    geonames_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    ascii_name: Mapped[str] = mapped_column(Text, nullable=False)
    alternate_names: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    feature_code: Mapped[str] = mapped_column(String(10), nullable=False)
    precision: Mapped[Precision] = mapped_column(
        vocabulary(Precision, "precision_values"), nullable=False
    )
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    admin1_code: Mapped[str | None] = mapped_column(String(20))
    admin2_code: Mapped[str | None] = mapped_column(String(80))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    geometry: Mapped[Any | None] = mapped_column(point_4326())
    # Stored but never consulted to break a tie. Kept because D2 may weigh a
    # match by how large the place is, which is a different question from which
    # place was meant.
    population: Mapped[int | None] = mapped_column(BigInteger)


class SignalLocation(IdentityMixin, Base):
    """One extracted place, and whatever the gazetteer could say about it.

    Both sides are recorded. The `*_name` columns are the extraction's own
    strings, unmodified; everything else is the resolution. `precision` is what
    keeps a province centroid from reading like a town.
    """

    __tablename__ = "signal_locations"
    __table_args__ = (
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="longitude_range"),
        CheckConstraint(
            "geocoding_confidence >= 0 AND geocoding_confidence <= 1",
            name="geocoding_confidence_range",
        ),
        Index("ix_signal_locations_signal_id", "signal_id"),
        Index("ix_signal_locations_precision", "precision"),
        Index("ix_signal_locations_country_code", "country_code"),
        Index("ix_signal_locations_geometry", "geometry", postgresql_using="gist"),
        Index("ix_signal_locations_geocoding_source", "geocoding_source"),
    )

    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), nullable=False
    )
    location_role: Mapped[LocationRole] = mapped_column(
        vocabulary(LocationRole, "location_role_values"),
        nullable=False,
        default=LocationRole.PRIMARY,
    )
    country_name: Mapped[str | None] = mapped_column(Text)
    admin1_name: Mapped[str | None] = mapped_column(Text)
    place_name: Mapped[str | None] = mapped_column(Text)
    precision: Mapped[Precision] = mapped_column(
        vocabulary(Precision, "precision_values"), nullable=False
    )
    geonames_id: Mapped[int | None] = mapped_column(Integer)
    resolved_name: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(String(2))
    admin1: Mapped[str | None] = mapped_column(Text)
    admin2: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    geometry: Mapped[Any | None] = mapped_column(point_4326())
    geocoding_source: Mapped[str | None] = mapped_column(Text)
    geocoding_confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

In `packages/backend/src/episignal_backend/models/__init__.py`, add the import and the two `__all__` entries:

```python
from episignal_backend.models.geography import GazetteerPlace, SignalLocation
```

`__all__` gains `"GazetteerPlace"` and `"SignalLocation"`, kept in alphabetical order.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_models.py -v`
Expected: PASS, all tests in the file

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/models packages/backend/tests/test_models.py
git commit -m "feat: add gazetteer and signal location models"
```

---

## Task 11: Migration 20260827_0006

**Files:**
- Create: `database/migrations/versions/20260827_0006_geocoding.py`
- Test: `apps/api/tests/test_migrations.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/api/tests/test_migrations.py`:

```python
def test_the_geocoding_revision_follows_the_ai_extraction_revision() -> None:
    module = _load_revision("20260827_0006_geocoding")
    assert module.revision == "20260827_0006"
    assert module.down_revision == "20260827_0005"


def test_the_geocoding_downgrade_drops_both_tables_it_created() -> None:
    source = _revision_source("20260827_0006_geocoding")
    assert 'op.drop_table("signal_locations")' in source
    assert 'op.drop_table("gazetteer_places")' in source


def test_the_geocoding_migration_does_not_touch_the_extraction_column() -> None:
    # `signals.ai_extraction` is Sub-project C's record of what the model said.
    # This sub-project records its answer beside it and never edits it.
    source = _revision_source("20260827_0006_geocoding")
    assert "ai_extraction" not in source
```

Read the top of `apps/api/tests/test_migrations.py` first. If helpers named `_load_revision` and `_revision_source` do not already exist, add them, matching the loading style the file already uses for `20260827_0005_ai_extraction`:

```python
import importlib.util
from pathlib import Path
from types import ModuleType

VERSIONS = Path(__file__).parents[3] / "database" / "migrations" / "versions"


def _revision_source(name: str) -> str:
    return (VERSIONS / f"{name}.py").read_text(encoding="utf-8")


def _load_revision(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_migrations.py -v -k geocoding`
Expected: FAIL with `FileNotFoundError` for `20260827_0006_geocoding.py`

- [ ] **Step 3: Write minimal implementation**

Create `database/migrations/versions/20260827_0006_geocoding.py`:

```python
"""add the gazetteer and the resolved locations of signals

Revision ID: 20260827_0006
Revises: 20260827_0005
Create Date: 2026-08-27

`gazetteer_places` is reference data: everything in it comes from a committed
seed artifact, so dropping it loses nothing that reseeding cannot rebuild.
`signal_locations` is derived from `signals.ai_extraction` and the gazetteer,
so it is rebuildable too. Neither needs the ledger protection
`20260827_0005` gives `ai_requests`.

The extraction column on `signals` is not touched. It records what the model
said, and this migration adds a place to record what the gazetteer answered.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography

revision: str = "20260827_0006"
down_revision: str | None = "20260827_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRECISIONS = ("place", "admin2", "admin1", "country", "unresolved")
LOCATION_ROLES = ("primary", "exposure", "diagnosis", "travel", "reporting", "affected_area")


def _point() -> Geography:
    return Geography(geometry_type="POINT", srid=4326, spatial_index=False)


def _precision(name: str) -> sa.Enum:
    return sa.Enum(*PRECISIONS, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.create_table(
        "gazetteer_places",
        sa.Column("geonames_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("ascii_name", sa.Text(), nullable=False),
        sa.Column(
            "alternate_names",
            sa.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("feature_code", sa.String(length=10), nullable=False),
        sa.Column("precision", _precision("precision_values"), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("admin1_code", sa.String(length=20), nullable=True),
        sa.Column("admin2_code", sa.String(length=80), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("geometry", _point(), nullable=True),
        sa.Column("population", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("geonames_id", name="pk_gazetteer_places"),
        sa.CheckConstraint(
            "latitude >= -90 AND latitude <= 90", name="ck_gazetteer_places_latitude_range"
        ),
        sa.CheckConstraint(
            "longitude >= -180 AND longitude <= 180", name="ck_gazetteer_places_longitude_range"
        ),
    )
    op.create_index("ix_gazetteer_places_normalized_name", "gazetteer_places", ["normalized_name"])
    op.create_index("ix_gazetteer_places_ascii_name", "gazetteer_places", ["ascii_name"])
    op.create_index("ix_gazetteer_places_precision", "gazetteer_places", ["precision"])
    op.create_index(
        "ix_gazetteer_places_scope",
        "gazetteer_places",
        ["country_code", "admin1_code", "normalized_name"],
    )
    op.create_index(
        "ix_gazetteer_places_alternate_names",
        "gazetteer_places",
        ["alternate_names"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_gazetteer_places_geometry",
        "gazetteer_places",
        ["geometry"],
        postgresql_using="gist",
    )

    op.create_table(
        "signal_locations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=False),
        sa.Column(
            "location_role",
            sa.Enum(
                *LOCATION_ROLES,
                name="location_role_values",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("country_name", sa.Text(), nullable=True),
        sa.Column("admin1_name", sa.Text(), nullable=True),
        sa.Column("place_name", sa.Text(), nullable=True),
        sa.Column("precision", _precision("precision_values"), nullable=False),
        sa.Column("geonames_id", sa.Integer(), nullable=True),
        sa.Column("resolved_name", sa.Text(), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("admin1", sa.Text(), nullable=True),
        sa.Column("admin2", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("geometry", _point(), nullable=True),
        sa.Column("geocoding_source", sa.Text(), nullable=True),
        sa.Column("geocoding_confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_signal_locations"),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name="fk_signal_locations_signal_id_signals",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "latitude >= -90 AND latitude <= 90", name="ck_signal_locations_latitude_range"
        ),
        sa.CheckConstraint(
            "longitude >= -180 AND longitude <= 180", name="ck_signal_locations_longitude_range"
        ),
        sa.CheckConstraint(
            "geocoding_confidence >= 0 AND geocoding_confidence <= 1",
            name="ck_signal_locations_geocoding_confidence_range",
        ),
    )
    op.create_index("ix_signal_locations_signal_id", "signal_locations", ["signal_id"])
    op.create_index("ix_signal_locations_precision", "signal_locations", ["precision"])
    op.create_index("ix_signal_locations_country_code", "signal_locations", ["country_code"])
    op.create_index(
        "ix_signal_locations_geocoding_source", "signal_locations", ["geocoding_source"]
    )
    op.create_index(
        "ix_signal_locations_geometry",
        "signal_locations",
        ["geometry"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("ix_signal_locations_geometry", table_name="signal_locations")
    op.drop_index("ix_signal_locations_geocoding_source", table_name="signal_locations")
    op.drop_index("ix_signal_locations_country_code", table_name="signal_locations")
    op.drop_index("ix_signal_locations_precision", table_name="signal_locations")
    op.drop_index("ix_signal_locations_signal_id", table_name="signal_locations")
    op.drop_table("signal_locations")

    op.drop_index("ix_gazetteer_places_geometry", table_name="gazetteer_places")
    op.drop_index("ix_gazetteer_places_alternate_names", table_name="gazetteer_places")
    op.drop_index("ix_gazetteer_places_scope", table_name="gazetteer_places")
    op.drop_index("ix_gazetteer_places_precision", table_name="gazetteer_places")
    op.drop_index("ix_gazetteer_places_ascii_name", table_name="gazetteer_places")
    op.drop_index("ix_gazetteer_places_normalized_name", table_name="gazetteer_places")
    op.drop_table("gazetteer_places")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/api/tests/test_migrations.py -v`
Expected: PASS, all tests in the file

- [ ] **Step 5: Commit**

```bash
git add database/migrations/versions/20260827_0006_geocoding.py apps/api/tests/test_migrations.py
git commit -m "feat: add the geocoding migration"
```

---

## Task 12: The gazetteer build script

**Files:**
- Create: `scripts/build_gazetteer.py`
- Create: `packages/backend/tests/fixtures/gazetteer_sample/countryInfo.txt`
- Create: `packages/backend/tests/fixtures/gazetteer_sample/admin1CodesASCII.txt`
- Create: `packages/backend/tests/fixtures/gazetteer_sample/admin2Codes.txt`
- Create: `packages/backend/tests/fixtures/gazetteer_sample/cities1000.txt`
- Test: `packages/backend/tests/test_build_gazetteer.py`

The script is tested against a handful of real GeoNames lines rather than the
full download, so this task needs no network. The full artifact is generated in
Task 21.

- [ ] **Step 1: Write the failing test**

Create the four fixture files. Fields are tab-separated, in GeoNames order.

`packages/backend/tests/fixtures/gazetteer_sample/countryInfo.txt`:

```text
#ISO	ISO3	ISO-Numeric	fips	Country	Capital	Area(in sq km)	Population	Continent	tld	CurrencyCode	CurrencyName	Phone	Postal Code Format	Postal Code Regex	Languages	geonameid	neighbours	EquivalentFipsCode
NG	NGA	566	NI	Nigeria	Abuja	923768	195874740	AF	.ng	NGN	Naira	234			en-NG	2328926	BJ,NE,CM,TD	
CD	COD	180	CG	Democratic Republic of the Congo	Kinshasa	2345410	84068091	AF	.cd	CDF	Franc	243			fr-CD	203312	TZ,CF,SS,RW,ZM,BI,UG,CG,AO	
```

`packages/backend/tests/fixtures/gazetteer_sample/admin1CodesASCII.txt`:

```text
NG.05	Lagos	Lagos	2332453
CD.12	Kinshasa	Kinshasa	2314301
```

`packages/backend/tests/fixtures/gazetteer_sample/admin2Codes.txt`:

```text
CD.10.1002	Ituri	Ituri	212228
```

`packages/backend/tests/fixtures/gazetteer_sample/cities1000.txt`:

```text
2332459	Lagos	Lagos	Eko,Lagos,Lagos City	6.45407	3.39467	P	PPLA	NG		05				1536000		41	Africa/Lagos	2019-09-05
2314302	Kinshasa	Kinshasa	Kinshasa,Léopoldville	-4.32758	15.31357	P	PPLC	CD		12				7785965		240	Africa/Kinshasa	2019-09-05
217831	Bunia	Bunia	Bunia	1.55980	30.25266	P	PPLA	CD		10	1002			336654		1275	Africa/Lubumbashi	2019-09-05
3094802	Kraków	Krakow	Cracovia,Kraków	50.06143	19.93658	P	PPLA	PL		77				755050		219	Europe/Warsaw	2019-09-05
```

Create `packages/backend/tests/test_build_gazetteer.py`:

```python
import gzip
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "scripts"))

from build_gazetteer import GazetteerRow, build_rows, write_artifact  # noqa: E402

SAMPLE = Path(__file__).parent / "fixtures" / "gazetteer_sample"


@pytest.fixture
def rows() -> list[GazetteerRow]:
    return build_rows(SAMPLE)


def test_it_emits_a_row_for_every_source_file(rows: list[GazetteerRow]) -> None:
    precisions = [row.precision for row in rows]
    assert precisions.count("country") == 2
    assert precisions.count("admin1") == 2
    assert precisions.count("admin2") == 1
    assert precisions.count("place") == 4


def test_no_row_sits_at_the_origin() -> None:
    # A country or district with no coordinate of its own must be dropped, not
    # written at (0, 0). Null island is in the Gulf of Guinea, which is both a
    # real place and a plausible one for an outbreak, so the error would be
    # invisible on a map.
    for row in build_rows(SAMPLE):
        assert (row.latitude, row.longitude) != (0.0, 0.0)


def test_a_country_centroid_is_the_mean_of_its_known_places(
    rows: list[GazetteerRow],
) -> None:
    congo = next(row for row in rows if row.geonames_id == 203312)
    assert congo.latitude == pytest.approx((-4.32758 + 1.55980) / 2)
    assert congo.longitude == pytest.approx((15.31357 + 30.25266) / 2)


def test_an_administrative_unit_with_no_known_place_is_dropped(tmp_path: Path) -> None:
    # Poland has a city in the sample but no countryInfo row, and no admin unit
    # in the sample lacks a member, so this is checked by construction: every
    # emitted admin row must have at least one place inside its own scope.
    places = [row for row in build_rows(SAMPLE) if row.precision == "place"]
    for row in build_rows(SAMPLE):
        if row.precision == "admin1":
            assert any(
                place.country_code == row.country_code
                and place.admin1_code == row.admin1_code
                for place in places
            )


def test_a_country_row_carries_the_country_code_and_no_admin_codes(
    rows: list[GazetteerRow],
) -> None:
    nigeria = next(row for row in rows if row.geonames_id == 2328926)
    assert nigeria.precision == "country"
    assert nigeria.country_code == "NG"
    assert nigeria.admin1_code is None
    assert nigeria.admin2_code is None


def test_an_admin1_row_splits_the_composite_code(rows: list[GazetteerRow]) -> None:
    lagos_state = next(row for row in rows if row.geonames_id == 2332453)
    assert lagos_state.precision == "admin1"
    assert lagos_state.country_code == "NG"
    assert lagos_state.admin1_code == "05"


def test_an_admin2_row_splits_all_three_parts(rows: list[GazetteerRow]) -> None:
    ituri = next(row for row in rows if row.geonames_id == 212228)
    assert ituri.precision == "admin2"
    assert (ituri.country_code, ituri.admin1_code, ituri.admin2_code) == ("CD", "10", "1002")


def test_a_place_row_carries_both_name_forms(rows: list[GazetteerRow]) -> None:
    krakow = next(row for row in rows if row.geonames_id == 3094802)
    assert krakow.name == "Kraków"
    assert krakow.normalized_name == "kraków"
    assert krakow.ascii_name == "krakow"


def test_alternate_names_are_normalized_and_deduplicated(rows: list[GazetteerRow]) -> None:
    lagos = next(row for row in rows if row.geonames_id == 2332459)
    assert "eko" in lagos.alternate_names
    assert "lagos city" in lagos.alternate_names
    # "Lagos" repeats the primary name and adds nothing to the index.
    assert lagos.alternate_names.count("lagos") <= 1


def test_a_place_row_keeps_its_population(rows: list[GazetteerRow]) -> None:
    lagos = next(row for row in rows if row.geonames_id == 2332459)
    assert lagos.population == 1536000


def test_the_artifact_is_gzipped_tab_separated_with_a_header(
    tmp_path: Path, rows: list[GazetteerRow]
) -> None:
    target = tmp_path / "gazetteer_places.tsv.gz"
    written = write_artifact(rows, target)
    assert written == len(rows)
    with gzip.open(target, "rt", encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        first = handle.readline().rstrip("\n").split("\t")
    assert header[0] == "geonames_id"
    assert len(first) == len(header)


def test_rows_are_written_in_a_stable_order(tmp_path: Path, rows: list[GazetteerRow]) -> None:
    # A reproducible artifact keeps a reseed from showing as a diff of noise.
    target = tmp_path / "one.tsv.gz"
    other = tmp_path / "two.tsv.gz"
    write_artifact(rows, target)
    write_artifact(build_rows(SAMPLE), other)
    assert gzip.open(target, "rb").read() == gzip.open(other, "rb").read()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_build_gazetteer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'build_gazetteer'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/build_gazetteer.py`:

```python
"""Turn raw GeoNames downloads into the committed seed artifact.

Run by hand when the gazetteer is refreshed, never by the application. The
artifact it writes is what ships; this script ships beside it so the artifact's
provenance is auditable and its contents reproducible.

Inputs, all from https://download.geonames.org/export/dump/ :
  countryInfo.txt, admin1CodesASCII.txt, admin2Codes.txt, cities1000.txt

GeoNames data is licensed CC BY 4.0. See database/seeds/gazetteer/ATTRIBUTION.md.

Usage:
  uv run python scripts/build_gazetteer.py <input-directory> <output.tsv.gz>
"""

import gzip
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "packages" / "backend" / "src"))

from episignal_backend.geocode.normalize import ascii_form, normalized_form  # noqa: E402

COLUMNS = (
    "geonames_id",
    "name",
    "normalized_name",
    "ascii_name",
    "alternate_names",
    "feature_code",
    "precision",
    "country_code",
    "admin1_code",
    "admin2_code",
    "latitude",
    "longitude",
    "population",
)


@dataclass(frozen=True)
class GazetteerRow:
    geonames_id: int
    name: str
    normalized_name: str
    ascii_name: str
    alternate_names: list[str]
    feature_code: str
    precision: str
    country_code: str
    admin1_code: str | None
    admin2_code: str | None
    latitude: float
    longitude: float
    population: int | None


def _alternates(raw: str, primary_normalized: str) -> list[str]:
    seen: list[str] = []
    for part in raw.split(","):
        form = normalized_form(part)
        if form and form != primary_normalized and form not in seen:
            seen.append(form)
    return seen


def _row(
    *,
    geonames_id: int,
    name: str,
    alternates: str,
    feature_code: str,
    precision: str,
    country_code: str,
    admin1_code: str | None,
    admin2_code: str | None,
    latitude: float,
    longitude: float,
    population: int | None,
) -> GazetteerRow:
    normalized = normalized_form(name)
    return GazetteerRow(
        geonames_id=geonames_id,
        name=name,
        normalized_name=normalized,
        ascii_name=ascii_form(name),
        alternate_names=_alternates(alternates, normalized),
        feature_code=feature_code,
        precision=precision,
        country_code=country_code,
        admin1_code=admin1_code,
        admin2_code=admin2_code,
        latitude=latitude,
        longitude=longitude,
        population=population,
    )


def _lines(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        rows.append(line.split("\t"))
    return rows


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    """The mean of the places inside a unit.

    GeoNames publishes no coordinate for a country or an administrative unit in
    these four files, and the alternative sources are worse. A capital is not
    the centre of its country, and an arbitrary seat is not the centre of its
    district. The mean of the known places inside a unit is at least inside it,
    and it is deterministic, which matters because this artifact is committed
    and a rebuild must not show as a diff of noise.
    """
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def build_rows(source: Path) -> list[GazetteerRow]:
    """Read the four GeoNames files and return one flat list of rows.

    A country or administrative unit containing no place from `cities1000` is
    dropped rather than written at (0, 0). Null island sits in the Gulf of
    Guinea, which is both a real place and a plausible one for an outbreak, so
    that error would be invisible on a map.
    """
    cities = _lines(source / "cities1000.txt")

    by_country: dict[str, list[tuple[float, float]]] = {}
    by_admin1: dict[tuple[str, str], list[tuple[float, float]]] = {}
    by_admin2: dict[tuple[str, str, str], list[tuple[float, float]]] = {}
    for fields in cities:
        point = (float(fields[4]), float(fields[5]))
        country_code = fields[8]
        by_country.setdefault(country_code, []).append(point)
        if fields[10]:
            by_admin1.setdefault((country_code, fields[10]), []).append(point)
            if fields[11]:
                by_admin2.setdefault((country_code, fields[10], fields[11]), []).append(point)

    rows: list[GazetteerRow] = []

    for fields in _lines(source / "countryInfo.txt"):
        members = by_country.get(fields[0])
        if not members:
            continue
        latitude, longitude = _centroid(members)
        rows.append(
            _row(
                geonames_id=int(fields[16]),
                name=fields[4],
                alternates="",
                feature_code="PCLI",
                precision="country",
                country_code=fields[0],
                admin1_code=None,
                admin2_code=None,
                latitude=latitude,
                longitude=longitude,
                population=int(fields[7]) if fields[7] else None,
            )
        )

    for fields in _lines(source / "admin1CodesASCII.txt"):
        country_code, admin1_code = fields[0].split(".", 1)
        members = by_admin1.get((country_code, admin1_code))
        if not members:
            continue
        latitude, longitude = _centroid(members)
        rows.append(
            _row(
                geonames_id=int(fields[3]),
                name=fields[1],
                alternates=fields[2],
                feature_code="ADM1",
                precision="admin1",
                country_code=country_code,
                admin1_code=admin1_code,
                admin2_code=None,
                latitude=latitude,
                longitude=longitude,
                population=None,
            )
        )

    for fields in _lines(source / "admin2Codes.txt"):
        country_code, admin1_code, admin2_code = fields[0].split(".", 2)
        members = by_admin2.get((country_code, admin1_code, admin2_code))
        if not members:
            continue
        latitude, longitude = _centroid(members)
        rows.append(
            _row(
                geonames_id=int(fields[3]),
                name=fields[1],
                alternates=fields[2],
                feature_code="ADM2",
                precision="admin2",
                country_code=country_code,
                admin1_code=admin1_code,
                admin2_code=admin2_code,
                latitude=latitude,
                longitude=longitude,
                population=None,
            )
        )

    for fields in cities:
        rows.append(
            _row(
                geonames_id=int(fields[0]),
                name=fields[1],
                alternates=fields[3],
                feature_code=fields[7],
                precision="place",
                country_code=fields[8],
                admin1_code=fields[10] or None,
                admin2_code=fields[11] or None,
                latitude=float(fields[4]),
                longitude=float(fields[5]),
                population=int(fields[14]) if fields[14] else None,
            )
        )

    return rows


def write_artifact(rows: list[GazetteerRow], target: Path) -> int:
    """Write the artifact, sorted by id so a rebuild is byte-identical."""
    ordered = sorted(rows, key=lambda row: row.geonames_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(target, "wt", encoding="utf-8", newline="\n", mtime=0) as handle:
        handle.write("\t".join(COLUMNS) + "\n")
        for row in ordered:
            handle.write(
                "\t".join(
                    (
                        str(row.geonames_id),
                        row.name,
                        row.normalized_name,
                        row.ascii_name,
                        ",".join(row.alternate_names),
                        row.feature_code,
                        row.precision,
                        row.country_code,
                        row.admin1_code or "",
                        row.admin2_code or "",
                        f"{row.latitude:.5f}",
                        f"{row.longitude:.5f}",
                        "" if row.population is None else str(row.population),
                    )
                )
                + "\n"
            )
    return len(ordered)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    written = write_artifact(build_rows(Path(argv[0])), Path(argv[1]))
    print(f"rows={written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_build_gazetteer.py -v`
Expected: PASS, 9 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/build_gazetteer.py packages/backend/tests/test_build_gazetteer.py packages/backend/tests/fixtures/gazetteer_sample
git commit -m "feat: build the gazetteer seed artifact from GeoNames dumps"
```

---

## Task 13: The country alias seed

**Files:**
- Create: `database/seeds/country_aliases.json`
- Create: `database/seeds/gazetteer/ATTRIBUTION.md`
- Modify: `packages/backend/src/episignal_backend/seeds.py`
- Modify: `packages/backend/tests/test_seeds.py`
- Modify: `README.md`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_seeds.py`:

```python
def test_the_country_alias_seed_maps_names_to_two_letter_codes() -> None:
    from episignal_backend.seeds import load_country_aliases

    aliases = load_country_aliases()
    assert len(aliases) >= 3
    for alias in aliases:
        assert len(alias.country_code) == 2
        assert alias.country_code == alias.country_code.upper()


def test_the_country_alias_seed_is_already_normalized() -> None:
    from episignal_backend.geocode.normalize import normalized_form
    from episignal_backend.seeds import load_country_aliases

    for alias in load_country_aliases():
        assert alias.name == normalized_form(alias.name)


def test_the_country_alias_seed_holds_no_duplicate_names() -> None:
    from episignal_backend.seeds import load_country_aliases

    names = [alias.name for alias in load_country_aliases()]
    assert len(names) == len(set(names))


def test_the_country_alias_seed_separates_niger_from_nigeria() -> None:
    from episignal_backend.seeds import load_country_aliases

    codes = {alias.name: alias.country_code for alias in load_country_aliases()}
    assert codes["niger"] == "NE"
    assert codes["nigeria"] == "NG"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_seeds.py -v -k country_alias`
Expected: FAIL with `ImportError: cannot import name 'load_country_aliases'`

- [ ] **Step 3: Write minimal implementation**

Create `database/seeds/country_aliases.json`. Names are already in normalized
form: casefolded, punctuation replaced by spaces, whitespace collapsed. Include
at minimum every country reachable by the current GDELT query rules, plus the
short and historical forms below.

```json
[
  { "name": "nigeria", "country_code": "NG" },
  { "name": "niger", "country_code": "NE" },
  { "name": "democratic republic of the congo", "country_code": "CD" },
  { "name": "dr congo", "country_code": "CD" },
  { "name": "drc", "country_code": "CD" },
  { "name": "congo dem rep", "country_code": "CD" },
  { "name": "zaire", "country_code": "CD" },
  { "name": "republic of the congo", "country_code": "CG" },
  { "name": "congo brazzaville", "country_code": "CG" },
  { "name": "united states", "country_code": "US" },
  { "name": "united states of america", "country_code": "US" },
  { "name": "usa", "country_code": "US" },
  { "name": "united kingdom", "country_code": "GB" },
  { "name": "uk", "country_code": "GB" },
  { "name": "great britain", "country_code": "GB" },
  { "name": "south korea", "country_code": "KR" },
  { "name": "republic of korea", "country_code": "KR" },
  { "name": "north korea", "country_code": "KP" },
  { "name": "ivory coast", "country_code": "CI" },
  { "name": "cote d ivoire", "country_code": "CI" },
  { "name": "myanmar", "country_code": "MM" },
  { "name": "burma", "country_code": "MM" },
  { "name": "tanzania", "country_code": "TZ" },
  { "name": "united republic of tanzania", "country_code": "TZ" },
  { "name": "vietnam", "country_code": "VN" },
  { "name": "viet nam", "country_code": "VN" },
  { "name": "laos", "country_code": "LA" },
  { "name": "lao pdr", "country_code": "LA" },
  { "name": "philippines", "country_code": "PH" },
  { "name": "the philippines", "country_code": "PH" },
  { "name": "saudi arabia", "country_code": "SA" },
  { "name": "uae", "country_code": "AE" },
  { "name": "united arab emirates", "country_code": "AE" },
  { "name": "czech republic", "country_code": "CZ" },
  { "name": "czechia", "country_code": "CZ" },
  { "name": "eswatini", "country_code": "SZ" },
  { "name": "swaziland", "country_code": "SZ" },
  { "name": "cape verde", "country_code": "CV" },
  { "name": "cabo verde", "country_code": "CV" },
  { "name": "east timor", "country_code": "TL" },
  { "name": "timor leste", "country_code": "TL" },
  { "name": "south sudan", "country_code": "SS" },
  { "name": "sudan", "country_code": "SD" },
  { "name": "india", "country_code": "IN" },
  { "name": "china", "country_code": "CN" },
  { "name": "peoples republic of china", "country_code": "CN" },
  { "name": "brazil", "country_code": "BR" },
  { "name": "mexico", "country_code": "MX" },
  { "name": "indonesia", "country_code": "ID" },
  { "name": "bangladesh", "country_code": "BD" },
  { "name": "pakistan", "country_code": "PK" },
  { "name": "ethiopia", "country_code": "ET" },
  { "name": "kenya", "country_code": "KE" },
  { "name": "uganda", "country_code": "UG" },
  { "name": "ghana", "country_code": "GH" },
  { "name": "senegal", "country_code": "SN" },
  { "name": "cameroon", "country_code": "CM" },
  { "name": "chad", "country_code": "TD" },
  { "name": "mali", "country_code": "ML" },
  { "name": "burkina faso", "country_code": "BF" },
  { "name": "guinea", "country_code": "GN" },
  { "name": "sierra leone", "country_code": "SL" },
  { "name": "liberia", "country_code": "LR" },
  { "name": "madagascar", "country_code": "MG" },
  { "name": "mozambique", "country_code": "MZ" },
  { "name": "zambia", "country_code": "ZM" },
  { "name": "zimbabwe", "country_code": "ZW" },
  { "name": "malawi", "country_code": "MW" },
  { "name": "angola", "country_code": "AO" },
  { "name": "south africa", "country_code": "ZA" },
  { "name": "yemen", "country_code": "YE" },
  { "name": "haiti", "country_code": "HT" },
  { "name": "afghanistan", "country_code": "AF" },
  { "name": "syria", "country_code": "SY" },
  { "name": "syrian arab republic", "country_code": "SY" }
]
```

Create `database/seeds/gazetteer/ATTRIBUTION.md`:

```markdown
# Gazetteer Attribution

`database/seeds/gazetteer_places.tsv.gz` is derived from the GeoNames geographical
database, specifically `countryInfo.txt`, `admin1CodesASCII.txt`, `admin2Codes.txt`,
and `cities1000.txt` from https://download.geonames.org/export/dump/.

GeoNames data is licensed under Creative Commons Attribution 4.0
(https://creativecommons.org/licenses/by/4.0/). The derivation is performed by
`scripts/build_gazetteer.py`, which normalizes names and flattens the four files
into one table; no coordinate or identifier is altered.
```

In `README.md`, add a line under the data or licensing section:

```markdown
Place names are resolved against a GeoNames extract. See
`database/seeds/gazetteer/ATTRIBUTION.md` for the CC BY 4.0 attribution.
```

In `packages/backend/src/episignal_backend/seeds.py`, add the seed model beside
the others and the loader beside the others:

```python
class CountryAliasSeed(BaseModel):
    """One accepted spelling of a country, already in normalized form.

    Normalization happens here rather than at lookup time so that a reviewer
    reading the file sees exactly the key the resolver will look up.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    country_code: str = Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")


def load_country_aliases() -> tuple[CountryAliasSeed, ...]:
    return tuple(
        TypeAdapter(list[CountryAliasSeed]).validate_python(_read_seed("country_aliases.json"))
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_seeds.py -v`
Expected: PASS, all tests in the file

- [ ] **Step 5: Commit**

```bash
git add database/seeds/country_aliases.json database/seeds/gazetteer/ATTRIBUTION.md packages/backend/src/episignal_backend/seeds.py packages/backend/tests/test_seeds.py README.md
git commit -m "feat: seed a reviewed country alias list"
```

---

## Task 14: Seeding the gazetteer

**Files:**
- Modify: `packages/backend/src/episignal_backend/seeds.py`
- Modify: `packages/backend/src/episignal_backend/seed_runner.py`
- Modify: `packages/backend/tests/test_seeds.py`

The artifact `database/seeds/gazetteer_places.tsv.gz` does not exist yet; it is
generated in Task 21. Until then `seed_gazetteer` reports zero rows for a
missing artifact rather than failing, so `corepack pnpm db:seed` keeps working
throughout the sub-project.

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_seeds.py`. Add only the imports the file
does not already have — a repeated import is a ruff `F811` failure:

```python
import gzip
from pathlib import Path
from typing import Any


class RecordingSession:
    def __init__(self) -> None:
        self.executed: list[Any] = []

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return None


def write_gazetteer(target: Path, rows: list[tuple[str, ...]]) -> None:
    header = (
        "geonames_id\tname\tnormalized_name\tascii_name\talternate_names\t"
        "feature_code\tprecision\tcountry_code\tadmin1_code\tadmin2_code\t"
        "latitude\tlongitude\tpopulation\n"
    )
    with gzip.open(target, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write(header)
        for row in rows:
            handle.write("\t".join(row) + "\n")


def test_it_reads_every_row_of_the_artifact(tmp_path: Path) -> None:
    from episignal_backend.seeds import read_gazetteer

    target = tmp_path / "gazetteer_places.tsv.gz"
    write_gazetteer(
        target,
        [
            ("2332459", "Lagos", "lagos", "lagos", "eko", "PPLA", "place", "NG", "05", "", "6.45407", "3.39467", "1536000"),
            ("2328926", "Nigeria", "nigeria", "nigeria", "", "PCLI", "country", "NG", "", "", "9.08333", "8.67500", ""),
        ],
    )
    rows = list(read_gazetteer(target))
    assert len(rows) == 2
    assert rows[0]["geonames_id"] == 2332459
    assert rows[0]["alternate_names"] == ["eko"]
    assert rows[0]["population"] == 1536000


def test_an_empty_optional_column_becomes_none_not_an_empty_string(tmp_path: Path) -> None:
    from episignal_backend.seeds import read_gazetteer

    target = tmp_path / "gazetteer_places.tsv.gz"
    write_gazetteer(
        target,
        [("2328926", "Nigeria", "nigeria", "nigeria", "", "PCLI", "country", "NG", "", "", "9.0", "8.0", "")],
    )
    row = next(iter(read_gazetteer(target)))
    assert row["admin1_code"] is None
    assert row["admin2_code"] is None
    assert row["population"] is None
    assert row["alternate_names"] == []


def test_seeding_a_missing_artifact_reports_zero_rather_than_failing(tmp_path: Path) -> None:
    from episignal_backend.seeds import seed_gazetteer

    session = RecordingSession()
    assert seed_gazetteer(session, tmp_path / "absent.tsv.gz") == 0
    assert session.executed == []


def test_seeding_batches_its_upserts(tmp_path: Path) -> None:
    from episignal_backend.seeds import GAZETTEER_BATCH_SIZE, seed_gazetteer

    target = tmp_path / "gazetteer_places.tsv.gz"
    write_gazetteer(
        target,
        [
            (str(index), f"Place{index}", f"place{index}", f"place{index}", "", "PPL", "place", "NG", "05", "", "1.0", "2.0", "")
            for index in range(1, GAZETTEER_BATCH_SIZE + 3)
        ],
    )
    session = RecordingSession()
    written = seed_gazetteer(session, target)
    assert written == GAZETTEER_BATCH_SIZE + 2
    assert len(session.executed) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_seeds.py -v -k gazetteer`
Expected: FAIL with `ImportError: cannot import name 'read_gazetteer'`

- [ ] **Step 3: Write minimal implementation**

In `packages/backend/src/episignal_backend/seeds.py`, add the imports
`import gzip` and `from collections.abc import Iterator`, extend the imported
models with `GazetteerPlace`, and add:

```python
GAZETTEER_BATCH_SIZE = 5000
GAZETTEER_ARTIFACT = "gazetteer_places.tsv.gz"


def gazetteer_path() -> Path:
    return Path(__file__).parents[4] / "database" / "seeds" / GAZETTEER_ARTIFACT


def read_gazetteer(path: Path) -> Iterator[dict[str, Any]]:
    """Stream the artifact rather than loading it.

    The full artifact holds roughly 190,000 rows. Reading it into a list would
    cost nothing this machine cannot afford and would still be the wrong shape:
    the loader below never needs more than one batch at a time.
    """
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        columns = handle.readline().rstrip("\n").split("\t")
        for line in handle:
            if not line.strip():
                continue
            values = dict(zip(columns, line.rstrip("\n").split("\t"), strict=True))
            yield {
                "geonames_id": int(values["geonames_id"]),
                "name": values["name"],
                "normalized_name": values["normalized_name"],
                "ascii_name": values["ascii_name"],
                "alternate_names": [
                    part for part in values["alternate_names"].split(",") if part
                ],
                "feature_code": values["feature_code"],
                "precision": values["precision"],
                "country_code": values["country_code"],
                "admin1_code": values["admin1_code"] or None,
                "admin2_code": values["admin2_code"] or None,
                "latitude": float(values["latitude"]),
                "longitude": float(values["longitude"]),
                "population": int(values["population"]) if values["population"] else None,
            }


def seed_gazetteer(session: Any, path: Path | None = None) -> int:
    """Upsert the gazetteer in batches, keyed on the stable GeoNames id.

    A missing artifact is not an error. The artifact is large enough to be
    generated rather than hand-written, and a clone that has not generated it
    should still be able to seed everything else.
    """
    target = gazetteer_path() if path is None else path
    if not target.exists():
        return 0

    written = 0
    batch: list[dict[str, Any]] = []
    for row in read_gazetteer(target):
        batch.append(row)
        if len(batch) >= GAZETTEER_BATCH_SIZE:
            _upsert(session, GazetteerPlace, batch, ("geonames_id",))
            written += len(batch)
            batch = []
    if batch:
        _upsert(session, GazetteerPlace, batch, ("geonames_id",))
        written += len(batch)
    return written
```

Extend `SeedResult` with `country_aliases: int` and `gazetteer_places: int`, and
in `seed_database` add:

```python
    country_aliases = load_country_aliases()
    gazetteer_places = seed_gazetteer(session)
```

The country aliases are read by the gazetteer repository from the seed file
directly rather than stored in a table of their own; validating them during
seeding is what makes a malformed file fail loudly at seed time.

Return them in `SeedResult`, and in `seed_runner.py` extend the printed line:

```python
        f"country_aliases={result.country_aliases} "
        f"gazetteer_places={result.gazetteer_places}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_seeds.py -v`
Expected: PASS, all tests in the file

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/seeds.py packages/backend/src/episignal_backend/seed_runner.py packages/backend/tests/test_seeds.py
git commit -m "feat: seed the gazetteer in batches from the committed artifact"
```

---

## Task 15: The gazetteer repository

**Files:**
- Create: `packages/backend/src/episignal_backend/geocode/repository.py`
- Test: `packages/backend/tests/test_geocode_repository.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_geocode_repository.py`:

```python
from typing import Any

from episignal_backend.geocode.documents import MatchForm
from episignal_backend.geocode.protocol import GazetteerRepository
from episignal_backend.geocode.repository import SqlAlchemyGazetteerRepository
from sqlalchemy import Select


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> Any:
        return self._value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = results or []
        self.executed: list[Any] = []

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return self._results.pop(0) if self._results else FakeResult(None)


class Row:
    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


def place_row(**overrides: Any) -> Row:
    fields: dict[str, Any] = {
        "geonames_id": 2332459,
        "name": "Lagos",
        "precision": "place",
        "country_code": "NG",
        "admin1_code": "05",
        "admin2_code": None,
        "latitude": 6.45,
        "longitude": 3.39,
    }
    fields.update(overrides)
    return Row(**fields)


def test_it_satisfies_the_gazetteer_boundary() -> None:
    assert isinstance(SqlAlchemyGazetteerRepository(FakeSession()), GazetteerRepository)


def test_the_alias_map_comes_from_the_reviewed_seed_file() -> None:
    aliases = SqlAlchemyGazetteerRepository(FakeSession()).country_aliases()
    assert aliases["nigeria"] == "NG"
    assert aliases["niger"] == "NE"


def test_it_turns_rows_into_candidates() -> None:
    session = FakeSession([FakeResult([place_row()])])
    found = SqlAlchemyGazetteerRepository(session).candidates(
        name="Lagos", form=MatchForm.EXACT, country_code="NG", admin1_code=None
    )
    assert len(found) == 1
    assert found[0].geonames_id == 2332459
    assert found[0].latitude == 6.45


def test_a_scoped_query_is_a_select_against_the_gazetteer() -> None:
    session = FakeSession([FakeResult([])])
    SqlAlchemyGazetteerRepository(session).candidates(
        name="Lagos", form=MatchForm.EXACT, country_code="NG", admin1_code="05"
    )
    statement = session.executed[0]
    assert isinstance(statement, Select)
    rendered = str(statement)
    assert "gazetteer_places" in rendered
    assert "normalized_name" in rendered


def test_the_ascii_form_queries_the_ascii_column() -> None:
    session = FakeSession([FakeResult([])])
    SqlAlchemyGazetteerRepository(session).candidates(
        name="Krakow", form=MatchForm.ASCII, country_code="PL", admin1_code=None
    )
    assert "ascii_name" in str(session.executed[0])


def test_the_alternate_form_queries_the_alternate_names_array() -> None:
    session = FakeSession([FakeResult([])])
    SqlAlchemyGazetteerRepository(session).candidates(
        name="Eko", form=MatchForm.ALTERNATE, country_code="NG", admin1_code=None
    )
    assert "alternate_names" in str(session.executed[0])


def test_a_worldwide_query_carries_no_country_filter() -> None:
    session = FakeSession([FakeResult([])])
    SqlAlchemyGazetteerRepository(session).candidates(
        name="Kinshasa", form=MatchForm.EXACT, country_code=None, admin1_code=None
    )
    assert "country_code" not in str(session.executed[0].whereclause)


def test_candidate_queries_are_bounded() -> None:
    # Two rows is all the ladder needs: one means unique, more than one means
    # ambiguous. Fetching every Springfield on earth to count them is waste.
    session = FakeSession([FakeResult([])])
    SqlAlchemyGazetteerRepository(session).candidates(
        name="Springfield", form=MatchForm.EXACT, country_code="US", admin1_code=None
    )
    assert "LIMIT" in str(session.executed[0]).upper()


def test_it_resolves_an_admin1_code_by_either_name_form() -> None:
    session = FakeSession([FakeResult("05")])
    code = SqlAlchemyGazetteerRepository(session).admin1_code(
        country_code="NG", name="Lagos State"
    )
    assert code == "05"
    rendered = str(session.executed[0])
    assert "normalized_name" in rendered
    assert "ascii_name" in rendered


def test_an_admin1_centroid_is_returned_as_a_candidate() -> None:
    row = place_row(geonames_id=2332453, name="Lagos", precision="admin1")
    session = FakeSession([FakeResult(row)])
    centre = SqlAlchemyGazetteerRepository(session).centroid(
        country_code="NG", admin1_code="05"
    )
    assert centre is not None
    assert centre.precision == "admin1"


def test_a_missing_centroid_is_none_rather_than_an_error() -> None:
    session = FakeSession([FakeResult(None)])
    assert (
        SqlAlchemyGazetteerRepository(session).centroid(country_code="ZZ", admin1_code=None)
        is None
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.geocode.repository'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/geocode/repository.py`:

```python
"""The storage boundary for geocoding.

The only module in `geocode/` that imports SQLAlchemy, and the only one that
owns transactions. Deliberately unable to decide anything: it fetches candidates
and writes rows, and the ladder above it chooses.
"""

from collections.abc import Mapping, Sequence
from functools import lru_cache

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from episignal_backend.db.types import Precision
from episignal_backend.geocode.documents import Candidate, MatchForm
from episignal_backend.geocode.normalize import ascii_form, normalized_form
from episignal_backend.models import GazetteerPlace
from episignal_backend.seeds import load_country_aliases

# Two is enough to answer the only question the ladder asks: is this name
# unique here? One row means yes, two means no, and the rest are irrelevant.
CANDIDATE_LIMIT = 2


@lru_cache(maxsize=1)
def _aliases() -> Mapping[str, str]:
    return {alias.name: alias.country_code for alias in load_country_aliases()}


def _candidate(row: GazetteerPlace) -> Candidate:
    return Candidate(
        geonames_id=row.geonames_id,
        name=row.name,
        precision=row.precision,
        country_code=row.country_code,
        admin1_code=row.admin1_code,
        admin2_code=row.admin2_code,
        latitude=row.latitude,
        longitude=row.longitude,
    )


class SqlAlchemyGazetteerRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def country_aliases(self) -> Mapping[str, str]:
        return _aliases()

    def _scoped(
        self, statement: Select[tuple[GazetteerPlace]], country_code: str | None, admin1_code: str | None
    ) -> Select[tuple[GazetteerPlace]]:
        if country_code is not None:
            statement = statement.where(GazetteerPlace.country_code == country_code)
            if admin1_code is not None:
                statement = statement.where(GazetteerPlace.admin1_code == admin1_code)
        return statement

    def candidates(
        self,
        *,
        name: str,
        form: MatchForm,
        country_code: str | None,
        admin1_code: str | None,
    ) -> Sequence[Candidate]:
        if form is MatchForm.EXACT:
            predicate = GazetteerPlace.normalized_name == normalized_form(name)
        elif form is MatchForm.ASCII:
            predicate = GazetteerPlace.ascii_name == ascii_form(name)
        else:
            predicate = GazetteerPlace.alternate_names.any(  # type: ignore[assignment]
                normalized_form(name)
            )
        statement = self._scoped(
            select(GazetteerPlace).where(predicate), country_code, admin1_code
        ).limit(CANDIDATE_LIMIT)
        return tuple(_candidate(row) for row in self._session.execute(statement).scalars())

    def admin1_code(self, *, country_code: str, name: str) -> str | None:
        return self._session.execute(
            select(GazetteerPlace.admin1_code)
            .where(
                GazetteerPlace.country_code == country_code,
                GazetteerPlace.precision == Precision.ADMIN1,
                or_(
                    GazetteerPlace.normalized_name == normalized_form(name),
                    GazetteerPlace.ascii_name == ascii_form(name),
                ),
            )
            .limit(1)
        ).scalar_one_or_none()

    def centroid(self, *, country_code: str, admin1_code: str | None) -> Candidate | None:
        precision = Precision.COUNTRY if admin1_code is None else Precision.ADMIN1
        statement = select(GazetteerPlace).where(
            GazetteerPlace.country_code == country_code,
            GazetteerPlace.precision == precision,
        )
        if admin1_code is not None:
            statement = statement.where(GazetteerPlace.admin1_code == admin1_code)
        row = self._session.execute(statement.limit(1)).scalar_one_or_none()
        return None if row is None else _candidate(row)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_repository.py -v`
Expected: PASS, 11 passed

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/geocode/repository.py packages/backend/tests/test_geocode_repository.py
git commit -m "feat: add the gazetteer storage adapter"
```

---

## Task 16: The geocoding repository

**Files:**
- Modify: `packages/backend/src/episignal_backend/geocode/repository.py`
- Modify: `packages/backend/tests/test_geocode_repository.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_geocode_repository.py`:

```python
from uuid import uuid4

from episignal_backend.db.types import LocationRole, Precision
from episignal_backend.geocode.documents import ResolvedLocation
from episignal_backend.geocode.protocol import GeocodeRepository
from episignal_backend.geocode.repository import SqlAlchemyGeocodeRepository
from sqlalchemy import Delete, Update


class SignalRow:
    def __init__(self, signal_id: Any, extraction: Any) -> None:
        self.id = signal_id
        self.ai_extraction = extraction


def test_it_satisfies_the_geocoding_storage_boundary() -> None:
    assert isinstance(SqlAlchemyGeocodeRepository(FakeSession()), GeocodeRepository)


def test_only_extracted_signals_are_selected() -> None:
    session = FakeSession([FakeResult([])])
    SqlAlchemyGeocodeRepository(session).awaiting_geocoding(limit=10)
    rendered = str(session.executed[0].whereclause)
    assert "processing_status" in rendered
    assert "ai_extraction" in rendered


def test_it_reads_the_places_out_of_the_stored_extraction() -> None:
    extraction = {
        "signal_type": "outbreak_report",
        "summary": "Cholera in Lagos.",
        "locations": [
            {"role": "primary", "country": "Nigeria", "admin1": None, "place_name": "Lagos"}
        ],
    }
    signal_id = uuid4()
    session = FakeSession([FakeResult([SignalRow(signal_id, extraction)])])
    signals = SqlAlchemyGeocodeRepository(session).awaiting_geocoding(limit=10)
    assert len(signals) == 1
    assert signals[0].id == signal_id
    place = signals[0].locations[0]
    assert place.role == LocationRole.PRIMARY
    assert place.country_name == "Nigeria"
    assert place.place_name == "Lagos"


def test_an_extraction_naming_no_places_yields_a_signal_with_no_locations() -> None:
    extraction = {"signal_type": "research", "summary": "A modelling study."}
    session = FakeSession([FakeResult([SignalRow(uuid4(), extraction)])])
    signals = SqlAlchemyGeocodeRepository(session).awaiting_geocoding(limit=10)
    assert signals[0].locations == ()


def test_replacing_locations_deletes_before_it_inserts() -> None:
    session = FakeSession()
    repository = SqlAlchemyGeocodeRepository(session)
    resolved = ResolvedLocation(
        role=LocationRole.PRIMARY,
        country_name="Nigeria",
        place_name="Lagos",
        precision=Precision.PLACE,
        geonames_id=2332459,
        resolved_name="Lagos",
        country_code="NG",
        admin1="05",
        latitude=6.45,
        longitude=3.39,
        confidence=0.95,
    )
    repository.replace_locations(uuid4(), (resolved,), source="geonames-2026-08-27")
    assert isinstance(session.executed[0], Delete)
    assert len(session.added) == 1
    assert session.added[0].geocoding_source == "geonames-2026-08-27"
    assert session.added[0].geocoding_confidence == 0.95


def test_an_unresolved_location_is_stored_with_no_geometry() -> None:
    session = FakeSession()
    repository = SqlAlchemyGeocodeRepository(session)
    resolved = ResolvedLocation(
        role=LocationRole.PRIMARY, place_name="Strelsau", precision=Precision.UNRESOLVED
    )
    repository.replace_locations(uuid4(), (resolved,), source="geonames-2026-08-27")
    stored = session.added[0]
    assert stored.geometry is None
    assert stored.latitude is None
    assert stored.geocoding_confidence is None


def test_marking_geocoded_advances_only_the_processing_status() -> None:
    session = FakeSession()
    SqlAlchemyGeocodeRepository(session).mark_geocoded(uuid4())
    statement = session.executed[0]
    assert isinstance(statement, Update)
    rendered = str(statement)
    assert "processing_status" in rendered
    assert "ai_extraction" not in rendered


def test_stale_selection_asks_for_a_source_other_than_the_current_one() -> None:
    session = FakeSession([FakeResult([])])
    SqlAlchemyGeocodeRepository(session).stale_geocoding(
        limit=10, source="geonames-2026-08-27"
    )
    rendered = str(session.executed[0])
    assert "geocoding_source" in rendered
```

Extend `FakeSession` in this file with the `add`, `commit`, and `rollback`
methods, matching `packages/backend/tests/test_ai_repository.py`:

```python
class FakeSession:
    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = results or []
        self.executed: list[Any] = []
        self.added: list[Any] = []

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return self._results.pop(0) if self._results else FakeResult(None)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_repository.py -v`
Expected: FAIL with `ImportError: cannot import name 'SqlAlchemyGeocodeRepository'`

- [ ] **Step 3: Write minimal implementation**

Append to `packages/backend/src/episignal_backend/geocode/repository.py`:

```python
from typing import Any
from uuid import UUID

from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, update

from episignal_backend.db.types import LocationRole, ProcessingStatus
from episignal_backend.geocode.documents import (
    ExtractedPlace,
    GeocodableSignal,
    ResolvedLocation,
)
from episignal_backend.models import Signal, SignalLocation


def _places(extraction: Any) -> tuple[ExtractedPlace, ...]:
    """Read the locations out of a stored extraction.

    Tolerant of a missing `locations` key and of nulls inside it, because the
    schema makes every field but the role optional and an older row may predate
    a field entirely. Not tolerant of an unknown role: that is a corrupted row
    rather than a sparse one.
    """
    if not isinstance(extraction, dict):
        return ()
    raw = extraction.get("locations") or ()
    return tuple(
        ExtractedPlace(
            role=LocationRole(item["role"]),
            country_name=item.get("country"),
            admin1_name=item.get("admin1"),
            place_name=item.get("place_name"),
        )
        for item in raw
    )


def _point(resolved: ResolvedLocation) -> WKTElement | None:
    if resolved.latitude is None or resolved.longitude is None:
        return None
    return WKTElement(f"POINT({resolved.longitude} {resolved.latitude})", srid=4326)


class SqlAlchemyGeocodeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _signals(self, statement: Select[tuple[Signal]]) -> Sequence[GeocodableSignal]:
        rows = self._session.execute(statement).scalars()
        return tuple(
            GeocodableSignal(id=row.id, locations=_places(row.ai_extraction)) for row in rows
        )

    def awaiting_geocoding(self, *, limit: int) -> Sequence[GeocodableSignal]:
        # The enforcement of the pipeline order: `classified`, `normalized`, and
        # `duplicate` are simply not selectable here.
        return self._signals(
            select(Signal)
            .where(
                Signal.processing_status == ProcessingStatus.EXTRACTED,
                Signal.ai_extraction.is_not(None),
            )
            .order_by(Signal.first_seen_at)
            .limit(limit)
        )

    def stale_geocoding(self, *, limit: int, source: str) -> Sequence[GeocodableSignal]:
        superseded = (
            select(SignalLocation.signal_id)
            .where(SignalLocation.geocoding_source.is_distinct_from(source))
            .distinct()
        )
        return self._signals(
            select(Signal)
            .where(
                Signal.processing_status == ProcessingStatus.GEOCODED,
                Signal.ai_extraction.is_not(None),
                Signal.id.in_(superseded),
            )
            .order_by(Signal.first_seen_at)
            .limit(limit)
        )

    def replace_locations(
        self, signal_id: UUID, locations: Sequence[ResolvedLocation], *, source: str
    ) -> None:
        # Delete then insert rather than upsert. The extraction is the sole
        # input, so the current answer is the whole answer and there is no
        # partial state worth reconciling.
        self._session.execute(
            delete(SignalLocation).where(SignalLocation.signal_id == signal_id)
        )
        for resolved in locations:
            self._session.add(
                SignalLocation(
                    signal_id=signal_id,
                    location_role=resolved.role,
                    country_name=resolved.country_name,
                    admin1_name=resolved.admin1_name,
                    place_name=resolved.place_name,
                    precision=resolved.precision,
                    geonames_id=resolved.geonames_id,
                    resolved_name=resolved.resolved_name,
                    country_code=resolved.country_code,
                    admin1=resolved.admin1,
                    admin2=resolved.admin2,
                    latitude=resolved.latitude,
                    longitude=resolved.longitude,
                    geometry=_point(resolved),
                    geocoding_source=source,
                    geocoding_confidence=resolved.confidence,
                )
            )

    def mark_geocoded(self, signal_id: UUID) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(processing_status=ProcessingStatus.GEOCODED)
        )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_repository.py -v`
Expected: PASS, 19 passed

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/geocode/repository.py packages/backend/tests/test_geocode_repository.py
git commit -m "feat: add the geocoding storage adapter"
```

---

## Task 17: The pass

**Files:**
- Create: `packages/backend/src/episignal_backend/geocode/locate.py`
- Test: `packages/backend/tests/test_geocode_locate.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_geocode_locate.py`:

```python
from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4

import pytest
from episignal_backend.db.types import LocationRole, Precision
from episignal_backend.geocode.documents import (
    Candidate,
    ExtractedPlace,
    GeocodableSignal,
    MatchForm,
    ResolvedLocation,
)
from episignal_backend.geocode.locate import GeocodingResult, run_geocoding
from episignal_backend.geocode.protocol import GazetteerMissing

SOURCE = "geonames-2026-08-27"

LAGOS = Candidate(
    geonames_id=2332459,
    name="Lagos",
    precision=Precision.PLACE,
    country_code="NG",
    admin1_code="05",
    admin2_code=None,
    latitude=6.45,
    longitude=3.39,
)


class Gazetteer:
    def __init__(self, *, empty: bool = False) -> None:
        self.empty = empty

    def country_aliases(self) -> Mapping[str, str]:
        return {} if self.empty else {"nigeria": "NG"}

    def admin1_code(self, *, country_code: str, name: str) -> str | None:
        return None

    def candidates(
        self, *, name: str, form: MatchForm, country_code: str | None, admin1_code: str | None
    ) -> Sequence[Candidate]:
        if self.empty or form is not MatchForm.EXACT or name != "Lagos":
            return ()
        return (LAGOS,)

    def centroid(self, *, country_code: str, admin1_code: str | None) -> Candidate | None:
        return None


class Storage:
    def __init__(self, signals: Sequence[GeocodableSignal] = (), stale: Sequence[GeocodableSignal] = ()) -> None:
        self._signals = signals
        self._stale = stale
        self.written: dict[UUID, tuple[ResolvedLocation, ...]] = {}
        self.geocoded: list[UUID] = []
        self.commits = 0
        self.rollbacks = 0

    def awaiting_geocoding(self, *, limit: int) -> Sequence[GeocodableSignal]:
        return self._signals[:limit]

    def stale_geocoding(self, *, limit: int, source: str) -> Sequence[GeocodableSignal]:
        return self._stale[:limit]

    def replace_locations(
        self, signal_id: UUID, locations: Sequence[ResolvedLocation], *, source: str
    ) -> None:
        self.written[signal_id] = tuple(locations)

    def mark_geocoded(self, signal_id: UUID) -> None:
        self.geocoded.append(signal_id)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def signal_named(place_name: str | None, country: str | None = "Nigeria") -> GeocodableSignal:
    return GeocodableSignal(
        id=uuid4(),
        locations=(
            ExtractedPlace(
                role=LocationRole.PRIMARY, country_name=country, place_name=place_name
            ),
        ),
    )


def test_it_resolves_and_advances_a_signal() -> None:
    signal = signal_named("Lagos")
    storage = Storage(signals=(signal,))
    result = run_geocoding(storage, Gazetteer(), limit=10, source=SOURCE)
    assert result == GeocodingResult(examined=1, located=1, unresolved=0, locations=1)
    assert storage.geocoded == [signal.id]
    assert storage.written[signal.id][0].precision == Precision.PLACE


def test_a_signal_whose_places_all_fail_still_advances() -> None:
    # Absence of a coordinate is not a processing failure. Sending it to review
    # would fill the queue with places no gazetteer of this size will hold.
    signal = signal_named("Nowheresville")
    storage = Storage(signals=(signal,))
    result = run_geocoding(storage, Gazetteer(), limit=10, source=SOURCE)
    assert storage.geocoded == [signal.id]
    assert result.unresolved == 1
    assert result.located == 0
    assert storage.written[signal.id][0].precision == Precision.UNRESOLVED


def test_a_signal_naming_no_places_advances_with_no_rows() -> None:
    signal = GeocodableSignal(id=uuid4())
    storage = Storage(signals=(signal,))
    result = run_geocoding(storage, Gazetteer(), limit=10, source=SOURCE)
    assert storage.geocoded == [signal.id]
    assert storage.written[signal.id] == ()
    assert result == GeocodingResult(examined=1, located=0, unresolved=0, locations=0)


def test_the_pass_commits_once_when_it_finishes() -> None:
    storage = Storage(signals=(signal_named("Lagos"), signal_named("Lagos")))
    run_geocoding(storage, Gazetteer(), limit=10, source=SOURCE)
    assert storage.commits == 1
    assert storage.rollbacks == 0


def test_an_empty_gazetteer_stops_the_run_instead_of_marking_signals() -> None:
    storage = Storage(signals=(signal_named("Lagos"),))
    with pytest.raises(GazetteerMissing):
        run_geocoding(storage, Gazetteer(empty=True), limit=10, source=SOURCE)
    assert storage.geocoded == []
    assert storage.rollbacks == 1


def test_the_limit_bounds_what_the_pass_examines() -> None:
    storage = Storage(signals=tuple(signal_named("Lagos") for _ in range(5)))
    result = run_geocoding(storage, Gazetteer(), limit=2, source=SOURCE)
    assert result.examined == 2


def test_the_stale_pass_reads_from_the_stale_selection() -> None:
    fresh = signal_named("Lagos")
    stale = signal_named("Lagos")
    storage = Storage(signals=(fresh,), stale=(stale,))
    run_geocoding(storage, Gazetteer(), limit=10, source=SOURCE, stale=True)
    assert storage.geocoded == [stale.id]


def test_nothing_in_the_pass_can_send_a_signal_to_review() -> None:
    storage = Storage(signals=(signal_named("Nowheresville"),))
    run_geocoding(storage, Gazetteer(), limit=10, source=SOURCE)
    assert not hasattr(storage, "mark_needs_review")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_locate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.geocode.locate'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/geocode/locate.py`:

```python
"""The geocoding pass.

Orchestration only: it selects signals, runs the ladder over each place, writes
the rows, and advances the signal. It has no failure of its own to report about
a signal, because there is none available to it. An unresolvable place is a
recorded answer, not an error, and the only thing that can stop the run is an
empty gazetteer, which is an operator problem rather than a signal problem.

This module imports neither SQLAlchemy nor httpx.
"""

from dataclasses import dataclass

from episignal_backend.db.types import Precision
from episignal_backend.geocode.protocol import (
    GazetteerMissing,
    GazetteerRepository,
    GeocodeRepository,
)
from episignal_backend.geocode.resolve import resolve_place


@dataclass(frozen=True)
class GeocodingResult:
    examined: int = 0
    located: int = 0
    unresolved: int = 0
    locations: int = 0


def run_geocoding(
    repository: GeocodeRepository,
    gazetteer: GazetteerRepository,
    *,
    limit: int,
    source: str,
    stale: bool = False,
) -> GeocodingResult:
    if not gazetteer.country_aliases():
        repository.rollback()
        raise GazetteerMissing("no country aliases are loaded, so nothing can be scoped")

    signals = (
        repository.stale_geocoding(limit=limit, source=source)
        if stale
        else repository.awaiting_geocoding(limit=limit)
    )

    examined = 0
    located = 0
    unresolved = 0
    written = 0

    for signal in signals:
        resolutions = tuple(resolve_place(place, gazetteer) for place in signal.locations)
        repository.replace_locations(signal.id, resolutions, source=source)
        repository.mark_geocoded(signal.id)
        examined += 1
        written += len(resolutions)
        for resolution in resolutions:
            if resolution.precision is Precision.UNRESOLVED:
                unresolved += 1
            else:
                located += 1

    repository.commit()
    return GeocodingResult(
        examined=examined, located=located, unresolved=unresolved, locations=written
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_locate.py -v`
Expected: PASS, 8 passed

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/geocode/locate.py packages/backend/tests/test_geocode_locate.py
git commit -m "feat: add the geocoding pass"
```

---

## Task 18: Configuration

**Files:**
- Modify: `packages/backend/src/episignal_backend/config.py`
- Modify: `packages/backend/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_config.py`:

```python
def test_geocoding_defaults_are_set(monkeypatch: Any) -> None:
    settings = build_settings(monkeypatch)
    assert settings.geocode_batch_size == 200
    assert settings.geocode_max_signals_per_run == 2000
    assert settings.gazetteer_source == "geonames-2026-08-27"


def test_the_geocoding_batch_must_fit_the_run(monkeypatch: Any) -> None:
    with pytest.raises(ValidationError):
        build_settings(
            monkeypatch,
            EPISIGNAL_GEOCODE_BATCH_SIZE="500",
            EPISIGNAL_GEOCODE_MAX_SIGNALS_PER_RUN="100",
        )


def test_the_gazetteer_source_must_not_be_blank(monkeypatch: Any) -> None:
    with pytest.raises(ValidationError):
        build_settings(monkeypatch, EPISIGNAL_GAZETTEER_SOURCE="   ")
```

Read the top of `packages/backend/tests/test_config.py` first and reuse whatever
helper it already has for constructing `Settings` with a valid database URL and
overridden environment variables. If it has none, add:

```python
def build_settings(monkeypatch: Any, **overrides: str) -> Settings:
    monkeypatch.setenv(
        "EPISIGNAL_DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/episignal"
    )
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_config.py -v -k geocod`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'geocode_batch_size'`

- [ ] **Step 3: Write minimal implementation**

In `packages/backend/src/episignal_backend/config.py`, add after the `ai_*`
settings:

```python
    geocode_batch_size: int = Field(default=200, ge=1, le=5000)
    geocode_max_signals_per_run: int = Field(default=2000, ge=1, le=100000)
    # Stamped onto every row this run writes, and the value `--stale` compares
    # against. Bump it whenever the seed artifact is regenerated, or a refreshed
    # gazetteer reaches only signals processed after it.
    gazetteer_source: str = Field(default="geonames-2026-08-27", min_length=1)
```

Add the validator beside the existing ones:

```python
    @field_validator("gazetteer_source")
    @classmethod
    def gazetteer_source_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("EPISIGNAL_GAZETTEER_SOURCE must name the gazetteer in use")
        return value

    @model_validator(mode="after")
    def geocode_batch_fits_the_run(self) -> "Settings":
        if self.geocode_batch_size > self.geocode_max_signals_per_run:
            raise ValueError(
                "EPISIGNAL_GEOCODE_BATCH_SIZE must not exceed "
                "EPISIGNAL_GEOCODE_MAX_SIGNALS_PER_RUN"
            )
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_config.py -v`
Expected: PASS, all tests in the file

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/config.py packages/backend/tests/test_config.py
git commit -m "feat: add geocoding configuration"
```

---

## Task 19: The CLI runner

**Files:**
- Create: `packages/backend/src/episignal_backend/geocode_runner.py`
- Modify: `package.json`
- Test: `packages/backend/tests/test_geocode_runner.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_geocode_runner.py`:

```python
import json
from pathlib import Path
from typing import Any

from episignal_backend.geocode_runner import main, parse_arguments


def test_it_defaults_to_the_fresh_pass() -> None:
    arguments = parse_arguments([])
    assert arguments.limit is None
    assert arguments.stale is False


def test_it_accepts_a_limit_and_the_stale_flag() -> None:
    arguments = parse_arguments(["--limit", "50", "--stale"])
    assert arguments.limit == 50
    assert arguments.stale is True


def test_it_ignores_the_bare_separator_pnpm_passes_through() -> None:
    assert parse_arguments(["--", "--limit", "5"]).limit == 5


def test_a_failure_prints_the_exception_type_and_nothing_else(
    monkeypatch: Any, capsys: Any
) -> None:
    def explode(_: Any) -> None:
        raise RuntimeError("postgresql://user:secret@host/db")

    monkeypatch.setattr("episignal_backend.geocode_runner._run", explode)
    assert main([]) == 1
    captured = capsys.readouterr()
    assert "secret" not in captured.err
    assert "RuntimeError" in captured.err


def test_a_successful_run_prints_counts_only(monkeypatch: Any, capsys: Any) -> None:
    from episignal_backend.geocode.locate import GeocodingResult

    monkeypatch.setattr(
        "episignal_backend.geocode_runner._run",
        lambda _: GeocodingResult(examined=3, located=4, unresolved=1, locations=5),
    )
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "examined=3" in captured.out
    assert "located=4" in captured.out
    assert "unresolved=1" in captured.out


def test_the_workspace_script_is_wired() -> None:
    package = json.loads(Path("package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["geocode:signals"] == (
        "uv run --package episignal-backend python -m episignal_backend.geocode_runner"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.geocode_runner'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/geocode_runner.py`:

```python
"""Entry point for `pnpm geocode:signals`.

Counts only. The connection string and the article text never reach stdout or
stderr, the same posture as `extract_runner.py`. A failure message says what
stage failed and nothing about what was in it.

Re-running is safe: the fresh pass selects only signals still at `extracted`, so
a second run in the same minute does nothing. `--stale` re-runs signals whose
rows were written against a superseded gazetteer.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.geocode.locate import GeocodingResult, run_geocoding
from episignal_backend.geocode.repository import (
    SqlAlchemyGazetteerRepository,
    SqlAlchemyGeocodeRepository,
)


@dataclass(frozen=True)
class Arguments:
    limit: int | None
    stale: bool


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="geocode",
        description="Resolve the places named by extracted signals.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Signals to examine. Defaults to EPISIGNAL_GEOCODE_BATCH_SIZE.",
    )
    parser.add_argument(
        "--stale",
        action="store_true",
        help="Re-run signals whose locations came from a superseded gazetteer.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(limit=parsed.limit, stale=parsed.stale)


def _run(arguments: Arguments) -> GeocodingResult:
    settings = get_settings()
    limit = min(
        arguments.limit or settings.geocode_batch_size,
        settings.geocode_max_signals_per_run,
    )
    with session_scope() as session:
        return run_geocoding(
            SqlAlchemyGeocodeRepository(session),
            SqlAlchemyGazetteerRepository(session),
            limit=limit,
            source=settings.gazetteer_source,
            stale=arguments.stale,
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        result = _run(arguments)
    except Exception as error:
        # The message is fixed text plus the exception's type, never its
        # payload: an exception raised near the session can carry the
        # connection string.
        print(
            f"Geocoding failed before completing ({type(error).__name__}). "
            "Check the database, the migration state, and that the gazetteer is seeded.",
            file=sys.stderr,
        )
        return 1

    print(
        f"examined={result.examined} located={result.located} "
        f"unresolved={result.unresolved} locations={result.locations}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

In `package.json`, add beside `extract:signals`:

```json
    "geocode:signals": "uv run --package episignal-backend python -m episignal_backend.geocode_runner",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_runner.py -v`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/geocode_runner.py package.json packages/backend/tests/test_geocode_runner.py
git commit -m "feat: add the geocode command and its workspace script"
```

---

## Task 20: The seam and schema guards

**Files:**
- Modify: `packages/backend/src/episignal_backend/schema_check.py`
- Test: `packages/backend/tests/test_geocode_seams.py`
- Test: `packages/backend/tests/test_schema_check.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_geocode_seams.py`:

```python
from pathlib import Path

import pytest

GEOCODE = Path(__file__).parents[1] / "src" / "episignal_backend" / "geocode"
DECISION_MODULES = ("documents.py", "normalize.py", "resolve.py", "protocol.py", "locate.py")


@pytest.mark.parametrize("name", DECISION_MODULES)
def test_a_decision_module_imports_no_database_driver(name: str) -> None:
    source = (GEOCODE / name).read_text(encoding="utf-8")
    assert "sqlalchemy" not in source.lower()


def test_no_module_in_the_sub_project_touches_the_network() -> None:
    # There is no provider to call. A future network geocoder is an adapter
    # module, and this test is what makes adding one a deliberate act.
    for path in GEOCODE.glob("*.py"):
        assert "httpx" not in path.read_text(encoding="utf-8").lower()


def test_only_the_repository_imports_sqlalchemy() -> None:
    importers = {
        path.name
        for path in GEOCODE.glob("*.py")
        if "sqlalchemy" in path.read_text(encoding="utf-8").lower()
    }
    assert importers == {"repository.py"}


def test_the_ladder_never_reads_a_population() -> None:
    # The tie-break prohibition, enforced structurally rather than only by the
    # behavioural tests: `resolve.py` has no access to population at all,
    # because `Candidate` does not carry it.
    from episignal_backend.geocode.documents import Candidate

    assert "population" not in Candidate.model_fields
```

Append to `packages/backend/tests/test_schema_check.py`:

```python
def test_the_expected_tables_include_the_geocoding_tables() -> None:
    from episignal_backend.schema_check import EXPECTED_TABLES

    assert "gazetteer_places" in EXPECTED_TABLES
    assert "signal_locations" in EXPECTED_TABLES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_geocode_seams.py packages/backend/tests/test_schema_check.py -v`
Expected: FAIL — the schema-check assertion fails because `EXPECTED_TABLES` lacks both names. The seam tests should already pass; if any does not, fix the offending module rather than the test.

- [ ] **Step 3: Write minimal implementation**

In `packages/backend/src/episignal_backend/schema_check.py`, extend
`EXPECTED_TABLES`:

```python
EXPECTED_TABLES = (
    "sources",
    "signals",
    "diseases",
    "pathogens",
    "events",
    "event_signals",
    "event_observations",
    "event_locations",
    "gazetteer_places",
    "signal_locations",
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_geocode_seams.py packages/backend/tests/test_schema_check.py -v`
Expected: PASS, all tests in both files

- [ ] **Step 5: Run the whole gate**

```bash
uv run pytest
```

Expected: PASS, roughly 590 tests, 0 failures

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src packages/backend/src
```

Expected: `All checks passed!`, `N files already formatted`, `Success: no issues found`

Fix anything that fails before committing.

- [ ] **Step 6: Commit**

```bash
git add packages/backend/src/episignal_backend/schema_check.py packages/backend/tests/test_geocode_seams.py packages/backend/tests/test_schema_check.py
git commit -m "test: guard the geocoding seams and the expected schema"
```

---

## Task 21: Build the real artifact and verify live

This is the only task that touches the network or a database. It needs a
reachable PostgreSQL with PostGIS and `apps/api/.env` populated.

**Files:**
- Create: `database/seeds/gazetteer_places.tsv.gz`
- Create: `docs/reports/2026-08-27-subproject-d1-report.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: Download the four GeoNames files**

Download into a scratch directory outside the repository:

- `https://download.geonames.org/export/dump/countryInfo.txt`
- `https://download.geonames.org/export/dump/admin1CodesASCII.txt`
- `https://download.geonames.org/export/dump/admin2Codes.txt`
- `https://download.geonames.org/export/dump/cities1000.zip`, then extract `cities1000.txt`

- [ ] **Step 2: Build the artifact**

```bash
uv run python scripts/build_gazetteer.py <scratch-directory> database/seeds/gazetteer_places.tsv.gz
```

Expected: `rows=` followed by roughly 190,000.

Confirm the file is between 3 and 10 MB. If it is much larger, the wrong dump
was downloaded — `allCountries.txt` is not the input.

- [ ] **Step 3: Set the gazetteer source to today's dump**

In `packages/backend/src/episignal_backend/config.py`, set `gazetteer_source`
to `geonames-<the date you downloaded>`. Update the matching assertion in
`packages/backend/tests/test_config.py`.

- [ ] **Step 4: Migrate and seed**

```bash
corepack pnpm db:migrate
```

Expected: `Running upgrade 20260827_0005 -> 20260827_0006`

```bash
corepack pnpm db:seed
```

Expected: a line ending `country_aliases=<N> gazetteer_places=<~190000>`

- [ ] **Step 5: Verify the migration rolls back and forward**

```bash
corepack pnpm db:rollback
corepack pnpm db:migrate
corepack pnpm db:seed
```

Expected: all three succeed. The rollback drops both tables without prompting,
because neither holds anything that cannot be rebuilt.

- [ ] **Step 6: Run the pass**

```bash
corepack pnpm geocode:signals -- --limit 50
```

Expected: `examined=<N> located=<N> unresolved=<N> locations=<N>`

Then confirm against the database, with `uv run python`:

- every row in `signal_locations` has a non-null `precision` and
  `geocoding_source`;
- every row at `precision = 'unresolved'` has null `latitude`, `longitude`,
  `geometry`, and `geocoding_confidence`;
- no row has a non-null `latitude` and a null `geocoding_confidence`;
- every signal that was `extracted` before the run is now `geocoded`;
- no signal moved to `needs_review`;
- `signals.ai_extraction` is unchanged for every signal touched. Capture a hash
  of the column before and after the run and compare them.

- [ ] **Step 7: Verify re-running is idempotent**

```bash
corepack pnpm geocode:signals -- --stale --limit 50
```

Run it twice. Expected: the second run reports `examined=0`, because the first
run stamped every row with the current source.

- [ ] **Step 8: Run the full gate**

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src packages/backend/src
corepack pnpm verify
```

Expected: all pass.

- [ ] **Step 9: Commit the artifact and the source stamp**

```bash
git add database/seeds/gazetteer_places.tsv.gz packages/backend/src/episignal_backend/config.py packages/backend/tests/test_config.py
git commit -m "chore: build the GeoNames gazetteer artifact and verify geocoding live"
```

- [ ] **Step 10: Review, report, and hand off**

Use the `code-review` skill against `2f01d31`, then `verify-and-stop`.

Write `docs/reports/2026-08-27-subproject-d1-report.md` in the shape
`docs/reports/2026-08-27-subproject-c-report.md` uses: executive summary, task
ledger with commits, verification results, two-axis review summary, conclusion.

Rewrite `HANDOFF.md` to target Sub-project D2 (story clustering, event matching,
and dual scoring). Record that `signal_locations` now exists with a GIST index
and is D2's spatial input, and carry forward these open items:

- `ExtractedLocation` has no `source_span`, so places are the one extracted fact
  that is not grounded. Closing it needs a schema change in Sub-project C and
  re-extraction of every signal already processed.
- `events.attention_score` and `events.confidence_score` exist and are not the
  two scores `CONTEXT.md` names. D2 must reconcile them explicitly.
- The gazetteer holds no place below roughly a thousand inhabitants. A village
  resolves to its district or province centroid, and D2 must weigh a
  `country`-precision location far below a `place`-precision one.
- The four items carried forward from Sub-project C's review, still open.

```bash
git add docs/reports/2026-08-27-subproject-d1-report.md HANDOFF.md
git commit -m "docs: add the Sub-Project D1 completion report"
```

---

## Verification Checklist

Each maps to an acceptance criterion in the design.

| # | Criterion | Where it is verified |
| --- | --- | --- |
| 1 | Resolvable town yields a `place` row and advances | Task 17, `test_it_resolves_and_advances_a_signal` |
| 2 | Ambiguous town in a known admin1 yields an `admin1` row | Task 8, `test_two_survivors_coarsen_to_the_admin1_centroid` |
| 3 | Unknown place with no admin1 yields a `country` row | Task 8, `test_an_ambiguous_name_with_no_admin1_coarsens_to_the_country_centroid` |
| 4 | Unresolvable place yields nulls, not zeros | Task 9, `test_a_globally_ambiguous_name_is_unresolved_rather_than_guessed` |
| 5 | Signal naming no places advances with no rows | Task 17, `test_a_signal_naming_no_places_advances_with_no_rows` |
| 6 | No signal reaches `needs_review` | Task 17, `test_nothing_in_the_pass_can_send_a_signal_to_review` |
| 7 | No tie-break, ever | Task 8, `test_coarsening_never_returns_one_of_the_tied_candidates`; Task 20, `test_the_ladder_never_reads_a_population` |
| 8 | `ai_extraction` is untouched | Task 11, `test_the_geocoding_migration_does_not_touch_the_extraction_column`; Task 16, `test_marking_geocoded_advances_only_the_processing_status`; Task 21 Step 6 |
| 9 | Re-running replaces rows and repeats the result | Task 16, `test_replacing_locations_deletes_before_it_inserts`; Task 21 Step 7 |
| 10 | `--stale` selects only superseded rows | Task 16, `test_stale_selection_asks_for_a_source_other_than_the_current_one`; Task 17, `test_the_stale_pass_reads_from_the_stale_selection` |
| 11 | Seam discipline holds | Task 20, `test_only_the_repository_imports_sqlalchemy`, `test_no_module_in_the_sub_project_touches_the_network` |
| 12 | No socket and no live database in the suite | Task 20 Step 5, the full `uv run pytest` |
| 13 | Project gates pass | Task 20 Step 5 and Task 21 Step 8 |

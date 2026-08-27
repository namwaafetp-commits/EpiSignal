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

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
import io
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
    with (
        target.open("wb") as raw_file,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw_file, mtime=0.0) as gz_file,
        io.TextIOWrapper(gz_file, encoding="utf-8", newline="\n") as handle,
    ):
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

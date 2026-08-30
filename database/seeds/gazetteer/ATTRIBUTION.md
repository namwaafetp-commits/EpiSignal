# Gazetteer Attribution

`database/seeds/gazetteer_places.tsv.gz` is derived from the GeoNames geographical
database, specifically `countryInfo.txt`, `admin1CodesASCII.txt`, `admin2Codes.txt`,
and `cities1000.txt` from https://download.geonames.org/export/dump/.

GeoNames data is licensed under Creative Commons Attribution 4.0
(https://creativecommons.org/licenses/by/4.0/). The derivation is performed by
`scripts/build_gazetteer.py`, which normalizes names and flattens the four files
into one table; no coordinate or identifier is altered.

"""Coordinates for places and addresses (data/coordinates.tsv), looked up offline in GeoNames and
OpenStreetMap downloads, so no address from the tree is sent to a geocoding service.

Precision follows what the source allows: an exact address point only for a street and house
number from about 1940 on that still exists (older numbers have been renumbered), otherwise the
hamlet or street, otherwise the place. Ward numbers ("wijk A nr. 73") stay on the place.
"""

from __future__ import annotations

import csv
import io
import math
import re
import shutil
import sqlite3
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .i18n import t
from .web import BROWSER_UA

TABLE = Path("data/coordinates.tsv")
LEGACY_TABLE = "coordinaten.tsv"
COLUMNS = ["place", "address", "lat", "lon", "level", "origin", "remark"]
LEGACY_COLUMNS = {
    "plaats": "place",
    "adres": "address",
    "niveau": "level",
    "herkomst": "origin",
    "toelichting": "remark",
}
CACHE = Path("~/.cache/lineage/geo").expanduser()
LEGACY_CACHE = Path("~/.cache/ndygen/geo").expanduser()
DB = CACHE / "geo.sqlite"
GEONAMES = ("NL", "BE", "DE", "ID")
# Streets and addresses for the Netherlands; only place names across the borders.
OSM_FULL = ("europe/netherlands",)
OSM_PLACES = (
    "europe/belgium",
    "europe/germany/nordrhein-westfalen/koeln-regbez",
    "europe/germany/nordrhein-westfalen/duesseldorf-regbez",
    "europe/germany/rheinland-pfalz",
)
EXACT_FROM = 1940
LEVEL_ADDRESS, LEVEL_STREET, LEVEL_HAMLET, LEVEL_PLACE = (
    "address",
    "street",
    "hamlet/neighbourhood",
    "place",
)
OSM_CENTERS = (
    "city",
    "town",
    "village",
    "hamlet",
    "suburb",
    "neighbourhood",
    "locality",
    "isolated_dwelling",
)
SCHEMA = """
DROP TABLE IF EXISTS place; DROP TABLE IF EXISTS road; DROP TABLE IF EXISTS address;
CREATE TABLE place (name TEXT, lat REAL, lon REAL, kind TEXT, area TEXT, population INT, origin TEXT);
CREATE TABLE road (name TEXT, lat REAL, lon REAL, origin TEXT);
CREATE TABLE address (street TEXT, number TEXT, place TEXT, lat REAL, lon REAL, origin TEXT);
"""
RADIUS_HAMLET, RADIUS_STREET, RADIUS_ADDRESS = 5.0, 3.0, 3.0
PROVINCE = {
    "Drenthe": "NL.01", "Friesland": "NL.02", "Gelderland": "NL.03", "Groningen": "NL.04",
    "Limburg": "NL.05", "Noord-Brabant": "NL.06", "Noord-Holland": "NL.07", "Utrecht": "NL.09",
    "Zeeland": "NL.10", "Zuid-Holland": "NL.11", "Overijssel": "NL.15", "Flevoland": "NL.16",
    "Rijnland-Palts": "DE.08", "Noordrijn-Westfalen": "DE.07", "Nordrhein-Westfalen": "DE.07",
    "Antwerpen": "BE.VLG", "Oost-Vlaanderen": "BE.VLG", "West-Vlaanderen": "BE.VLG",
    "Vlaams-Brabant": "BE.VLG", "Luik": "BE.WAL", "Henegouwen": "BE.WAL", "Namen": "BE.WAL",
}  # fmt: skip
COUNTRY = {
    "Nederland": "NL", "Netherlands": "NL", "België": "BE", "Belgium": "BE",
    "Duitsland": "DE", "Deutschland": "DE", "Germany": "DE", "Nederlands-Indië": "ID",
}  # fmt: skip


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float
    level: str
    origin: str
    remark: str = ""
    distance: float = 0.0

    def row(self, place: str, address: str = "") -> list[str]:
        return [
            place,
            address,
            f"{self.lat:.6f}",
            f"{self.lon:.6f}",
            self.level,
            self.origin,
            self.remark,
        ]


# --- the table -------------------------------------------------------------------------------


def table_for(gedcom: Path) -> Path:
    """The table next to the GEDCOM; a Dutch-named table is used while no new one exists."""
    path = gedcom.with_name(TABLE.name)
    legacy = gedcom.with_name(LEGACY_TABLE)
    return legacy if not path.exists() and legacy.exists() else path


def read(path: Path = TABLE) -> dict[tuple[str, str], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        rows = (
            {LEGACY_COLUMNS.get(key, key): value for key, value in raw.items()}
            for raw in csv.DictReader(f, delimiter="\t")
        )
        return {(r["place"], r["address"]): r for r in rows}


def write(rows: dict[tuple[str, str], dict[str, str]], path: Path = TABLE) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(COLUMNS)
        for key in sorted(rows):
            w.writerow([rows[key].get(k, "") for k in COLUMNS])


def missing_places(place_names: set[str], path: Path = TABLE) -> list[str]:
    """Place names without any row; a row without coordinates but with a reason counts as done."""
    if not path.exists():
        return []
    known = {p for p, address in read(path) if not address}
    return sorted(place_names - known)


# --- the index -------------------------------------------------------------------------------


def _download(url: str, target: Path) -> None:
    # Hundreds of megabytes: streamed to disk, not through lineage.web.fetch, which reads into memory.
    if target.exists():
        return
    earlier = LEGACY_CACHE / target.name
    if earlier.exists():
        target.symlink_to(earlier)
        return
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as f:
        shutil.copyfileobj(response, f, 1 << 20)
    partial.rename(target)


def build_index(notify=print) -> None:
    import osmium  # only needed to build the index

    CACHE.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(CACHE / "geo.sqlite.part")
    db.executescript(SCHEMA)
    for country in GEONAMES:
        notify(f"GeoNames {country}")
        zip_path = CACHE / f"{country}.zip"
        _download(f"https://download.geonames.org/export/dump/{country}.zip", zip_path)
        with zipfile.ZipFile(zip_path) as z, z.open(f"{country}.txt") as f:
            rows = []
            for r in csv.reader(
                io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE
            ):
                if r[6] == "P" or (r[6] == "A" and r[7] in ("ADM2", "ADM3")):
                    area = f"{r[8]}.{r[10]}"
                    for name in {r[1], r[2], *(r[3].split(",") if r[6] == "P" else [])}:
                        if name:
                            rows.append(
                                (
                                    name.lower(),
                                    float(r[4]),
                                    float(r[5]),
                                    r[7],
                                    area,
                                    int(r[14] or 0),
                                    f"geonames:{r[0]}",
                                )
                            )
            db.executemany("INSERT INTO place VALUES (?,?,?,?,?,?,?)", rows)

    class Reader(osmium.SimpleHandler):
        def __init__(self, full: bool):
            super().__init__()
            self.full = full

        def _place(self, t, lat, lon, oid):
            if "place" in t and t.get("name"):
                db.execute(
                    "INSERT INTO place VALUES (?,?,?,?,?,?,?)",
                    (t["name"].lower(), lat, lon, t["place"], "", 0, f"osm:{oid}"),
                )

        def _address(self, t, lat, lon, oid):
            if self.full and "addr:housenumber" in t and t.get("addr:street"):
                db.execute(
                    "INSERT INTO address VALUES (?,?,?,?,?,?)",
                    (
                        t["addr:street"].lower(),
                        t["addr:housenumber"].lower(),
                        t.get("addr:city", "").lower(),
                        lat,
                        lon,
                        f"osm:{oid}",
                    ),
                )

        def node(self, n):
            if n.tags:
                self._place(n.tags, n.location.lat, n.location.lon, f"node/{n.id}")
                self._address(n.tags, n.location.lat, n.location.lon, f"node/{n.id}")

        def way(self, w):
            t = w.tags
            if not ("place" in t or "highway" in t or "addr:housenumber" in t):
                return
            points = [(nd.location.lat, nd.location.lon) for nd in w.nodes if nd.location.valid()]
            if not points:
                return
            middle = points[len(points) // 2]
            centroid = (
                sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points),
            )
            self._place(t, *centroid, f"way/{w.id}")
            self._address(t, *centroid, f"way/{w.id}")
            if self.full and "highway" in t and t.get("name"):
                # A point on the street itself; a centroid can fall beside a curved street.
                db.execute(
                    "INSERT INTO road VALUES (?,?,?,?)",
                    (t["name"].lower(), *middle, f"osm:way/{w.id}"),
                )

    for area, full in [(g, True) for g in OSM_FULL] + [(g, False) for g in OSM_PLACES]:
        notify(t("OpenStreetMap {area} (this takes a while)", area=area))
        pbf = CACHE / f"{area.replace('/', '-')}.osm.pbf"
        _download(f"https://download.geofabrik.de/{area}-latest.osm.pbf", pbf)
        Reader(full).apply_file(str(pbf), locations=True, idx="flex_mem")
        db.commit()
    db.executescript(
        """
        CREATE INDEX place_name ON place(name); CREATE INDEX road_name ON road(name);
        CREATE INDEX address_street ON address(street, number);
        """
    )
    db.commit()
    db.close()
    (CACHE / "geo.sqlite.part").rename(DB)


# --- looking up ------------------------------------------------------------------------------


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot((a[0] - b[0]) * 111.2, (a[1] - b[1]) * 111.2 * math.cos(math.radians(a[0])))


def _db() -> sqlite3.Connection:
    if not DB.exists():
        raise SystemExit(t("No index; build it first with: uv run lineage coordinates index"))
    return sqlite3.connect(DB)


def find_place(place: str, db: sqlite3.Connection | None = None) -> list[Point]:
    """Candidates for a place as written in the GEDCOM ("Dongen, Noord-Brabant, Nederland"),
    best first. Several candidates far apart mean the name is ambiguous."""
    db = db or _db()
    parts = [d.strip() for d in place.split(",")]
    country = COUNTRY.get(parts[-1]) if len(parts) > 1 else None
    area = PROVINCE.get(parts[-2]) if len(parts) >= 3 else None
    if len(parts) >= 4 and area:
        # "Klein-Dongen, Dongen, Noord-Brabant, Nederland": a hamlet near its municipality.
        for center in find_place(", ".join(parts[1:]), db)[:1]:
            nearby = _nearby(db, "place", parts[0], (center.lat, center.lon), RADIUS_HAMLET)
            nearby += _nearby(db, "road", parts[0], (center.lat, center.lon), RADIUS_STREET)
            if nearby:
                return nearby
            return [
                Point(
                    center.lat,
                    center.lon,
                    LEVEL_PLACE,
                    center.origin,
                    t("as {place}; {name} not found", place=parts[1], name=parts[0]),
                )
            ]
    rows = db.execute(
        "SELECT lat, lon, kind, area, population, origin FROM place WHERE name = ?",
        (parts[0].lower(),),
    ).fetchall()
    geonames = [r for r in rows if r[5].startswith("geonames:")]
    if country:
        geonames = [r for r in geonames if r[3].startswith(country + ".")]
    if area:
        geonames = [r for r in geonames if r[3] == area] or geonames
    # Populated places before municipalities, the bigger one first.
    geonames.sort(key=lambda r: (not r[2].startswith("PPL"), -r[4]))
    candidates = [Point(r[0], r[1], LEVEL_PLACE, r[5]) for r in geonames]
    if not candidates or not area:
        # Without a province GeoNames alone can miss the right one (Oberhaid in the Westerwald).
        candidates += [
            Point(r[0], r[1], LEVEL_PLACE, r[5])
            for r in rows
            if r[5].startswith("osm:") and r[2] in OSM_CENTERS
        ]
    # Drop the same place found twice (village and municipality, GeoNames and OSM).
    unique: list[Point] = []
    for k in candidates:
        if all(distance((k.lat, k.lon), (u.lat, u.lon)) > 3 for u in unique):
            unique.append(k)
    return unique


def _nearby(db, table: str, name: str, near: tuple[float, float], radius: float) -> list[Point]:
    level = LEVEL_HAMLET if table == "place" else LEVEL_STREET
    rows = db.execute(
        f"SELECT lat, lon, origin FROM {table} WHERE name = ?", (name.lower(),)
    ).fetchall()
    points = [Point(r[0], r[1], level, r[2], distance=distance(near, (r[0], r[1]))) for r in rows]
    return sorted((p for p in points if p.distance < radius), key=lambda p: p.distance)[:1]


_NUMBER = re.compile(r"^(?P<street>.*?[a-zë'.]{2,})\s+(?P<number>\d+\s?[a-z]?)\b", re.I)
_WARD = re.compile(r"^(wijk|huis|huizing|nr|n°|no|nummer|lett)\b|^[a-z]\s*\d", re.I)
_PREPOSITION = re.compile(
    r"^(gehucht|hoeve|wijk|op|aen|aan|achter|in|bij|opt)\s+(de|den|het|'t)?\s*", re.I
)


def find_address(
    place: str, address: str, year: int | None = None, db: sqlite3.Connection | None = None
) -> Point | None:
    """The most precise point for an address in a place, or None (then it stays on the place)."""
    db = db or _db()
    center = next(iter(find_place(place, db)), None)
    if not center:
        return None
    near = (center.lat, center.lon)
    first = re.split(r"[;,(]", address)[0].strip()
    m = _NUMBER.match(first)
    if m and year and year >= EXACT_FROM:
        street, number = m["street"].strip(), m["number"].replace(" ", "").lower()
        rows = db.execute(
            "SELECT lat, lon, origin FROM address WHERE street = ? AND number = ?",
            (street.lower(), number),
        ).fetchall()
        nearby = sorted((distance(near, (r[0], r[1])), r) for r in rows)
        if nearby and nearby[0][0] < RADIUS_ADDRESS:
            r = nearby[0][1]
            return Point(r[0], r[1], LEVEL_ADDRESS, r[2])
    if _WARD.match(first):
        return None
    name = re.sub(r"\s*\d.*$", "", first)
    name = re.sub(r"\s+[A-Z]$", "", name).strip(" .'\"")
    for candidate in dict.fromkeys([name, _PREPOSITION.sub("", name).strip()]):
        if len(candidate) > 2:
            found = _nearby(db, "place", candidate, near, RADIUS_HAMLET)
            found = found or _nearby(db, "road", candidate, near, RADIUS_STREET)
            if found:
                return found[0]
    return None


# --- filling the table from the tree ---------------------------------------------------------


@dataclass
class Fill:
    added: list[list[str]]
    doubtful: list[tuple[str, list[Point]]]
    not_found: list[str]


def fill(places: list[dict], years: dict[str, int], table: dict) -> Fill:
    """Rows for every place and address without one. An ambiguous place name (candidates more
    than 15 km apart) is not filled in but reported; that choice needs the context."""
    db = _db()
    out = Fill([], [], [])
    titles = sorted({p["title"] for p in places})
    for title in titles:
        if (title, "") in table:
            continue
        candidates = find_place(title, db)
        if not candidates:
            out.not_found.append(title)
        elif (
            len(candidates) > 1
            and distance(
                (candidates[0].lat, candidates[0].lon), (candidates[1].lat, candidates[1].lon)
            )
            > 15
        ):
            out.doubtful.append((title, candidates))
        else:
            row = candidates[0].row(title)
            table[(title, "")] = dict(zip(COLUMNS, row, strict=True))
            out.added.append(row)
    seen = set()
    for p in places:
        address = (p.get("alt_loc") or [{}])[0].get("street", "")
        key = (p["title"], address)
        if not address or key in table or key in seen or (p["title"], "") not in table:
            continue
        seen.add(key)
        point = find_address(p["title"], address, years.get(p["handle"]), db)
        if point:
            row = point.row(*key)
            table[key] = dict(zip(COLUMNS, row, strict=True))
            out.added.append(row)
    return out


def years_per_place(objects: list[dict]) -> dict[str, int]:
    """The latest year an event took place at each place: decides whether a house number can
    still be today's."""
    years: dict[str, int] = defaultdict(int)
    for obj in objects:
        if obj["_class"] == "Event" and obj.get("place"):
            year = (obj.get("date") or {}).get("dateval", [0, 0, 0])[2]
            if isinstance(year, int):
                years[obj["place"]] = max(years[obj["place"]], year)
    return dict(years)

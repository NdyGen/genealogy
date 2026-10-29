import sqlite3

import pytest

from lineage import coordinates


@pytest.fixture
def db():
    db = sqlite3.connect(":memory:")
    db.executescript(coordinates.SCHEMA)
    db.executemany(
        "INSERT INTO place VALUES (?,?,?,?,?,?,?)",
        [
            ("exampleton", 51.6267, 4.9389, "PPL", "NL.06", 20000, "geonames:1"),
            ("sampleford", 51.4233, 5.5222, "PPL", "NL.06", 115, "geonames:2"),
            ("sampleford", 51.5258, 5.0236, "PPL", "NL.06", 0, "geonames:3"),
            ("klein-exampleton", 51.6426, 4.9606, "hamlet", "", 0, "osm:node/4"),
        ],
    )
    db.executemany(
        "INSERT INTO road VALUES (?,?,?,?)",
        [
            ("kerkstraat", 51.6229, 4.9357, "osm:way/5"),
            ("kerkstraat", 51.6871, 4.9083, "osm:way/6"),
        ],
    )
    db.execute(
        "INSERT INTO address VALUES (?,?,?,?,?,?)",
        ("kerkstraat", "12", "exampleton", 51.6231, 4.9360, "osm:node/7"),
    )
    return db


EXAMPLETON = "Exampleton, Noord-Brabant, Nederland"


def test_place(db):
    [point] = coordinates.find_place(EXAMPLETON, db)
    assert (point.lat, point.level, point.origin) == (51.6267, "place", "geonames:1")


def test_namesakes_are_both_named(db):
    assert len(coordinates.find_place("Sampleford, Noord-Brabant, Nederland", db)) == 2


def test_hamlet_near_its_municipality(db):
    [point] = coordinates.find_place("Klein-Exampleton, " + EXAMPLETON, db)
    assert (point.level, point.origin) == ("hamlet/neighbourhood", "osm:node/4")


def test_street_nearest_to_the_center(db):
    point = coordinates.find_address(EXAMPLETON, "Kerkstraat", db=db)
    assert point.origin == "osm:way/5"


def test_exact_house_number_only_from_1940(db):
    assert coordinates.find_address(EXAMPLETON, "Kerkstraat 12", 1955, db).level == "address"
    assert coordinates.find_address(EXAMPLETON, "Kerkstraat 12", 1910, db).level == "street"


def test_ward_number_stays_on_the_place(db):
    assert coordinates.find_address(EXAMPLETON, "wijk A nr. 73", 1900, db) is None
    assert coordinates.find_address(EXAMPLETON, "A 122", 1900, db) is None


def test_table_round_trip(tmp_path):
    path = tmp_path / "coordinates.tsv"
    rows = {
        (EXAMPLETON, ""): dict(
            zip(coordinates.COLUMNS, [EXAMPLETON, "", "51.6", "4.9", "place", "x", ""], strict=True)
        )
    }
    coordinates.write(rows, path)
    assert path.read_text().splitlines()[0] == "place\taddress\tlat\tlon\tlevel\torigin\tremark"
    assert coordinates.read(path) == rows
    assert coordinates.missing_places({EXAMPLETON, "Samplecity"}, path) == ["Samplecity"]


def test_table_with_dutch_header_is_read(tmp_path):
    path = tmp_path / "coordinaten.tsv"
    path.write_text(
        "plaats\tadres\tlat\tlon\tniveau\therkomst\ttoelichting\n"
        f"{EXAMPLETON}\t\t51.6\t4.9\tplaats\tx\t\n",
        encoding="utf-8",
    )
    row = coordinates.read(path)[(EXAMPLETON, "")]
    assert (row["level"], row["origin"], row["remark"]) == ("plaats", "x", "")


def test_table_for_prefers_the_new_name_and_falls_back_to_the_old(tmp_path):
    gedcom = tmp_path / "tree.ged"
    assert coordinates.table_for(gedcom) == tmp_path / "coordinates.tsv"
    (tmp_path / "coordinaten.tsv").write_text("x")
    assert coordinates.table_for(gedcom) == tmp_path / "coordinaten.tsv"
    (tmp_path / "coordinates.tsv").write_text("x")
    assert coordinates.table_for(gedcom) == tmp_path / "coordinates.tsv"

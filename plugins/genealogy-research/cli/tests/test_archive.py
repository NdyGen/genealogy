import dataclasses
import json
from pathlib import Path

import pytest

from lineage import archive

FIXTURES = Path(__file__).parent / "fixtures"
REF = "bhi:7c3d9e20-1111-4222-8333-444455556666"


@pytest.fixture
def offline(monkeypatch):
    def fake_get(endpoint, params):
        name = "marriage" if endpoint == "show" else "search"
        return json.loads((FIXTURES / f"openarch-{name}.json").read_text())

    monkeypatch.setattr(archive, "_get", fake_get)


def test_search_hits(offline):
    total, hits = archive.search("Pieter Dekkers 1887", event="Huwelijk")
    assert total == 2
    assert hits[0].event == "Huwelijk"
    assert hits[0].date == "14-9-1887"
    assert ":" in hits[0].ref


def test_show_record(offline):
    record = archive.show(REF)
    assert (record.source_type, record.date, record.place) == (
        "BS Huwelijk",
        "14-9-1887",
        "Heuvelwijk",
    )
    assert (record.deed, record.inventory, record.archive_number) == ("7", "812", "77")
    roles = {p.role: p for p in record.persons}
    assert roles["Bruid"].name == "Maria van Berkel"
    assert roles["Bruid"].age == "19"
    assert roles["Moeder van de bruid"].name == "Wilhelmina Peeters"
    assert record.remarks == []


def test_citation_is_deterministic_and_traceable(offline):
    record = archive.show(REF)
    assert record.source_xref == archive.show(REF).source_xref
    assert len(record.source_xref) <= 20
    citation = record.gedcom_citation()
    assert citation.splitlines() == [
        f"2 SOUR @{record.source_xref}@",
        "3 PAGE record 7, 14-9-1887, archive 77, inv. 812; "
        "https://www.openarchieven.nl/bhi:7c3d9e20-1111-4222-8333-444455556666",
        "3 QUAY 3",
    ]
    assert record.gedcom_source().startswith(
        f"0 @{record.source_xref}@ SOUR\n1 TITL BS Huwelijk Heuvelwijk"
    )


def test_show_requires_archive_prefix():
    with pytest.raises(archive.ArchiveError):
        archive.show("7c3d9e20")


def test_other_prefix_is_left_out_of_the_title_but_keeps_the_id(offline):
    record = dataclasses.replace(
        archive.show(REF), source_type="other:Rechterlijke archieven", place="Veldhoek"
    )
    assert "1 TITL Rechterlijke archieven Veldhoek" in record.gedcom_source()
    plain = dataclasses.replace(record, source_type="Rechterlijke archieven")
    assert record.source_xref != plain.source_xref

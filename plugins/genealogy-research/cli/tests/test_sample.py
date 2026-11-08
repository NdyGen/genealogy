import pytest

from lineage import archive, sample
from lineage.archive import Record, RecordPerson
from lineage.gedcom import parse
from tests.conftest import ged

OA = "https://www.openarchieven.nl/abc:11111111-2222-3333-4444-555555555555"
REF = "abc:11111111-2222-3333-4444-555555555555"


def _cite(page: str = OA, quay: str = "3") -> list[str]:
    return ["2 SOUR @S1@", f"3 PAGE {page}", f"3 QUAY {quay}"]


def _child(*lines: str) -> str:
    return "\n".join(["0 @I1@ INDI", "1 NAME Jan /Dekkers/", "1 CHR", "2 DATE 1 FEB 1850", "2 PLAC Breda",
                      *_cite(), *lines])  # fmt: skip


PARENTS = "\n".join([
    "0 @I2@ INDI", "1 NAME Piet /Dekkers/", "1 FAMS @F1@",
    "0 @I3@ INDI", "1 NAME Kee /Smit/", "1 FAMS @F1@",
    "0 @F1@ FAM", "1 HUSB @I2@", "1 WIFE @I3@", "1 CHIL @I1@",
])  # fmt: skip


@pytest.fixture
def records(monkeypatch):
    found = {
        REF: Record(
            archive="abc", identifier="x", source_type="DTB Dopen", event="Doop", date="1-2-1850", place="Breda",
            institution="Stadsarchief", date_parts=(1, 2, 1850),
            persons=[RecordPerson("Dopeling", "Jan Dekkers"), RecordPerson("Vader", "Piet Dekkers"),
                     RecordPerson("Moeder", "Kee Smit")],
        )
    }  # fmt: skip

    def show(ref, offline=False):
        if ref not in found:
            raise archive.RecordNotFound(f"record {ref} not found")
        return found[ref]

    monkeypatch.setattr(archive, "show", show)
    return found


def test_a_changed_date_is_a_correction_a_new_fact_is_not():
    old = ged(_child())
    new = ged(_child().replace("1 FEB 1850", "2 FEB 1850") + "\n1 DEAT\n2 DATE 1900\n" + "\n".join(_cite()))
    assert sample.corrections(old, new) == {("I1", "CHR")}


def test_an_uncited_new_link_brings_in_the_childs_baptism(records):
    old = ged(_child(), PARENTS.replace("1 CHIL @I1@", ""))
    new = ged(_child("1 FAMC @F1@"), PARENTS)
    [pick] = sample.candidates(old, new, parse(new))
    assert pick.ref == REF and sample.LINK in pick.reasons
    assert [link.label for link in pick.links] == ["I1 FAMC @F1@"]


def test_the_same_seed_gives_the_same_sample_and_links_weigh_more():
    picks = [sample.Pick("oa", f"r{i}") for i in range(9)] + [sample.Pick("oa", "link", reasons={sample.LINK})]
    assert sample.choose(picks, 3, "I1 abc") == sample.choose(picks, 3, "I1 abc")
    hits = sum(sample.choose(picks, 1, str(seed))[0].ref == "link" for seed in range(400))
    assert hits > 400 / 10 * 2


def test_record_and_fact_side_by_side(records):
    old = ged(_child(), PARENTS.replace("1 CHIL @I1@", ""))
    new = ged(_child("1 FAMC @F1@"), PARENTS)
    text = sample.sample(old, new, 3, seed="x", offline=True)
    lines = text.splitlines()
    assert any("DATE 1 FEB 1850" in line and "Stadsarchief" in line for line in lines)
    assert any("Vader: Piet Dekkers" in line for line in lines)
    assert any("Piet Dekkers x Kee Smit" in line for line in lines)
    assert "verify: I1 CHR supported" in text


def test_a_scan_shows_the_leads_reading(records):
    page = "RAT 929 (Schepenbank) inv. 145 p. 251 (scans 0255-0259), deling 1742"
    new = ged(
        "\n".join(["0 @I1@ INDI", "1 NAME Jan /Dekkers/", "1 EVEN", "2 TYPE Deling", "2 DATE 1742", *_cite(page),
                   "2 NOTE Gelezen: Jan Dekkers krijgt een derde deel."])
    )  # fmt: skip
    text = sample.sample(ged("0 @I1@ INDI\n1 NAME Jan /Dekkers/"), new, 1, seed="x")
    assert "open the scan: rat:929-145/0255" in text and "krijgt een derde deel" in text
    assert "TYPE Deling" in text


def test_no_cited_record():
    text = ged("0 @I1@ INDI\n1 NAME Jan /Dekkers/")
    assert sample.sample(text, text, 3, seed="x") == "sample: no cited record in this round"

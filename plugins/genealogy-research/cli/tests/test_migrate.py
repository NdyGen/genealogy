import shutil
import stat

import pytest

from lineage import credentials, migrate, queue, requests, settings
from tests.conftest import FIXTURE

REQUEST = """---
aan: info@archive.example.org
onderwerp: Burial register
personen: I1
aangemaakt: 2026-10-02
afzender: andy
status: verstuurd
---
Dear archivist,

## Achtergrond
Only for us.
"""


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "LEGACY_CONFIG_DIR", str(tmp_path / "home/ndygen"))
    monkeypatch.setattr(credentials, "CONFIG_DIR", str(tmp_path / "home/lineage"))
    root = tmp_path / "project"
    (root / "data").mkdir(parents=True)
    shutil.copy(FIXTURE, root / "data/stamboom.ged")
    (root / "data/coordinaten.tsv").write_text(
        "plaats\tadres\tlat\tlon\tniveau\therkomst\ttoelichting\n"
        "Northfield\t\t51.1\t4.2\tplaats\tgeonames:1\t\n"
        "Northfield\t\t51.1\t4.2\tplaats\tgeonames:1\ta duplicate row stays\n"
    )
    research = root / "onderzoek"
    (research / "aanvragen").mkdir(parents=True)
    (research / "aanvragen/2026-10-02-burial.md").write_text(REQUEST)
    (research / "wachtrij.tsv").write_text(
        "id\tstatus\tprioriteit\tronde\tdoor\treden\ttoegevoegd\tidreeks\trapport\n"
        "I2\tklaar\t1\t1\t\tfather\t2026-10-01\t800001-800999\trapporten/personen/I2.md\n"
        "I3\topen\t5\t1\tI2\tmother\t2026-10-01\t\t\n"
    )
    (research / "verwant.tsv").write_text("# targets\nJohn\tI1\n")
    (research / "stammen.tsv").write_text("# stems\nMiller\tI2\tmannen-eerst\n")
    (research / "vragenkaart.tsv").write_text("datum\topen\tkeuze\n2026-10-29\t3\t1\n")
    (root / "rapporten/levensverhalen").mkdir(parents=True)
    (tmp_path / "home/ndygen").mkdir(parents=True)
    (tmp_path / "home/ndygen/gramps.env").write_text(
        "NDYGEN_GRAMPS_GEBRUIKER=claude\nNDYGEN_GRAMPS_WACHTWOORD=x\n"
    )
    return root


def test_plan_keeps_the_dutch_names(legacy):
    p = migrate.plan(legacy, settings.Config(root=legacy, language="nl"))
    c = p.config
    assert c.language == "nl" and c.rel("gedcom").as_posix() == "data/stamboom.ged"
    assert c.rel("queue").as_posix() == "onderzoek/wachtrij.tsv"
    assert c.rel("life_stories").as_posix() == "rapporten/levensverhalen"
    assert c.rel("scans").as_posix() == "bronnen/scans/opgehaald"
    assert c.rel("output").as_posix() == "uitvoer"
    assert c.rel("replies").as_posix() == "onderzoek/aanvragen/antwoorden"
    assert c.targets == (settings.Target("John", "I1"),)
    assert c.stems == (settings.Stem("Miller", "I2", men_first=True),)
    assert not (legacy / "lineage.toml").exists()
    assert "remove onderzoek/verwant.tsv (now in lineage.toml)" in p.lines(legacy)


def test_apply_converts_the_files(legacy):
    migrate.apply(
        migrate.plan(
            legacy, settings.Config(root=legacy, language="nl", own_address="me@example.org")
        )
    )
    c = settings.load(legacy)
    assert c.own_address == "me@example.org" and c.root_person == "I1"
    items = queue.load(c.path("queue"))
    assert items["I2"].status == "done" and items["I2"].id_block == "800001-800999"
    lines = c.path("queue").read_text().splitlines()
    assert lines[0].startswith("id\tstatus\tpriority\tround\tvia") and lines[1].startswith(
        "I2\tdone\t1"
    )
    request = requests.read(c.path("requests") / "2026-10-02-burial.md")
    assert request.status == "sent" and request.fields["sender"] == "user"
    text = (c.path("requests") / "2026-10-02-burial.md").read_text()
    assert (
        text.startswith("---\nto: info@archive.example.org\nsubject:") and "## Achtergrond" in text
    )
    rows = (legacy / "data/coordinaten.tsv").read_text().splitlines()
    assert len(rows) == 3 and [r.split("\t")[4] for r in rows[1:]] == ["place", "place"]
    assert c.path("question_history").read_text().startswith("date\topen\tchoice")
    assert not (legacy / "onderzoek/verwant.tsv").exists()
    new = legacy.parent / "home/lineage/gramps.env"
    assert new.read_text() == "LINEAGE_GRAMPS_USER=claude\nLINEAGE_GRAMPS_PASSWORD=x\n"
    assert stat.S_IMODE(new.stat().st_mode) == 0o600


def test_a_migrated_project_is_left_alone(legacy):
    migrate.apply(migrate.plan(legacy, settings.Config(root=legacy, language="nl")))
    with pytest.raises(settings.ConfigError, match="already migrated"):
        migrate.plan(legacy, settings.Config(root=legacy, language="nl"))


def test_header_rewrite_leaves_english_files_unchanged():
    english = "---\nto: x@example.org\nstatus: draft\n---\nbody: text\n"
    assert (
        migrate.rewrite_header(english, requests.LEGACY_KEYS, requests.LEGACY_STATUSES) == english
    )


def test_cli_shows_the_plan_and_applies_it(legacy, monkeypatch, capsys):
    from lineage.cli import main

    monkeypatch.chdir(legacy)
    assert main(["migrate", "--sender-name", "Ann Doe"]) == 0
    assert "onderzoek/wachtrij.tsv omzetten" in capsys.readouterr().out
    assert not (legacy / "lineage.toml").exists()
    assert main(["migrate", "--apply", "--sender-name", "Ann Doe"]) == 0
    c = settings.load(legacy)
    assert c.sender_name == "Ann Doe" and c.language == "nl"

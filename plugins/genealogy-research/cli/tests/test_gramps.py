import json

import pytest

from lineage import gramps
from tests.conftest import project

QUESTIONS = """# Open vragen

## Keuzes voor de gebruiker

### Coördinatie

- [ ] I5 Maria: **keuze** voor `Ann` (coördinator)

## Uit te zoeken met online bronnen

### Overig

- [ ] I1 Peter en F1: doop niet gevonden
- [x] I2 Piet: overlijden gevonden

## Levende personen of recent (niet opzoeken)

- [ ] I3 Jan: niet opzoeken
"""

ENGLISH_QUESTIONS = """# Open questions

## Choices for the user

- [ ] I5 Maria: choice

## To research with online sources

- [ ] I1 Peter: baptism not found
- [x] I2 Piet: death found

## On site only or with a full-resolution scan

- [ ] I4 Kees: needs the original

## Living persons or recent (do not look up)

- [ ] I3 Jan: do not look up
"""


class Server:
    def __init__(self):
        self.logins = 0
        self.expired = False

    def __call__(self, method, url, data, headers):
        if url.endswith("/api/token/"):
            self.logins += 1
            return 200, json.dumps({"access_token": f"t{self.logins}"}).encode()
        if self.expired:
            self.expired = False
            return 401, b'{"error": {"message": "expired"}}'
        return 200, b"[]"


@pytest.fixture
def server():
    return Server()


@pytest.fixture
def g(server):
    cfg = {
        "LINEAGE_GRAMPS_URL": "http://gramps.example.org",
        "LINEAGE_GRAMPS_USER": "claude",
        "LINEAGE_GRAMPS_PASSWORD": "secret",
    }
    return gramps.Gramps(cfg, transport=server)


def test_config_from_file(tmp_path, monkeypatch):
    project(tmp_path, gramps_url="https://gramps.example.org")
    cfg = tmp_path / "gramps.env"
    cfg.write_text("# x\nLINEAGE_GRAMPS_USER=claude\nLINEAGE_GRAMPS_PASSWORD=secret\n")
    monkeypatch.setenv("LINEAGE_GRAMPS_CONFIG", str(cfg))
    values = gramps.config()
    assert values["LINEAGE_GRAMPS_URL"] == "https://gramps.example.org"
    assert values["LINEAGE_GRAMPS_USER"] == "claude"


def test_config_needs_a_server(tmp_path, monkeypatch):
    project(tmp_path)
    cfg = tmp_path / "gramps.env"
    cfg.write_text("LINEAGE_GRAMPS_USER=claude\nLINEAGE_GRAMPS_PASSWORD=secret\n")
    monkeypatch.setenv("LINEAGE_GRAMPS_CONFIG", str(cfg))
    monkeypatch.delenv("LINEAGE_GRAMPS_URL", raising=False)
    with pytest.raises(gramps.GrampsError, match=r"\[gramps\] url"):
        gramps.config()
    monkeypatch.setenv("LINEAGE_GRAMPS_URL", "https://other.example.org")
    assert gramps.config()["LINEAGE_GRAMPS_URL"] == "https://other.example.org"


def test_config_reads_the_old_keys(tmp_path, monkeypatch):
    project(tmp_path, gramps_url="https://gramps.example.org")
    cfg = tmp_path / "gramps.env"
    cfg.write_text("NDYGEN_GRAMPS_GEBRUIKER=claude\nNDYGEN_GRAMPS_WACHTWOORD=secret\n")
    monkeypatch.setenv("LINEAGE_GRAMPS_CONFIG", str(cfg))
    values = gramps.config()
    assert (values["LINEAGE_GRAMPS_USER"], values["LINEAGE_GRAMPS_PASSWORD"]) == ("claude", "secret")


def test_config_without_password(tmp_path, monkeypatch):
    monkeypatch.setenv("LINEAGE_GRAMPS_CONFIG", str(tmp_path / "missing.env"))
    monkeypatch.delenv("LINEAGE_GRAMPS_USER", raising=False)
    monkeypatch.delenv("NDYGEN_GRAMPS_GEBRUIKER", raising=False)
    with pytest.raises(gramps.GrampsError, match="USER"):
        gramps.config()


def test_login_again_after_token_expiry(g, server):
    g.api("GET", "tags/")
    server.expired = True
    g.api("GET", "tags/")
    assert server.logins == 2


def test_stored_keys_are_unchanged():
    assert (gramps.QUESTION_KEY, gramps.STATUS_KEY, gramps.BLOG_KEY) == (
        "ndygen-vraag",
        "ndygen-status",
        "ndygen-blog",
    )
    assert gramps.FOOTER == "\n\n(onderzoek/vragen.md, "
    assert (gramps.OPEN, gramps.IN_PROGRESS, gramps.BLOCKED, gramps.DONE) == (
        "Open",
        "In Progress",
        "Blocked",
        "Done",
    )


def test_for_gramps_converts_myheritage():
    ged = "\r\n".join(
        [
            "﻿0 HEAD",
            "1 _PROJECT_GUID X",
            "0 @I1@ INDI",
            "1 NAME Eliza /Example/",
            "2 _FORMERNAME Liz",
            "1 EVEN Eliza Sample",
            "2 TYPE Other name",
            "2 SOUR @S1@",
            "1 EVEN Something",
            "2 TYPE Other",
            "1 OBJE",
            "2 FILE media/a.jpg",
            "2 _FILESIZE 12",
            "2 _PHOTO_RIN MH:P1",
            "3 _DEEPER x",
            "2 TITL Photo",
            "2 _DATE 2007",
            "1 DEAT Y",
            "0 TRLR",
            "",
        ]
    )
    out = gramps.for_gramps(ged).split("\r\n")
    assert out == [
        "0 HEAD",
        "0 @I1@ INDI",
        "1 NAME Eliza /Example/",
        "2 _AKA Liz",
        "1 NAME Eliza Sample",
        "2 TYPE aka",
        "2 SOUR @S1@",
        "1 EVEN Something",
        "2 TYPE Other",
        "1 OBJE",
        "2 FILE media/a.jpg",
        "2 TITL Photo (2007)",
        "1 DEAT Y",
        "0 TRLR",
        "",
    ]


def test_for_gramps_saves_what_gramps_would_drop():
    ged = "\r\n".join(
        [
            "0 @I1@ INDI",
            "1 NOTE Married 1909",
            "2 CONC  (record 16)",
            "2 SOUR @S7@",
            "3 PAGE record 16",
            "1 RESI",
            "2 ADDR Sample Street 39",
            "3 CITY Exampleton",
            "1 DSCR height 1.67 m",
            "2 DATE 28 MAY 1887",
            "1 CHR",
            "2 RELI catholic",
            "2 NOTE Baptized",
            "3 SOUR @S8@",
            "0 @N1@ NOTE Loose note",
            "1 SOUR @S9@",
        ]
    )
    assert gramps.for_gramps(ged).split("\r\n")[:-1] == [
        "0 @I1@ INDI",
        "1 NOTE Married 1909",
        "2 CONC  (record 16)",
        "1 SOUR @S7@",
        "2 PAGE record 16",
        "1 RESI",
        "2 ADDR",
        "3 ADR1 Sample Street 39",
        "3 CITY Exampleton",
        "1 DSCR height 1.67 m (28 MAY 1887)",
        "1 CHR",
        "2 NOTE Baptized",
        "2 SOUR @S8@",
        "2 NOTE Godsdienst: catholic",
        "0 @N1@ NOTE Loose note",
        "1 SOUR @S9@",
    ]


def test_for_gramps_does_not_split_on_unicode_line_separators():
    out = gramps.for_gramps("0 @N1@ NOTE a b\r\n0 TRLR\r\n")
    assert out == "0 @N1@ NOTE a b\r\n0 TRLR\r\n"


def test_read_questions():
    questions = gramps.read_questions(QUESTIONS)
    assert [v.status for v in questions] == ["Open", "Open", "Done", "Blocked"]
    assert [v.priority for v in questions] == ["1", "5", "5", "9"]
    assert questions[0].title == "I5 Maria: keuze voor Ann (coördinator)"
    assert questions[1].ids == ["I1", "F1"]
    assert "Keuzes voor de gebruiker / Coördinatie" in questions[0].note


def test_read_questions_with_english_headings():
    questions = gramps.read_questions(ENGLISH_QUESTIONS)
    assert [v.kind for v in questions] == ["choice", "online", "online", "on_site", "living"]
    assert [v.status for v in questions] == ["Open", "Open", "Done", "Open", "Blocked"]
    assert [v.priority for v in questions] == ["1", "5", "5", "9", "9"]


def test_key_survives_an_addition_at_the_end():
    long = "I1 Peter: " + "word " * 40
    a = gramps.read_questions(f"## Other\n- [ ] {long}\n")[0]
    b = gramps.read_questions(f"## Other\n- [x] {long} Solved 14-10-2026.\n")[0]
    assert a.key == b.key


def test_long_title_is_shortened():
    v = gramps.read_questions("## Other\n- [ ] " + "long " * 50 + "\n")[0]
    assert len(v.title) <= 122 and v.title.endswith("…")


def test_read_blogpost(tmp_path):
    post = tmp_path / "2026-10-14-start.md"
    post.write_text(
        "---\ntitle: The start\n---\n# Heading\n\nSee [Open Archives](https://example.org) and **this**.\n"
    )
    read = gramps.read_blogpost(post)
    assert (read.key, read.title, read.author) == (
        "2026-10-14-start",
        "The start",
        "Onderzoeksassistent",
    )
    assert read.text == "# Heading\n\nSee [Open Archives](https://example.org) and **this**."


def test_read_blogpost_with_dutch_front_matter(tmp_path):
    post = tmp_path / "2026-10-14-start.md"
    post.write_text("---\ntitel: De start\nauteur: Jan\n---\nText.\n")
    read = gramps.read_blogpost(post)
    assert (read.title, read.author) == ("De start", "Jan")


def _tags(styled: dict) -> dict[tuple[int, object], list[str]]:
    s = styled["string"]
    return {
        (t["name"]["value"], t["value"]): [s[a:b] for a, b in t["ranges"]] for t in styled["tags"]
    }


def test_styled():
    md = (
        "*Father of Sample (I263), see [Exampleton](https://example.org/wiki/Exampleton_(town)).*\n\n"
        "## The militia\n\nHe drew **number 4** and `I9.md` (I9).\n\n---\n\n**Sources:** record."
    )
    out = gramps.styled(md, {"I263": "ndgx"})
    assert out["string"] == (
        "Father of Sample (I263), see Exampleton.\n\nThe militia\n\n"
        "He drew number 4 and I9.md (I9).\n\nSources: record."
    )
    assert _tags(out) == {
        (gramps.LINK, "gramps://Person/handle/ndgx"): ["I263"],
        (gramps.LINK, "https://example.org/wiki/Exampleton_(town)"): ["Exampleton"],
        (gramps.ITALIC, None): ["Father of Sample (I263), see Exampleton."],
        (gramps.BOLD, None): ["The militia", "number 4", "Sources:"],
        (gramps.FONT_SIZE, gramps.HEADING_SIZE): ["The militia"],
    }


def test_read_life_story(tmp_path):
    stories = tmp_path / "reports" / "life-stories"
    (stories / "images" / "I7").mkdir(parents=True)
    (stories / "images" / "I7" / "church.jpg").write_bytes(b"jpg")
    media = tmp_path / "data" / "media"
    media.mkdir(parents=True)
    (media / "photo.jpg").write_bytes(b"jpg")
    (stories / "I7.md").write_text(
        "# Jan (1800-1850)\n\nFirst paragraph.\n\n"
        "![The church](images/I7/church.jpg)\n*The church in 1900. Source: [Wiki](https://example.org), CC0.*\n\n"
        "Second paragraph.\n\n![Portrait](../../data/media/photo.jpg)\n\nEnd.\n"
    )
    post = gramps.read_life_story(stories / "I7.md", media)
    assert (post.key, post.title, post.person) == ("levensverhaal-I7", "Jan (1800-1850)", "I7")
    assert post.text == "First paragraph.\n\nSecond paragraph.\n\nEnd."
    assert [(a.path, a.caption) for a in post.images] == [
        (
            "levensverhalen/images/I7/church.jpg",
            "The church in 1900. Source: Wiki (https://example.org), CC0.",
        ),
        ("media/photo.jpg", "Portrait"),
    ]


def test_life_story_without_image_file(tmp_path):
    (tmp_path / "I7.md").write_text("# Jan\n\n![x](images/gone.jpg)\n")
    with pytest.raises(gramps.GrampsError, match="gone.jpg"):
        gramps.read_life_story(tmp_path / "I7.md", tmp_path / "media")


def test_blog_without_title(tmp_path):
    post = tmp_path / "x.md"
    post.write_text("Only text.\n")
    with pytest.raises(gramps.GrampsError, match="title"):
        gramps.read_blogpost(post)

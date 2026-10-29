from pathlib import Path

import pytest

from lineage import forum

DRAFT = """---
forum: Geneanet, Palaeography, transcription and old languages
title: Northfield 1631: a name
persons: I1001
crops: a.jpg, b.jpg
status: draft
---
Northfield 1631: a name

Hello everyone,

> Adriaen Ja[n] al[s] d[e]

See https://example.org/scan.jpg
"""

LEGACY_DRAFT = """---
forum: Geneanet, Paleografie
titel: Northfield 1631: een naam
personen: I1001
uitsneden: a.jpg
status: geplaatst
draad: https://nl.geneanet.org/forum/viewtopic.php?t=1
geplaatst: 2026-10-27
reacties: 1
---
Northfield 1631: een naam

Hallo allemaal,

## Reacties

### door helper

Ik lees: Maria
"""


def test_bbcode_quotes_links_and_uncertain_letters() -> None:
    out = forum.bbcode("Hello\n\n> Adriaen Ja[n] al[s]\n> second line\n\nSee https://example.org/x.jpg")
    assert "[quote]Adriaen Ja(n) al(s)\nsecond line[/quote]" in out
    assert "[url]https://example.org/x.jpg[/url]" in out
    assert "[s]" not in out


def test_draft_round_trip_with_replies(tmp_path: Path) -> None:
    path = tmp_path / "c.md"
    path.write_text(DRAFT, encoding="utf-8")
    draft = forum.read_draft(path)
    assert draft.header["title"] == "Northfield 1631: a name"
    assert draft.crops == [Path("a.jpg"), Path("b.jpg")]
    assert draft.text.startswith("Hello everyone,")
    assert draft.reply_count == 0

    draft.header.update(status="posted", thread="https://nl.geneanet.org/forum/viewtopic.php?t=1", replies="1")
    draft.replies.append("### by helper » 27 October 2026\n\nI read: Maria Jan Peters daughter")
    forum.write_draft(draft)

    back = forum.read_draft(path)
    assert back.header["status"] == "posted"
    assert back.text == draft.text
    assert back.replies == draft.replies
    assert back.reply_count == 1


def test_unknown_status_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "c.md"
    path.write_text(DRAFT.replace("status: draft", "status: sent"), encoding="utf-8")
    with pytest.raises(forum.ForumError):
        forum.read_draft(path)


def test_posted_draft_is_not_posted_again(tmp_path: Path) -> None:
    path = tmp_path / "c.md"
    path.write_text(DRAFT.replace("status: draft", "status: posted"), encoding="utf-8")
    with pytest.raises(forum.ForumError, match="already posted"):
        forum.post(forum.read_draft(path))


def test_dutch_header_keys_and_statuses_are_read_and_written_in_english(tmp_path: Path) -> None:
    path = tmp_path / "c.md"
    path.write_text(LEGACY_DRAFT, encoding="utf-8")
    draft = forum.read_draft(path)
    assert draft.header["status"] == "posted"
    assert draft.header["title"] == "Northfield 1631: een naam"
    assert draft.header["thread"].endswith("t=1") and draft.header["posted"] == "2026-10-27"
    assert draft.crops == [Path("a.jpg")] and draft.reply_count == 1
    assert draft.replies == ["### door helper\n\nIk lees: Maria"]
    forum.write_draft(draft)
    written = path.read_text()
    assert "title: Northfield" in written and "titel:" not in written and "## Replies" in written


def test_credentials_use_the_new_names_with_an_old_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "geneanet.env"
    cfg.write_text("NDYGEN_GENEANET_GEBRUIKER=ndy\nNDYGEN_GENEANET_WACHTWOORD=pw\n")
    monkeypatch.setenv("LINEAGE_GENEANET_CONFIG", str(cfg))
    values = forum.config()
    assert values["LINEAGE_GENEANET_USER"] == "ndy" and values["LINEAGE_GENEANET_PASSWORD"] == "pw"
    cfg.write_text("")
    with pytest.raises(forum.ForumError, match="LINEAGE_GENEANET_USER is missing"):
        forum.config()

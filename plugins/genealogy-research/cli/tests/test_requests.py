import datetime as dt

import pytest

from lineage import requests
from tests.conftest import project

EXAMPLE = """---
to: info@archive.example.org
institution: Example Archive
subject: Access to register 1920
persons: I6, I256
status: draft
created: 2026-10-02
---
Dear sir or madam,

Could you please send a scan.

## Background
Why this question matters.
"""

LEGACY_EXAMPLE = """---
aan: info@archive.example.org
instelling: Example Archive
onderwerp: Access to register 1920
personen: I6, I256
status: verstuurd
aangemaakt: 2026-10-02
verstuurd: 2026-10-03
afzender: andy
antwoord-op: <earlier@example.org>
---
Dear sir or madam,

## Achtergrond
Only for us.
"""


def _folder(tmp_path):
    folder = tmp_path / "requests"
    folder.mkdir()
    (folder / "2026-10-02-example.md").write_text(EXAMPLE, encoding="utf-8")
    return folder


def test_read_header_and_text(tmp_path):
    r = requests.load_all(_folder(tmp_path))[0]
    assert (r.to, r.status, r.persons) == ("info@archive.example.org", "draft", ["I6", "I256"])
    assert requests.mail_text(r) == "Dear sir or madam,\n\nCould you please send a scan."


def test_mark_sets_status_and_date(tmp_path):
    folder = _folder(tmp_path)
    requests.mark(requests.find("2026-10-02-exa", folder), "sent", dt.date(2026, 10, 3))
    r = requests.find("2026-10-02-example", folder)
    assert (r.status, r.sent) == ("sent", "2026-10-03")
    assert "status: sent\nsent: 2026-10-03" in r.path.read_text()
    assert requests.mail_text(r).startswith("Dear")


def test_mark_accepts_a_dutch_status(tmp_path):
    folder = _folder(tmp_path)
    requests.mark(requests.find("2026", folder), "beantwoord", dt.date(2026, 10, 9))
    r = requests.find("2026", folder)
    assert (r.status, r.fields["answered"]) == ("answered", "2026-10-09")


def test_marking_a_dutch_file_replaces_its_old_status_lines(tmp_path):
    folder = _folder(tmp_path)
    path = folder / "2026-10-02-example.md"
    path.write_text(LEGACY_EXAMPLE, encoding="utf-8")
    requests.mark(requests.find("2026", folder), "sent", dt.date(2026, 10, 4))
    header = path.read_text().split("\n---\n")[0]
    assert "verstuurd" not in header
    assert header.count("status:") == 1 and "sent: 2026-10-04" in header


def test_unknown_status_is_refused(tmp_path):
    folder = _folder(tmp_path)
    with pytest.raises(requests.RequestError):
        requests.mark(requests.find("2026", folder), "lost")


def test_overview_shows_address_and_subject(tmp_path):
    text = requests.overview(requests.load_all(_folder(tmp_path)), with_text=True)
    assert "to: info@archive.example.org  (Example Archive)" in text
    assert "Could you please send a scan." in text and "Why this question" not in text


def test_overview_lists_replies_saved_for_a_request(tmp_path):
    project(tmp_path, paths={"research": "."})
    folder = tmp_path / "requests"
    (folder / "replies").mkdir(parents=True)
    (folder / "2026-10-02-circle.md").write_text(
        "---\nto: a@example.org\nsubject: Question\npersons: I1\nstatus: sent\ncreated: 2026-10-02\n---\nText\n"
    )
    (folder / "replies" / "2026-10-05-2026-10-02-circle-7.md").write_text("---\n---\nYes.\n")
    r = requests.load_all(folder)[0]
    assert [p.name for p in requests.replies(r)] == ["2026-10-05-2026-10-02-circle-7.md"]
    assert "reply:" in requests.overview([r])


def test_the_replies_folder_is_configurable(tmp_path):
    folder = _folder(tmp_path)
    project(tmp_path, paths={"replies": str(folder.relative_to(tmp_path) / "antwoorden")})
    (folder / "antwoorden").mkdir()
    (folder / "antwoorden" / "2026-10-05-2026-10-02-example-3.md").write_text("---\n---\nYes.\n")
    r = requests.load_all(folder)[0]
    assert len(requests.replies(r)) == 1


def test_duplicate_key_in_header_is_an_error(tmp_path):
    folder = _folder(tmp_path)
    (folder / "2026-10-03-double.md").write_text(
        EXAMPLE.replace("subject: Access to register 1920\n", "subject: A\nsubject: B\n"),
        encoding="utf-8",
    )
    with pytest.raises(requests.RequestError, match="twice"):
        requests.read(folder / "2026-10-03-double.md")
    assert len(requests.errors(folder)) == 1


def test_a_dutch_key_and_its_english_twin_count_as_a_duplicate(tmp_path):
    folder = _folder(tmp_path)
    (folder / "2026-10-03-double.md").write_text(
        EXAMPLE.replace("to: info@archive.example.org\n", "to: a@example.org\naan: b@example.org\n"),
        encoding="utf-8",
    )
    with pytest.raises(requests.RequestError, match="twice"):
        requests.read(folder / "2026-10-03-double.md")


def test_dutch_header_and_statuses_are_read(tmp_path):
    folder = _folder(tmp_path)
    (folder / "2026-10-02-example.md").write_text(LEGACY_EXAMPLE, encoding="utf-8")
    r = requests.load_all(folder)[0]
    assert (r.to, r.institution, r.subject, r.status) == (
        "info@archive.example.org", "Example Archive", "Access to register 1920", "sent"
    )
    assert (r.created, r.sent, r.fields["in-reply-to"]) == ("2026-10-02", "2026-10-03", "<earlier@example.org>")
    assert requests.mail_text(r) == "Dear sir or madam,"


def test_request_sent_by_the_user_points_to_their_own_mailbox(tmp_path):
    folder = _folder(tmp_path)
    (folder / "2026-10-02-example.md").write_text(
        EXAMPLE.replace("status: draft\n", "status: sent\nsender: user\n"), encoding="utf-8"
    )
    assert "own mailbox" in requests.overview(requests.load_all(folder))
    (folder / "2026-10-02-example.md").write_text(LEGACY_EXAMPLE, encoding="utf-8")
    assert "own mailbox" in requests.overview(requests.load_all(folder))


def test_overview_is_dutch_in_a_dutch_project(tmp_path):
    project(tmp_path, language="nl")
    text = requests.overview(requests.load_all(_folder(tmp_path)))
    assert "aan: info@archive.example.org  (Example Archive)" in text
    assert requests.overview([]) == "geen aanvragen"

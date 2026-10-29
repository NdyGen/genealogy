import pytest

from lineage import archive, credentials, htr, mail, rat, requests
from tests.conftest import project
from tests.test_archive import REF, offline  # noqa: F401


def test_describe_in_dutch(tmp_path, offline):  # noqa: F811
    project(tmp_path, language="nl", mail_enabled=True)
    lines = archive.describe(archive.show(REF)).splitlines()
    assert "archief 77, inv. 812, akte 7" in lines[1]
    assert lines[2].startswith("akte: ")
    assert lines[3].startswith("scan: ")


def test_archive_error_in_dutch(tmp_path):
    project(tmp_path, language="nl", mail_enabled=True)
    with pytest.raises(archive.ArchiveError, match="verwacht <archief>:<identifier>"):
        archive.show("7c3d9e20")


def test_rat_error_in_dutch(tmp_path):
    project(tmp_path, language="nl", mail_enabled=True)
    with pytest.raises(rat.RatError, match="kader moet fracties zijn"):
        rat.crop(tmp_path / "x.jpg", (0.5, 0, 0.2, 1), tmp_path / "out.jpg")


def test_model_error_in_dutch(tmp_path):
    project(tmp_path, language="nl", mail_enabled=True)
    with pytest.raises(htr.HtrError, match="onbekend model 'x'"):
        htr.model_id("x")


def test_missing_credentials_in_dutch(tmp_path, monkeypatch):
    project(tmp_path, language="nl", mail_enabled=True)
    monkeypatch.setenv("LINEAGE_MAIL_CONFIG", str(tmp_path / "none.env"))
    with pytest.raises(mail.MailError, match="ontbreekt in"):
        credentials.load("mail.env", "LINEAGE_MAIL_", ("LINEAGE_MAIL_ADDRESS",), mail.MailError)


def test_sending_needs_approval_in_dutch(tmp_path):
    project(tmp_path, language="nl", mail_enabled=True)
    request = requests.Request.__new__(requests.Request)
    request.to = "archief@example.org"
    with pytest.raises(mail.MailError, match="versturen kan alleen met --approved"):
        mail.send(request, approved=False)

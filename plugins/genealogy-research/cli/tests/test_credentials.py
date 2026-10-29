import pytest

from lineage import credentials


class Missing(RuntimeError):
    pass


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("LINEAGE_DEMO_CONFIG", "NDYGEN_DEMO_CONFIG", "LINEAGE_DEMO_USER", "NDYGEN_DEMO_GEBRUIKER"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def load():
    return credentials.load(
        "demo.env", "LINEAGE_DEMO_", ("LINEAGE_DEMO_USER",), Missing, renamed={"GEBRUIKER": "USER"}
    )


def test_new_file_and_keys(home):
    (home / ".config" / "lineage").mkdir(parents=True)
    (home / ".config" / "lineage" / "demo.env").write_text("LINEAGE_DEMO_USER=new\n# comment\n")
    assert load()["LINEAGE_DEMO_USER"] == "new"


def test_old_file_and_old_keys_are_the_fallback(home):
    (home / ".config" / "ndygen").mkdir(parents=True)
    (home / ".config" / "ndygen" / "demo.env").write_text("NDYGEN_DEMO_GEBRUIKER=old\n")
    assert load()["LINEAGE_DEMO_USER"] == "old"


def test_new_file_wins_over_the_old_one(home):
    for directory, line in (("ndygen", "NDYGEN_DEMO_GEBRUIKER=old"), ("lineage", "LINEAGE_DEMO_USER=new")):
        (home / ".config" / directory).mkdir(parents=True)
        (home / ".config" / directory / "demo.env").write_text(line + "\n")
    assert load()["LINEAGE_DEMO_USER"] == "new"


def test_old_environment_names_are_read(home, monkeypatch):
    monkeypatch.setenv("NDYGEN_DEMO_CONFIG", str(home / "x.env"))
    (home / "x.env").write_text("NDYGEN_DEMO_GEBRUIKER=from-file\n")
    assert load()["LINEAGE_DEMO_USER"] == "from-file"
    monkeypatch.setenv("NDYGEN_DEMO_GEBRUIKER", "from-env")
    assert load()["LINEAGE_DEMO_USER"] == "from-env"


def test_missing_credentials_name_the_file(home):
    with pytest.raises(Missing, match="LINEAGE_DEMO_USER is missing in"):
        load()

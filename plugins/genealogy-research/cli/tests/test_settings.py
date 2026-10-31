import shutil
import stat
from pathlib import Path

import pytest

from lineage import doctor, settings
from lineage.cli import main
from tests.conftest import FIXTURE

FULL = """\
name = "Smith family research"
language = "nl"
gedcom = "data/stamboom.ged"
targets = [{ label = "Me", id = "i1" }, { label = "Father", id = "I2" }]
line_root = "I1"
stems = [{ name = "Smith", id = "I2", men_first = true }, { name = "Jones", id = "I3" }]
runner = "herdr"

[paths]
research = "onderzoek"
queue = "{research}/wachtrij.tsv"

[paternal_line]
start = "I2"
notify = "me@example.org"

[mail]
own_address = "Me@Example.org"
sender_name = "Ann Smith"

[gramps]
url = "https://gramps.example.org"

[accounts.work]

[accounts.personal]
config_dir = "~/.claude-personal"
"""


def test_full_file(tmp_path):
    (tmp_path / "lineage.toml").write_text(FULL)
    c = settings.load(tmp_path / "sub" / "dir")
    assert c.root == tmp_path.resolve() and c.language == "nl" and c.runner == "herdr"
    assert c.targets == (settings.Target("Me", "I1"), settings.Target("Father", "I2"))
    assert c.stem_tuples == (("Smith", "I2", "men-first"), ("Jones", "I3"))
    assert c.own_address == "me@example.org" and c.sender_name == "Ann Smith"
    assert c.accounts == {"work": {}, "personal": {"config_dir": "~/.claude-personal"}}
    assert c.rel("gedcom") == Path("data/stamboom.ged")
    assert c.rel("queue") == Path("onderzoek/wachtrij.tsv")
    assert c.rel("questions") == Path("onderzoek/questions.md")
    assert c.path("life_stories") == tmp_path.resolve() / "reports/life-stories"


def test_dump_reads_back_the_same(tmp_path):
    (tmp_path / "lineage.toml").write_text(FULL)
    c = settings.load(tmp_path)
    assert settings.parse(settings.dump(c), c.file) == c


def test_without_a_file_only_defaults(tmp_path):
    c = settings.load(tmp_path)
    assert (
        c.file is None and c.root == tmp_path.resolve() and c.rel("gedcom") == Path("data/tree.ged")
    )
    with pytest.raises(settings.ConfigError, match="'line_root' is not set"):
        _ = c.root_person


def test_line_root_falls_back_to_the_first_target(tmp_path):
    assert settings.Config(tmp_path, targets=(settings.Target("Me", "I7"),)).root_person == "I7"


@pytest.mark.parametrize(
    "text, message",
    [
        ('language = "xx"', "language 'xx'"),
        ('runner = "tmux"', "runner 'tmux'"),
        ('[paths]\nresearh = "x"', "unknown \\[paths\\] researh"),
        ('targets = [{ label = "Me" }]', "needs label and id"),
        ("targets = [", "lineage.toml"),
    ],
)
def test_mistakes_are_named(tmp_path, text, message):
    (tmp_path / "lineage.toml").write_text(text)
    with pytest.raises(settings.ConfigError, match=message):
        settings.load(tmp_path)


def test_lineage_config_names_the_file(tmp_path, monkeypatch):
    (tmp_path / "elsewhere.toml").write_text('line_root = "I4"')
    monkeypatch.setenv("LINEAGE_CONFIG", str(tmp_path / "elsewhere.toml"))
    assert settings.load(tmp_path / "x").root_person == "I4"
    monkeypatch.setenv("LINEAGE_CONFIG", str(tmp_path / "missing.toml"))
    with pytest.raises(settings.ConfigError, match="does not exist"):
        settings.load(tmp_path)


def test_init_writes_the_project(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    shutil.copy(FIXTURE, tmp_path / "data" / "tree.ged")
    args = ["init", "--name", "Test", "--target", "Me=I1", "--stem", "Smith=I2:men-first"]
    assert main([*args, "--allow", "Archive searches about persons who died before 1900."]) == 0
    c = settings.load(tmp_path)
    assert c.name == "Test" and c.root_person == "I1" and c.stems[0].men_first
    for key in ("queue", "log", "questions", "project"):
        assert c.path(key).is_file()
    project = c.path("project").read_text()
    assert "Me: John Miller (I1)" in project and "Exception: Archive searches" in project
    assert "## On site only or with a full-resolution scan" in c.path("questions").read_text()
    assert "check:" not in capsys.readouterr().err

    assert main(["init"]) == 2
    assert "use --update" in capsys.readouterr().err

    c.path("log").write_text("# my log\n")
    assert main(["init", "--update", "--target", "Me=I99", "--language", "nl"]) == 0
    assert "check: targets: I99 is not in the tree" in capsys.readouterr().err
    c = settings.load(tmp_path)
    assert c.name == "Test" and c.targets == (settings.Target("Me", "I99"),) and c.language == "nl"
    assert c.path("log").read_text() == "# my log\n"


def test_config_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lineage.toml").write_text(
        f'gedcom = "{FIXTURE}"\ntargets = [{{ label = "Me", id = "I1" }}]\n'
    )
    assert main(["config", "path", "queue"]) == 0
    assert capsys.readouterr().out.strip() == str(tmp_path.resolve() / "research/queue.tsv")
    assert main(["config", "check"]) == 0
    assert main(["config", "show"]) == 0
    assert "# queue = research/queue.tsv" in capsys.readouterr().out
    (tmp_path / "lineage.toml").write_text(f'gedcom = "{FIXTURE}"\nline_root = "I404"\n')
    settings.use(None)
    assert main(["config", "check"]) == 1
    out = capsys.readouterr().out
    assert "line_root: I404 is not in the tree" in out and "no target persons" in out


def test_config_relative_path_value_runner_accounts(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DR_RUNNER", raising=False)
    monkeypatch.delenv("HERDR_ENV", raising=False)
    monkeypatch.delenv("HC_TERMINAL_ID", raising=False)
    (tmp_path / "lineage.toml").write_text(
        'name = "Test"\nlanguage = "nl"\nline_root = "I5"\n[accounts.work]\nconfig_dir = "/cfg/w"\n'
        "[accounts.private]\n"
    )
    assert main(["config", "path", "output", "--relative"]) == 0
    assert capsys.readouterr().out.strip() == "output"
    for key, want in (("language", "nl"), ("name", "Test"), ("line_root", "I5"), ("runner", "auto")):
        assert main(["config", "value", key]) == 0
        assert capsys.readouterr().out.strip() == want
    with pytest.raises(SystemExit) as exc:
        main(["config", "value", "nope"])
    assert exc.value.code == 2
    assert main(["config", "accounts"]) == 0
    assert capsys.readouterr().out == "work\t/cfg/w\nprivate\t\n"
    assert main(["config", "runner"]) == 0
    assert capsys.readouterr().out.strip() == "inline"
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setattr("shutil.which", lambda name: "/bin/herdr")
    assert main(["config", "runner"]) == 0
    assert capsys.readouterr().out.strip() == "herdr"
    # Inside an hc terminal (the Herdr app) hc wins, even where an old Herdr session is still around.
    monkeypatch.setenv("HC_TERMINAL_ID", "t7")
    assert main(["config", "runner"]) == 0
    assert capsys.readouterr().out.strip() == "hc"
    monkeypatch.setenv("DR_RUNNER", "headless")
    assert main(["config", "runner"]) == 0
    assert capsys.readouterr().out.strip() == "headless"


def test_config_accounts_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lineage.toml").write_text('name = "T"\n')
    assert main(["config", "accounts"]) == 0
    assert capsys.readouterr().out == "default\t\n"


def test_tree_commands_use_the_configured_tree(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lineage.toml").write_text(f'gedcom = "{FIXTURE}"\n')
    assert main(["person", "I1"]) == 0
    assert "John Miller" in capsys.readouterr().out


def test_auth_writes_a_private_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LINEAGE_GRAMPS_CONFIG", str(tmp_path / "conf" / "gramps.env"))
    answers = iter(["claude"])
    path = doctor.prompt("gramps", ask=lambda _: next(answers), ask_secret=lambda _: "s3cret")
    assert path.read_text() == "LINEAGE_GRAMPS_USER=claude\nLINEAGE_GRAMPS_PASSWORD=s3cret\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    path = doctor.prompt("gramps", ask=lambda _: "", ask_secret=lambda _: "")
    assert "LINEAGE_GRAMPS_PASSWORD=s3cret" in path.read_text()
    assert doctor.status("gramps").startswith("set up in")


def test_dutch_output(tmp_path, monkeypatch, capsys):
    from tests.conftest import project

    project(tmp_path, language="nl")
    monkeypatch.chdir(tmp_path)
    shutil.copy(FIXTURE, tmp_path / "tree.ged")
    with pytest.raises(SystemExit) as exc:
        main(["--file", str(tmp_path / "tree.ged"), "person", "I999"])
    assert "niet gevonden" in str(exc.value)
    assert main(["config", "check"]) == 1
    assert "geen lineage.toml" in capsys.readouterr().out


def test_dutch_scaffold_texts(tmp_path):
    from lineage import scaffold
    from tests.conftest import project

    project(tmp_path, language="nl")
    text = scaffold.questions_text("nl")
    assert text.startswith("# Open vragen\n\nFormaat:")
    assert "## Keuzes voor de gebruiker" in text
    assert "Doelpersonen" in scaffold.project_text(settings.current(), None, ["x"])
    assert doctor.status("gramps").startswith("niet ingesteld") or doctor.status(
        "gramps"
    ).startswith("ingesteld")


def test_mail_is_opt_in(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lineage.toml").write_text("")
    assert main(["config", "value", "mail_enabled"]) == 0
    assert capsys.readouterr().out.strip() == "false"
    (tmp_path / "lineage.toml").write_text("[mail]\nenabled = true\n")
    settings.use(None)
    assert main(["config", "value", "mail_enabled"]) == 0
    assert capsys.readouterr().out.strip() == "true"
    assert "enabled = true" in settings.dump(settings.current())


def test_config_paths_lists_every_key(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lineage.toml").write_text('[paths]\nresearch = "onderzoek"\n')
    assert main(["config", "paths"]) == 0
    lines = dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())
    assert lines["gedcom"] == "data/tree.ged" and lines["queue"] == "onderzoek/queue.tsv"
    assert set(lines) == {"gedcom", *settings.PATHS}


def test_file_may_follow_the_command(capsys):
    assert main(["person", "I1", "--file", str(FIXTURE)]) == 0
    assert main(["validate", f"--file={FIXTURE}"]) == 0
    assert "John Miller" in capsys.readouterr().out


def test_runner_hc_is_a_valid_setting(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DR_RUNNER", raising=False)
    (tmp_path / "lineage.toml").write_text('name = "T"\nrunner = "hc"\n')
    assert main(["config", "runner"]) == 0
    assert capsys.readouterr().out.strip() == "hc"


def test_guard_refuses_a_runner_without_terminals(tmp_path, monkeypatch, capsys):
    import subprocess

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    monkeypatch.setenv("DR_RUNNER", "inline")
    (tmp_path / "lineage.toml").write_text('name = "T"\n')
    assert main(["guard", "--once", "--dry-run"]) == 2
    assert "herdr or hc" in capsys.readouterr().err


def test_doctor_reports_hc(monkeypatch):
    monkeypatch.setattr(doctor, "_version", lambda *c: "hc 0.1.15" if c[0] == "hc" else None)
    found = {c.name: c for c in doctor.checks()}
    assert found["hc"].ok and found["hc"].detail == "hc 0.1.15" and not found["hc"].required
    assert not found["herdr"].ok

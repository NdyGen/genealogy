import pytest

from lineage import cli


def test_round_is_handed_to_the_wrapper(monkeypatch, tmp_path):
    wrapper = tmp_path / "lineage"
    wrapper.write_text("#!/bin/sh\n")
    monkeypatch.setenv("LINEAGE_BIN", str(wrapper))
    calls = []

    def execv(path, args):
        calls.append((path, args))
        raise SystemExit(0)

    monkeypatch.setattr(cli.os, "execv", execv)
    with pytest.raises(SystemExit):
        cli.main(["round", "watch"])
    assert calls == [(str(wrapper), [str(wrapper), "round", "watch"])]


def test_round_without_wrapper_fails_clearly(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LINEAGE_BIN", str(tmp_path / "missing"))
    assert cli.main(["round", "watch"]) == 2
    assert "wrapper" in capsys.readouterr().err

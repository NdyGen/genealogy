import datetime as dt
import io
import sys

from lineage import limits
from lineage.cli import main

NOW = dt.datetime(2026, 10, 3, 11, 0)


def test_session_limit_time():
    assert limits.limit_reset("You've hit your session limit · resets 3:30pm", NOW) == int(
        dt.datetime(2026, 10, 3, 15, 30).timestamp())


def test_no_limit():
    assert limits.limit_reset("all good", NOW) is None


def test_limits_parse_prints_epoch_or_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("hit your session limit · resets 11:30pm"))
    assert main(["limits", "parse"]) == 0
    assert capsys.readouterr().out.strip().isdigit()
    monkeypatch.setattr(sys, "stdin", io.StringIO("fine"))
    assert main(["limits", "parse"]) == 1

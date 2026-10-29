import ast
import datetime as dt
import json
import string
from pathlib import Path

import pytest

from lineage import i18n, settings
from tests.conftest import project

SOURCE = Path(i18n.__file__).parent


def _messages() -> dict[str, str]:
    """Every literal first argument of t(...) in the package, with the file it is in."""
    found = {}
    for path in SOURCE.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name | ast.Attribute)
                and (node.func.id if isinstance(node.func, ast.Name) else node.func.attr) == "t"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found[node.args[0].value] = path.name
    return found


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_message_has_a_dutch_translation():
    missing = {m: f for m, f in _messages().items() if m not in i18n.catalog("nl")}
    assert not missing, f"not in locales/nl: {missing}"


def test_no_unused_translations():
    unused = set(i18n.catalog("nl")) - set(_messages())
    assert not unused, f"in locales/nl but not used: {sorted(unused)}"


def test_translations_keep_the_placeholders():
    wrong = {k: v for k, v in i18n.catalog("nl").items() if _fields(k) != _fields(v)}
    assert not wrong


def test_no_key_in_two_files_with_different_texts():
    seen: dict[str, str] = {}
    for path in sorted((i18n.LOCALES / "nl").glob("*.json")):
        for key, value in json.loads(path.read_text(encoding="utf-8")).items():
            assert seen.setdefault(key, value) == value, f"{key!r} differs in {path.name}"


@pytest.mark.parametrize("language, expected", [("en", "1 March 1776"), ("nl", "1-3-1776")])
def test_dates(tmp_path, language, expected):
    project(tmp_path, language=language)
    assert i18n.date(dt.date(1776, 3, 1)) == expected


def test_untranslated_text_stays_english(tmp_path):
    project(tmp_path, language="nl")
    assert i18n.t("no such message {n}", n=3) == "no such message 3"
    project(tmp_path, language="fr")
    assert i18n.month(3) == "March"
    assert isinstance(settings.current(), settings.Config)

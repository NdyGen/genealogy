"""The project settings in lineage.toml, found in the working directory or one of its parents.

Every path is relative to the folder of lineage.toml. Without that file the English default paths apply
relative to the working directory, and the project values (target persons, line root, stems, addresses)
are empty: commands that need one say so instead of guessing.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

FILE = "lineage.toml"
LANGUAGES = ("en", "nl", "de", "fr")
RUNNERS = ("auto", "hc", "herdr", "headless", "inline")
# A path may refer to an earlier one as {name}; the order below is the resolution order.
PATHS = {
    "data": "data",
    "research": "research",
    "reports": "reports",
    "sources": "sources",
    "output": "output",
    "queue": "{research}/queue.tsv",
    "questions": "{research}/questions.md",
    "log": "{research}/log.md",
    "project": "{research}/project.md",
    "lessons": "{research}/lessons.md",
    "background": "{research}/background",
    "requests": "{research}/requests",
    "replies": "{requests}/replies",
    "forum": "{research}/forum",
    "forum_notifications": "{forum}/notifications",
    "blog": "{research}/blog",
    "question_history": "{research}/question-map.tsv",
    "stories_checked": "{research}/stories-checked.tsv",
    "person_reports": "{reports}/persons",
    "life_stories": "{reports}/life-stories",
    "books": "{reports}/books",
    "question_map_page": "{reports}/question-map.html",
    "scans": "{sources}/scans/fetched",
    "request_attachments": "{sources}/scans/requests",
}
DEFAULT_GEDCOM = "{data}/tree.ged"
DISK = ("low_gb", "target_gb", "critical_gb", "keep_days")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    label: str
    id: str


@dataclass(frozen=True)
class Stem:
    name: str
    id: str
    men_first: bool = False


@dataclass(frozen=True)
class Config:
    root: Path
    file: Path | None = None
    name: str = ""
    language: str = "en"
    gedcom: str = DEFAULT_GEDCOM
    targets: tuple[Target, ...] = ()
    line_root: str = ""
    stems: tuple[Stem, ...] = ()
    runner: str = "auto"
    paths: dict[str, str] = field(default_factory=dict)
    paternal_start: str = ""
    paternal_notify: str = ""
    mail_enabled: bool = False
    own_address: str = ""
    sender_name: str = ""
    gramps_url: str = ""
    rat_fonds: str = ""
    disk: dict[str, float] = field(default_factory=dict)
    accounts: dict[str, dict[str, str]] = field(default_factory=dict)

    def rel(self, key: str) -> Path:
        """The path below the project root, as written in lineage.toml or its default."""
        resolved: dict[str, str] = {}
        for name, default in PATHS.items():
            resolved[name] = self.paths.get(name, default).format(**resolved)
        if key == "gedcom":
            return Path(self.gedcom.format(**resolved))
        if key not in resolved:
            raise ConfigError(f"unknown path '{key}'; known: gedcom, {', '.join(PATHS)}")
        return Path(resolved[key])

    def path(self, key: str) -> Path:
        return self.root / self.rel(key)

    def require(self, value: str | tuple, key: str) -> None:
        if not value:
            where = self.file or f"{FILE} (none found from {self.root})"
            raise ConfigError(f"'{key}' is not set in {where}; run 'lineage init' or /genealogy-research:setup")

    @property
    def root_person(self) -> str:
        """The person whose ancestors form the direct line: line_root, else the first target."""
        value = self.line_root or (self.targets[0].id if self.targets else "")
        self.require(value, "line_root")
        return value

    @property
    def stem_tuples(self) -> tuple[tuple[str, ...], ...]:
        return tuple((s.name, s.id, *(["men-first"] if s.men_first else [])) for s in self.stems)


def find(start: Path) -> Path | None:
    for folder in (start, *start.parents):
        if (folder / FILE).is_file():
            return folder / FILE
    return None


def _table(raw: dict, key: str, file: Path) -> dict:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{file}: [{key}] must be a table")
    return value


def _list(raw: dict, key: str, file: Path, kind: type, id_key: str, name_key: str) -> tuple:
    items = []
    for entry in raw.get(key, []):
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get(name_key):
            raise ConfigError(f"{file}: every entry of '{key}' needs {name_key} and id, got {entry!r}")
        extra = {"men_first": bool(entry.get("men_first"))} if kind is Stem else {}
        items.append(kind(str(entry[name_key]), str(entry[id_key]).upper(), **extra))
    return tuple(items)


def parse(text: str, file: Path) -> Config:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{file}: {exc}") from exc
    paths = _table(raw, "paths", file)
    if unknown := set(paths) - set(PATHS):
        raise ConfigError(f"{file}: unknown [paths] {', '.join(sorted(unknown))}; known: {', '.join(PATHS)}")
    language = raw.get("language", "en")
    if language not in LANGUAGES:
        raise ConfigError(f"{file}: language '{language}' is not one of {', '.join(LANGUAGES)}")
    runner = raw.get("runner", "auto")
    if runner not in RUNNERS:
        raise ConfigError(f"{file}: runner '{runner}' is not one of {', '.join(RUNNERS)}")
    paternal = _table(raw, "paternal_line", file)
    mail = _table(raw, "mail", file)
    accounts = _table(raw, "accounts", file)
    disk = _table(raw, "disk", file)
    if unknown := set(disk) - set(DISK):
        raise ConfigError(f"{file}: unknown [disk] {', '.join(sorted(unknown))}; known: {', '.join(DISK)}")
    if wrong := [k for k, v in disk.items() if isinstance(v, bool) or not isinstance(v, int | float) or v < 0]:
        raise ConfigError(f"{file}: [disk] {', '.join(wrong)} must be a number of at least 0")
    return Config(
        root=file.parent.resolve(),
        file=file.resolve(),
        name=raw.get("name", ""),
        language=language,
        gedcom=raw.get("gedcom", DEFAULT_GEDCOM),
        targets=_list(raw, "targets", file, Target, "id", "label"),
        line_root=str(raw.get("line_root", "")).upper(),
        stems=_list(raw, "stems", file, Stem, "id", "name"),
        runner=runner,
        paths={k: str(v) for k, v in paths.items()},
        paternal_start=str(paternal.get("start", "")).upper(),
        paternal_notify=paternal.get("notify", ""),
        mail_enabled=bool(mail.get("enabled", False)),
        own_address=mail.get("own_address", "").strip().lower(),
        sender_name=mail.get("sender_name", ""),
        gramps_url=_table(raw, "gramps", file).get("url", ""),
        rat_fonds=str(_table(raw, "rat", file).get("fonds", "")),
        disk={k: float(v) for k, v in disk.items()},
        accounts={k: {kk: str(vv) for kk, vv in (v or {}).items()} for k, v in accounts.items()},
    )


def load(start: Path | None = None) -> Config:
    """LINEAGE_CONFIG names the file; otherwise the nearest lineage.toml from start upwards."""
    explicit = os.environ.get("LINEAGE_CONFIG")
    start = (start or Path.cwd()).resolve()
    file = Path(explicit).expanduser() if explicit else find(start)
    if file is None:
        return Config(root=start)
    if not file.is_file():
        raise ConfigError(f"LINEAGE_CONFIG points to {file}, which does not exist")
    return parse(file.read_text(encoding="utf-8"), file)


_current: Config | None = None


def current() -> Config:
    global _current
    if _current is None:
        _current = load()
    return _current


def use(config: Config | None) -> None:
    """Replace the loaded settings (None loads them again on the next use)."""
    global _current
    _current = config


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml(value: str | bool | float) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return f"{value:g}"
    return _quote(value)


def dump(c: Config) -> str:
    """lineage.toml text for c; only what differs from the defaults, so new defaults reach old projects."""
    lines = []
    if c.name:
        lines.append(f"name = {_quote(c.name)}")
    lines.append(f"language = {_quote(c.language)}")
    lines.append(f"gedcom = {_quote(c.gedcom)}")
    if c.targets:
        lines.append("targets = [")
        lines += [f"  {{ label = {_quote(t.label)}, id = {_quote(t.id)} }}," for t in c.targets]
        lines.append("]")
    if c.line_root:
        lines.append(f"line_root = {_quote(c.line_root)}")
    if c.stems:
        lines.append("stems = [")
        for s in c.stems:
            flag = ", men_first = true" if s.men_first else ""
            lines.append(f"  {{ name = {_quote(s.name)}, id = {_quote(s.id)}{flag} }},")
        lines.append("]")
    lines.append(f"runner = {_quote(c.runner)}")
    tables = {
        "paths": {k: v for k, v in c.paths.items() if v != PATHS.get(k)},
        "paternal_line": {"start": c.paternal_start, "notify": c.paternal_notify},
        "mail": {"enabled": c.mail_enabled, "own_address": c.own_address, "sender_name": c.sender_name},
        "gramps": {"url": c.gramps_url},
        "rat": {"fonds": c.rat_fonds},
        "disk": dict(c.disk),
    }
    for table, values in tables.items():
        if values := {k: v for k, v in values.items() if v}:
            lines += ["", f"[{table}]", *(f"{k} = {_toml(v)}" for k, v in values.items())]
    for account, values in c.accounts.items():
        lines += ["", f"[accounts.{account}]", *(f"{k} = {_quote(v)}" for k, v in values.items())]
    return "\n".join(lines) + "\n"

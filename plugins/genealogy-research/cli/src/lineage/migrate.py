"""`lineage migrate`: turn a project of the Dutch predecessor (ndygen) into a lineage project, once.

File and folder names stay as they are; lineage.toml points at them under [paths], so links in reports,
the git history and Gramps Web keep working. What changes is inside the files the tools read: TSV columns,
status values and header keys become English. Free text (log, questions, reports) stays as written.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from lineage import coordinates, credentials, forum, queue, requests, settings
from lineage.i18n import t
from lineage.question_map import LEGACY_HISTORY_COLUMNS

# Top folders and the names inside them as the predecessor used them.
LEGACY_TOP = {
    "research": "onderzoek",
    "reports": "rapporten",
    "sources": "bronnen",
    "output": "uitvoer",
}
LEGACY_NAMES = {
    "queue": "{research}/wachtrij.tsv",
    "questions": "{research}/vragen.md",
    "lessons": "{research}/lessen.md",
    "background": "{research}/achtergrond",
    "requests": "{research}/aanvragen",
    "replies": "{research}/aanvragen/antwoorden",
    "forum_notifications": "{research}/forum/meldingen",
    "question_history": "{research}/vragenkaart.tsv",
    "stories_checked": "{research}/levensverhalen-gecontroleerd.tsv",
    "person_reports": "{reports}/personen",
    "life_stories": "{reports}/levensverhalen",
    "books": "{reports}/boeken",
    "question_map_page": "{reports}/vragenkaart.html",
    "scans": "{sources}/scans/opgehaald",
    "request_attachments": "{sources}/scans/aanvragen",
}
LEGACY_GEDCOM = "data/stamboom.ged"
TARGETS_FILE = "verwant.tsv"
STEMS_FILE = "stammen.tsv"
LEGACY_LEVELS = {
    "adres": coordinates.LEVEL_ADDRESS,
    "straat": coordinates.LEVEL_STREET,
    "gehucht/buurt": coordinates.LEVEL_HAMLET,
    "plaats": coordinates.LEVEL_PLACE,
}
CREDENTIAL_KEYS = {"GEBRUIKER": "USER", "WACHTWOORD": "PASSWORD", "ADRES": "ADDRESS"}


@dataclass
class Plan:
    config: settings.Config
    rewrites: list[tuple[Path, str, Callable[[], None]]] = field(default_factory=list)
    removals: list[Path] = field(default_factory=list)
    credentials: list[tuple[Path, Path]] = field(default_factory=list)

    def lines(self, root: Path) -> list[str]:
        out = [t("write {file}", file=settings.FILE)]
        out += [
            t("convert {path}: {what}", path=path.relative_to(root), what=what)
            for path, what, _ in self.rewrites
        ]
        out += [
            t("remove {path} (now in {file})", path=path.relative_to(root), file=settings.FILE)
            for path in self.removals
        ]
        out += [
            t("copy credentials {old} -> {new} (LINEAGE_ keys, mode 600)", old=old, new=new)
            for old, new in self.credentials
        ]
        return out


def legacy_paths(root: Path) -> dict[str, str]:
    """[paths] with the predecessor's folder and file names, when its research folder is there."""
    if not (root / LEGACY_TOP["research"]).exists():
        return {}
    tops = dict(LEGACY_TOP)
    paths = dict(tops)
    for key, template in LEGACY_NAMES.items():
        parent = template[1 : template.index("}")]
        if parent in tops:
            paths[key] = template.format(**tops)
    return paths


def _rows(path: Path) -> list[list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        [v.strip() for v in line.split("\t")]
        for line in lines
        if line.strip() and not line.startswith("#")
    ]


def targets_from(path: Path) -> tuple[settings.Target, ...]:
    return tuple(settings.Target(r[0], r[1].upper()) for r in _rows(path) if len(r) >= 2)


def stems_from(path: Path) -> tuple[settings.Stem, ...]:
    return tuple(
        settings.Stem(r[0], r[1].upper(), bool({"mannen-eerst", "men-first"} & set(r[2:])))
        for r in _rows(path)
        if len(r) >= 2
    )


def rewrite_header(text: str, keys: dict[str, str], statuses: dict[str, str]) -> str:
    """The '---' header with English keys and status values; the body stays as it is."""
    if not text.startswith("---\n"):
        return text
    header, sep, body = text[4:].partition("\n---\n")
    lines = []
    for line in header.splitlines():
        key, colon, value = line.partition(":")
        if not colon:
            lines.append(line)
            continue
        key = keys.get(key.strip(), key.strip())
        value = value.strip()
        if key == "status":
            value = statuses.get(value, value)
        elif key == "sender" and value == "andy":
            value = requests.USER_SENDER
        lines.append(f"{key}: {value}".rstrip())
    return "---\n" + "\n".join(lines) + sep + body


def _header_rewrite(
    path: Path, keys: dict[str, str], statuses: dict[str, str]
) -> Callable[[], None] | None:
    text = path.read_text(encoding="utf-8")
    new = rewrite_header(text, keys, statuses)
    return None if new == text else (lambda: path.write_text(new, encoding="utf-8"))


def _tsv_rewrite(
    path: Path, columns: dict[str, str], values: dict[str, dict[str, str]] | None = None
) -> Callable[[], None] | None:
    """Column names, and the values of some columns, in place: order, duplicates and the rest stay."""
    text = path.read_text(encoding="utf-8")
    header, *rows = text.split("\n")
    names = [columns.get(c, c) for c in header.split("\t")]
    out = ["\t".join(names)]
    for row in rows:
        cells = row.split("\t")
        for i, name in enumerate(names):
            if i < len(cells) and name in (values or {}):
                cells[i] = values[name].get(cells[i], cells[i])
        out.append("\t".join(cells))
    new = "\n".join(out)
    return None if new == text else (lambda: path.write_text(new, encoding="utf-8"))


def _credential_moves() -> list[tuple[Path, Path]]:
    old_dir = Path(credentials.LEGACY_CONFIG_DIR).expanduser()
    new_dir = Path(credentials.CONFIG_DIR).expanduser()
    if not old_dir.is_dir():
        return []
    return [
        (old, new_dir / old.name)
        for old in sorted(old_dir.glob("*.env"))
        if not (new_dir / old.name).exists()
    ]


def copy_credentials(old: Path, new: Path) -> None:
    lines = []
    for line in old.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key.startswith(credentials.LEGACY_PREFIX):
            service, _, suffix = key.removeprefix(credentials.LEGACY_PREFIX).partition("_")
            key = f"{credentials.PREFIX}{service}_{CREDENTIAL_KEYS.get(suffix, suffix)}"
        lines.append(f"{key}={value.strip()}" if sep else line)
    new.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(new, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def plan(root: Path, base: settings.Config) -> Plan:
    """What migrate would do in root; base carries the values given on the command line (language nl by default)."""
    if (root / settings.FILE).exists():
        raise settings.ConfigError(
            f"{root / settings.FILE} exists; this project is already migrated"
        )
    paths = {**legacy_paths(root), **base.paths}
    c = replace(base, root=root, file=None, paths=paths)
    if c.gedcom == settings.DEFAULT_GEDCOM and (root / LEGACY_GEDCOM).exists():
        c = replace(c, gedcom=LEGACY_GEDCOM)
    result = Plan(c)
    research = c.path("research")
    if (research / TARGETS_FILE).exists():
        if not c.targets:
            result.config = c = replace(c, targets=targets_from(research / TARGETS_FILE))
        result.removals.append(research / TARGETS_FILE)
    if (research / STEMS_FILE).exists():
        if not c.stems:
            result.config = c = replace(c, stems=stems_from(research / STEMS_FILE))
        result.removals.append(research / STEMS_FILE)

    queue_file = c.path("queue")
    if queue_file.exists() and (
        action := _tsv_rewrite(queue_file, queue.LEGACY_COLUMNS, {"status": queue.LEGACY_STATUSES})
    ):
        result.rewrites.append((queue_file, t("English columns and statuses"), action))
    checks = [
        (
            c.path("requests"),
            "*.md",
            lambda p: _header_rewrite(p, requests.LEGACY_KEYS, requests.LEGACY_STATUSES),
        ),
        (
            c.path("forum"),
            "*.md",
            lambda p: _header_rewrite(p, forum.LEGACY_KEYS, forum.LEGACY_STATUSES),
        ),
    ]
    for folder, pattern, rewrite in checks:
        for path in sorted(folder.glob(pattern)) if folder.is_dir() else []:
            if action := rewrite(path):
                result.rewrites.append((path, t("English header keys and status"), action))
    history = c.path("question_history")
    if history.exists() and (action := _tsv_rewrite(history, LEGACY_HISTORY_COLUMNS)):
        result.rewrites.append((history, t("English column names"), action))
    table = coordinates.table_for(c.path("gedcom"))
    if table.exists() and (
        action := _tsv_rewrite(table, coordinates.LEGACY_COLUMNS, {"level": LEGACY_LEVELS})
    ):
        result.rewrites.append((table, t("English column names and levels"), action))
    result.credentials = _credential_moves()
    return result


def _remove(path: Path, root: Path) -> None:
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", str(path)],
        capture_output=True,
        check=False,
    )
    if tracked.returncode == 0:
        subprocess.run(["git", "-C", str(root), "rm", "-q", str(path)], check=True)
    else:
        path.unlink()


def apply(p: Plan) -> None:
    root = p.config.root
    (root / settings.FILE).write_text(settings.dump(p.config), encoding="utf-8")
    for _, _, action in p.rewrites:
        action()
    for path in p.removals:
        _remove(path, root)
    for old, new in p.credentials:
        copy_credentials(old, new)

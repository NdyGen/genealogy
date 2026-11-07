"""Counters of what a research round asks of archives, appended to <output>/metrics.jsonl of the round's
worktree. Outside a round's worktree nothing is recorded."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from lineage import settings

FILE = "metrics.jsonl"


def round_root(start: Path | None = None) -> Path | None:
    """The worktree folder (.worktrees/dr-<ID>) that start lies in, if any."""
    for folder in (start or Path.cwd(), *(start or Path.cwd()).parents):
        if folder.parent.name == ".worktrees" and folder.name.startswith("dr-"):
            return folder
    return None


def record(kind: str, host: str = "", size: int = 0, cached: bool = False) -> None:
    root = round_root()
    if root is None:
        return
    try:
        out = root / settings.current().rel("output")
        out.mkdir(parents=True, exist_ok=True)
        entry = {"t": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "kind": kind}
        if host:
            entry["host"] = host
        if size:
            entry["bytes"] = size
        if cached:
            entry["cached"] = True
        with (out / FILE).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except (OSError, settings.ConfigError):
        # A counter must never stop the research it counts.
        pass


def read(worktree: Path, output: Path) -> list[dict]:
    path = worktree / output / FILE
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries

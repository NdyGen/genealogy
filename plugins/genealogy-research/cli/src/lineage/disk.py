"""Keeps the disk from filling up: rounds fetch whole registers, and every merged round keeps its scans.

When free space drops below `low_gb`, space is freed up to `target_gb`, cheapest to get back first:
- the RAT scan cache (a cached scan still linked into a running round frees nothing and stays);
- whole RAT register pages (`<fonds>-<inventory>/NNNN.jpg`) that a merged round copied to the sources
  folder more than `keep_days` ago and that no tracked file names by path; `lineage rat download`
  fetches them again.
Crops, scans from other archives, manual scans, HTR text and provenance files are never removed.
Below `critical_gb` no round is started or resumed and no register is downloaded.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from lineage import settings
from lineage.i18n import t

GB = 10**9
DEFAULTS = {"low_gb": 20, "target_gb": 40, "critical_gb": 5, "keep_days": 30}
_PAGE = re.compile(r"\d{4}\.jpg")
_INVENTORY = re.compile(r"\d+-[^/]+")
_REFERENCE = re.compile(r"scans/(dr-I\d+(?:/[^\s)`'\"|>,;\]]+)+)")


@dataclass(frozen=True)
class Limits:
    low: int
    target: int
    critical: int
    keep_days: int


def limits(config: settings.Config | None = None) -> Limits:
    values = {**DEFAULTS, **(config or settings.current()).disk}
    return Limits(
        low=int(values["low_gb"] * GB),
        target=int(max(values["target_gb"], values["low_gb"]) * GB),
        critical=int(values["critical_gb"] * GB),
        keep_days=int(values["keep_days"]),
    )


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def too_full(path: Path, config: settings.Config | None = None) -> str | None:
    """The refusal for work that fills the disk, or None while there is room."""
    free = free_bytes(path)
    if free >= limits(config).critical:
        return None
    return t("disk almost full ({free:.1f} GB free); run 'lineage disk prune' first", free=free / GB)


def cache_dir() -> Path:
    from lineage import rat

    return rat._throttle_dir() / "scans"


def references(root: Path) -> set[str]:
    """Scan paths below the sources scan folder that tracked files mention, at least one folder deep in a round:
    a mention of a whole round folder is a pointer, not a citation."""
    out = subprocess.run(
        ["git", "-C", str(root), "grep", "-h", "-I", "-F", "scans/dr-I"],
        capture_output=True,
        text=True,
    ).stdout
    found = set()
    for match in _REFERENCE.finditer(out):
        ref = match.group(1).rstrip("/.:")
        if ref.count("/") >= 2:
            found.add(ref)
    return found


@dataclass(frozen=True)
class Candidate:
    path: Path
    size: int
    mtime: float
    kind: str


def _cached(cache: Path) -> Iterator[Candidate]:
    if not cache.is_dir():
        return
    for p in cache.glob("*.jpg"):
        st = p.stat()
        if st.st_nlink == 1:
            yield Candidate(p, st.st_size, st.st_mtime, "cache")


def _pages(scans: Path, worktrees: Path, refs: set[str], now: float, keep_days: int) -> Iterator[Candidate]:
    for round_dir in scans.glob("dr-I*"):
        if (worktrees / round_dir.name).exists():
            continue
        for p in round_dir.rglob("*.jpg"):
            if not (_PAGE.fullmatch(p.name) and _INVENTORY.fullmatch(p.parent.name)):
                continue
            st = p.stat()
            if now - st.st_mtime < keep_days * 86400:
                continue
            rel = p.relative_to(scans).as_posix()
            if any(rel == r or rel.startswith(r + "/") for r in refs):
                continue
            yield Candidate(p, st.st_size, st.st_mtime, "register")


def candidates(root: Path, now: float, config: settings.Config | None = None,
               cache: Path | None = None) -> list[Candidate]:
    """root is the main checkout, also when called from a worktree: merged scans live there. In removal order: the whole cache before any register page, oldest first within each."""
    config = config or settings.current()
    pages = _pages(root / config.rel("sources") / "scans", root / ".worktrees", references(root), now,
                   limits(config).keep_days)
    return [*sorted(_cached(cache or cache_dir()), key=lambda c: c.mtime),
            *sorted(pages, key=lambda c: c.mtime)]


@dataclass
class Pruned:
    removed: dict[str, int]
    freed: int
    free: int


def prune(root: Path, now: float, config: settings.Config | None = None, dry_run: bool = False,
          cache: Path | None = None, free: Callable[[Path], int] = free_bytes) -> Pruned:
    before = free(root)
    need = limits(config).target - before
    removed: dict[str, int] = {}
    freed = 0
    for c in candidates(root, now, config, cache) if need > 0 else []:
        if freed >= need:
            break
        if not dry_run:
            c.path.unlink(missing_ok=True)
        removed[c.kind] = removed.get(c.kind, 0) + 1
        freed += c.size
    return Pruned(removed, freed, before + freed if dry_run else free(root))


class Keeper:
    """The guard's check: frees space below `low`, and below `critical` tells the user once per episode."""

    def __init__(self, root: Path, log: Callable[[str], None], notify: Callable[[str, str], None] | None = None,
                 dry_run: bool = False, free: Callable[[Path], int] = free_bytes, cache: Path | None = None):
        self.root = root
        self.log = log
        self.notify = notify
        self.dry_run = dry_run
        self.free = free
        self.cache = cache

    def check(self, now: float, state: dict) -> tuple[str, bool]:
        """The status for the log line, and whether rounds may be resumed."""
        lim = limits()
        free = self.free(self.root)
        if free < lim.low:
            done = prune(self.root, now, dry_run=self.dry_run, cache=self.cache, free=self.free)
            if done.removed:
                kinds = ", ".join(f"{n} {kind}" for kind, n in done.removed.items())
                self.log(f"disk: {free / GB:.1f} GB free, removed {kinds} ({done.freed / GB:.1f} GB)")
            free = done.free
        if free >= lim.critical:
            if free >= lim.low:
                state.pop("warned", None)
            return f"disk {free / GB:.0f} GB free", True
        if not state.get("warned"):
            state["warned"] = int(now)
            self.log(f"disk full: {free / GB:.1f} GB free after pruning; resuming paused")
            if self.notify and not self.dry_run:
                try:
                    self.notify(
                        t("Disk almost full: research paused"),
                        t("Only {free:.1f} GB is free on the disk of {root}, also after removing old register "
                          "scans. No research round is started or resumed until there is room again. "
                          "'lineage disk' shows what takes the space.", free=free / GB, root=self.root),
                    )
                except Exception as exc:  # a failed notice must not stop the guard
                    self.log(f"disk notice not sent: {exc}")
        return f"disk FULL {free / GB:.1f} GB free, resuming paused", False


def usage(root: Path, now: float, config: settings.Config | None = None) -> list[str]:
    """Lines for `lineage disk`: free space, limits, and what pruning could remove now."""
    config = config or settings.current()
    lim = limits(config)
    scans = root / config.rel("sources") / "scans"
    lines = [t("free: {free:.1f} GB (prune below {low:.0f} GB up to {target:.0f} GB; stop below {critical:.0f} GB)",
               free=free_bytes(root) / GB, low=lim.low / GB, target=lim.target / GB, critical=lim.critical / GB)]
    if scans.is_dir():
        lines.append(t("scans in {path}: {size:.1f} GB", path=os.path.relpath(scans), size=_size(scans) / GB))
    by_kind: dict[str, list[int]] = {}
    for c in candidates(root, now, config):
        by_kind.setdefault(c.kind, []).append(c.size)
    lines.append(t("removable now: {cache:.1f} GB cache, {pages:.1f} GB register pages older than {days} days",
                   cache=sum(by_kind.get("cache", [])) / GB, pages=sum(by_kind.get("register", [])) / GB,
                   days=lim.keep_days))
    return lines


def _size(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())

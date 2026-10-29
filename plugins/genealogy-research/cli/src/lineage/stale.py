"""Which life stories are out of date: the tree record changed after the story was last written.

Git already dates both sides. `git blame` on the GEDCOM gives, per line, the commit that last changed it;
the newest such commit over a person's own record, his marriages and his children is the record date.
The story date is the last commit that touched reports/life-stories/<ID>.md. The blame is slow
(about half a minute), so its result is cached per GEDCOM blob in the git common dir.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from lineage import settings
from lineage.gedcom import Tree
from lineage.i18n import t
from lineage.kinship import ancestors
from lineage.merge import RESEARCH_NOTE

# The research note is written at merge time, after the story, and says nothing new about the person.
_IGNORED_LINE = RESEARCH_NOTE
_RECORD = re.compile(rb"^0 @([^@]+)@ ")
_SHA = re.compile(r"^([0-9a-f]{40}) \d+ \d+")


@dataclass
class RecordChange:
    time: int
    sha: str
    summary: str


@dataclass
class Stale:
    pid: str
    story_time: int
    change_time: int
    records: list[str] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=True
    ).stdout.decode("utf-8", "replace")


def _cache_path(root: Path) -> Path:
    common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(common) / "dr-stale-cache.json"


def record_changes(root: Path, gedcom: Path | None = None) -> dict[str, RecordChange]:
    """Per record ID, the newest commit that changed one of its lines (ignoring the research note)."""
    gedcom = gedcom or settings.current().rel("gedcom")
    blob = _git(root, "rev-parse", f"HEAD:{gedcom.as_posix()}").strip()
    cache = _cache_path(root)
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("blob") == blob:
            return {k: RecordChange(**v) for k, v in data["records"].items()}
    out = subprocess.run(
        ["git", "-C", str(root), "blame", "-l", "--porcelain", "HEAD", "--", gedcom.as_posix()],
        capture_output=True,
        check=True,
    ).stdout
    commits: dict[str, tuple[int, str]] = {}
    changes: dict[str, RecordChange] = {}
    sha = None
    current = None
    for line in out.split(b"\n"):
        if line.startswith(b"\t"):
            content = line[1:].lstrip(b"\xef\xbb\xbf")
            m = _RECORD.match(content)
            if m:
                current = m[1].decode()
            if current and sha and not _IGNORED_LINE.match(content):
                time, summary = commits[sha]
                known = changes.get(current)
                if known is None or time > known.time:
                    changes[current] = RecordChange(time, sha, summary)
            continue
        m = _SHA.match(line.decode("utf-8", "replace"))
        if m:
            sha = m[1]
            commits.setdefault(sha, (0, ""))
        elif sha and line.startswith(b"committer-time "):
            commits[sha] = (int(line.split()[1]), commits[sha][1])
        elif sha and line.startswith(b"summary "):
            commits[sha] = (commits[sha][0], line[8:].decode("utf-8", "replace"))
    cache.write_text(
        json.dumps({"blob": blob, "records": {k: v.__dict__ for k, v in changes.items()}}),
        encoding="utf-8",
    )
    return changes


def story_times(root: Path, stories: Path | None = None) -> dict[str, int]:
    """Per person with a life story, the last commit that touched it or the last check that left it unchanged."""
    stories = stories or settings.current().rel("life_stories")
    out = _git(root, "log", "--format=%ct", "--name-only", "--", stories.as_posix())
    times: dict[str, int] = dict(checked(root))
    current = 0
    for line in out.splitlines():
        if not line:
            continue
        if line.isdigit():
            current = int(line)
            continue
        m = re.fullmatch(rf"{re.escape(stories.as_posix())}/(I\d+)\.md", line)
        if m:
            times[m[1]] = max(times.get(m[1], 0), current)
    return times


def checked(root: Path) -> dict[str, int]:
    """Stories checked against new facts and left as they were: the check counts as their date."""
    path = root / settings.current().rel("stories_checked")
    if not path.exists():
        return {}
    result: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        pid, _, stamp = line.partition("\t")
        if pid.startswith("I") and stamp:
            result[pid] = max(result.get(pid, 0), int(dt.datetime.fromisoformat(stamp).timestamp()))
    return result


def mark_checked(root: Path, pid: str, now: dt.datetime | None = None) -> None:
    now = now or dt.datetime.now().astimezone()
    path = root / settings.current().rel("stories_checked")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{pid}\t{now.isoformat(timespec='seconds')}\n")


def related_records(tree: Tree, pid: str, direct_line: Collection[str] = ()) -> list[str]:
    """The person, his marriages and the children in them: changes there bear on his story.

    In the direct line the parents' family counts too: those stories are read one after another, so a
    parent's research that contradicts the child's story stands out (that was missed before).
    """
    ids = [pid]
    for family in tree.spouse_families(pid):
        ids.append(family.id)
        ids += [c.id for c in tree.children(family)]
    person = tree.persons.get(pid)
    if pid in direct_line and person and person.child_of:
        ids.append(person.child_of[0])
        ids += [p.id for p in tree.parents(pid) if p]
    return ids


_CONC = re.compile(r"\r?\n\d+ CONC ")
_RECORD_TEXT = re.compile(r"^0 @([^@]+)@ [^\r\n]*\r?\n(.*?)(?=^0 )", re.S | re.M)


def _normalized_records(root: Path, rev: str, gedcom: Path | None = None) -> dict[str, str]:
    """Record texts at a revision with CONC joined and the research note left out, so that
    re-wrapping long lines or stamping the note does not count as a change."""
    gedcom = gedcom or settings.current().rel("gedcom")
    text = _git(root, "show", f"{rev}:{gedcom.as_posix()}").lstrip("\ufeff")
    records = {}
    for m in _RECORD_TEXT.finditer(text):
        body = _CONC.sub("", m[2])
        records[m[1]] = "\n".join(
            line for line in body.splitlines() if not _IGNORED_LINE.match(line.encode())
        )
    return records


def _rev_at(root: Path, when: int) -> str | None:
    rev = _git(root, "rev-list", "-1", f"--before={when}", "HEAD").strip()
    return rev or None


def stale_stories(tree: Tree, root: Path | None = None, with_parents: bool = False) -> list[Stale]:
    """With with_parents, stories in the direct line also go stale on changes to the parents' family."""
    cfg = settings.current()
    root = root or cfg.root
    line_root = cfg.root_person if with_parents else ""
    changes = record_changes(root)
    current = _normalized_records(root, "HEAD")
    snapshots: dict[str, dict[str, str]] = {}
    direct_line = set(ancestors(tree, line_root)) if line_root in tree.persons else set()
    result = []
    for pid, story_time in sorted(story_times(root).items()):
        if pid not in tree.persons:
            continue
        hits = [
            (rid, changes[rid])
            for rid in related_records(tree, pid, direct_line)
            if rid in changes and changes[rid].time > story_time
        ]
        if hits:
            story_rev = _git(
                root, "log", "-1", "--format=%H %ct", "--", f"{cfg.rel('life_stories').as_posix()}/{pid}.md"
            ).split()
            # The story commit itself carries the tree it was written against; a later check has no commit of its own.
            if story_rev and int(story_rev[1]) >= story_time:
                rev = story_rev[0]
            else:
                rev = _rev_at(root, story_time)
            if rev:
                if rev not in snapshots:
                    snapshots[rev] = _normalized_records(root, rev)
                then = snapshots[rev]
                hits = [h for h in hits if then.get(h[0]) != current.get(h[0])]
        if not hits:
            continue
        hits.sort(key=lambda h: -h[1].time)
        stale = Stale(pid, story_time, hits[0][1].time)
        for rid, change in hits:
            stale.records.append(rid)
            if change.summary not in stale.summaries:
                stale.summaries.append(change.summary)
        result.append(stale)
    result.sort(key=lambda s: -s.change_time)
    return result


def _date(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%d-%m-%Y %H:%M")


def report(tree: Tree, stale: list[Stale], short: bool = False) -> str:
    if short:
        return "\n".join(s.pid for s in stale)
    lines = []
    for s in stale:
        person = tree.persons[s.pid]
        lines.append(f"{s.pid:<9} {person.name}")
        changed = t(
            "story {story}, record changed {record}: {ids}",
            story=_date(s.story_time),
            record=_date(s.change_time),
            ids=", ".join(s.records),
        )
        lines.append(f"{'':>10}{changed}")
        for summary in s.summaries[:3]:
            lines.append(f"{'':>10}- {summary[:120]}")
    lines.append("\n" + t("{count} life stories to update", count=len(stale)))
    return "\n".join(lines)

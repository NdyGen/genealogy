"""Cost and yield per research round, one row per merged round in the stats file.

A round is the branch dr/<ID> from its fork point (base) to its tip, merged into main. Its Claude sessions
are the transcripts of its worktree (.worktrees/dr-<ID>) between the fork and the merge, on every account;
the coordinator's review is its turns in the main checkout between the round's last own activity and
`round merge <ID>`. Yield is counted from the GEDCOM diff between base and tip.
"""

from __future__ import annotations

import collections
import csv
import datetime as dt
import re
import statistics
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from lineage import costs, gedcom, htr, metrics, settings, transcripts
from lineage.gedcom import Tree
from lineage.i18n import t
from lineage.transcripts import Session, Usage

ROLES = ("leader", "helpers", "review")
COLUMNS = [
    "id", "kind", "runtime", "start", "merged", "active_min", "leader_sessions", "helper_sessions",
    "limit_hits", "tool_calls",
    *(f"{role}_{kind}" for role in ROLES for kind in ("in", "out", "cache_read", "cache_write")),
    "models", "accounts", "api_eur_leader", "api_eur_helpers", "api_eur_review", "api_eur", "sub_eur",
    "persons_added", "families_added", "events_added", "events_changed", "events_removed",
    "citations_added", "queue_added",
    "oa_requests", "rat_requests", "web_requests", "browser_pages", "download_mb", "scans", "scan_mb",
    "htr_credits", "century", "region",
]  # fmt: skip
SCAN_TYPES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".pdf"}
_STARTED = re.compile(r"deep research (\S+) (?:started|gestart)(.*)$")
_FOLLOW_UP = re.compile(r"follow-up|vervolgronde")
_MERGE = re.compile(r"^Merge branch 'dr/([^']+)'")
_MERGED = re.compile(r"^Deep research (\S+) (?:merged|samengevoegd):")
# Rounds before the plugin merged with `samenvoegen.sh`.
# Any word of a command may be a record ID; only the IDs of known rounds are kept.
_WORD = re.compile(r"[A-Za-z0-9_]+")
_MERGE_CALL = re.compile(r"(?:round merge|merge\.sh|samenvoegen(?:\.sh)?)\s+@?(\w+)")
_HELPER_PROMPT = re.compile(r"^(?:Read the brief|Lees de opdracht)")
# Countries whose places are written "place, province, country"; elsewhere the country is the region.
_BY_PROVINCE = {"nederland", "netherlands", "belgië", "belgie", "belgium"}


@dataclass(frozen=True)
class Round:
    id: str
    base: str
    tip: str
    start: dt.datetime
    finished: dt.datetime
    merged: dt.datetime | None
    kind: str
    opencode: bool = False


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def _show(root: Path, commit: str, path: Path) -> str | None:
    try:
        return _git(root, "show", f"{commit}:{path.as_posix()}")
    except subprocess.CalledProcessError:
        return None


def main_root(start: Path) -> Path:
    """The main checkout, also from inside a round's worktree: the parent of the git common dir."""
    common = _git(start, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(common).parent


def main_branch(root: Path) -> str:
    for name in ("main", "master"):
        if (
            subprocess.run(
                ["git", "-C", str(root), "show-ref", "--verify", "--quiet", f"refs/heads/{name}"]
            ).returncode
            == 0
        ):
            return name
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()


def stats_path(root: Path) -> Path:
    return root / settings.current().rel("stats")


def _commit_time(root: Path, commit: str) -> dt.datetime:
    return dt.datetime.fromtimestamp(int(_git(root, "log", "-1", "--format=%ct", commit)), dt.UTC)


def make_round(root: Path, pid: str, base: str, tip: str, merged: dt.datetime | None) -> Round:
    subject = _git(root, "log", "-1", "--format=%s", base).strip()
    started = _STARTED.search(subject)
    config = settings.current()
    if started and started[1].upper() == pid:
        kind = "follow-up" if _FOLLOW_UP.search(started[2]) else "normal"
    else:
        changed = _git(
            root,
            "diff",
            "--name-only",
            base,
            tip,
            "--",
            str(config.rel("gedcom")),
            str(config.rel("queue")),
        )
        kind = "normal" if changed.strip() else "update"
    start, finished = _commit_time(root, base), _commit_time(root, tip)
    return Round(pid, base, tip, start, finished, merged, kind, "opencode" in subject.lower())


def merged_rounds(root: Path, branch: str = "main", since: dt.datetime | None = None) -> list[Round]:
    """Every round merged into branch, oldest first: a merge commit of dr/<ID>, or, when main had not
    moved and the merge was a fast-forward, the commit 'Deep research <ID> merged' right after the
    branch's commits, which then started at the last start commit of that ID."""
    rounds = []
    last_start: dict[str, str] = {}
    previous = ("", "")
    log = _git(root, "log", "--first-parent", "--reverse", "--format=%H %P%x09%ct%x09%s", branch)
    for line in log.splitlines():
        hashes, when, subject = line.split("\t", 2)
        commit, *parents = hashes.split()
        merged = dt.datetime.fromtimestamp(int(when), dt.UTC)
        recent = since is None or merged >= since
        if (started := _STARTED.search(subject)) and subject.startswith(("Queue:", "Wachtrij:")):
            last_start[started[1].upper()] = commit
        elif (match := _MERGE.match(subject)) and len(parents) == 2 and recent:
            base = _git(root, "merge-base", *parents).strip()
            rounds.append(make_round(root, match[1].upper(), base, parents[1], merged))
        elif (match := _MERGED.match(subject)) and parents and recent:
            pid = match[1].upper()
            follows_merge = _MERGE.match(previous[1]) and previous[0] == parents[0]
            if not follows_merge and pid in last_start and last_start[pid] != parents[0]:
                rounds.append(make_round(root, pid, last_start[pid], parents[0], merged))
        previous = (commit, subject)
    return rounds


# --- Claude usage -----------------------------------------------------------------------------------


@dataclass
class Spend:
    usage: dict[tuple[str, str, str], Usage] = field(default_factory=dict)  # (role, model, account)
    sessions: collections.Counter[str] = field(default_factory=collections.Counter)
    limit_hits: int = 0
    tool_calls: int = 0
    active: dt.timedelta = dt.timedelta()
    # The last turn of the round's own sessions: where the coordinator's review can begin.
    last: dt.datetime | None = None

    def add(self, role: str, model: str, account: str, usage: Usage, weight: float = 1.0) -> None:
        self.usage.setdefault((role, model, account), Usage()).add(usage, weight)


def _role(session: Session) -> str:
    if session.subagent or _HELPER_PROMPT.match(session.first_prompt):
        return "helpers"
    return "leader"


class Coordinator:
    """The coordinator's review of each round in the main checkout's sessions, read once.

    A review window runs from the first command (of the session or its sub-agents) that names the round's
    ID after the round's own sessions ended, to the merge call. Not after its last commit: the coordinator
    commits its corrections on the round's branch. Older coordinators had no `review` command, so the
    window does not depend on it. Where no merge call is in the transcripts (a merge from a background task
    or the watcher), the window runs to the last command naming the ID before the merge. Turns inside two
    windows are split between both rounds."""

    def __init__(
        self,
        root: Path,
        accounts: dict[str, Path],
        since: dt.datetime,
        rounds: list[Round],
        ends: dict[str, dt.datetime] | None = None,
    ):
        # (account, session family, round tip, start, end); the family is the session and its sub-agents.
        self.windows: list[tuple[str, list[Session], str, dt.datetime, dt.datetime]] = []
        sessions: list[tuple[str, Session]] = []
        # A review sub-agent (<session id>/subagents/*.jsonl) works inside its parent's window.
        children: dict[Path, list[Session]] = collections.defaultdict(list)
        for account, config_dir in accounts.items():
            folder = transcripts.project_dir(config_dir, root)
            for session in transcripts.sessions(folder, config_dir, since):
                if session.subagent:
                    parent = session.path.parent
                    if parent.name == "subagents":
                        parent = parent.parent
                    children[parent.with_suffix(".jsonl")].append(session)
                else:
                    sessions.append((account, session))
        wanted = {r.id for r in rounds}
        indexed = []
        for account, session in sessions:
            family = [session, *children.get(session.path, [])]
            named: dict[str, list[dt.datetime]] = collections.defaultdict(list)
            for message in (m for s in family for m in s.messages.values()):
                for command in message.commands:
                    for pid in {w.upper() for w in _WORD.findall(command)} & wanted:
                        named[pid].append(message.time)
            merges = [
                (pid.upper(), m.time)
                for m in session.messages.values()
                for c in m.commands
                for pid in _MERGE_CALL.findall(c)
            ]
            indexed.append((account, family, {k: sorted(v) for k, v in named.items()}, merges))
        for r in rounds:
            if r.merged is None:
                continue
            late = r.merged + dt.timedelta(minutes=10)
            finished = (ends or {}).get(r.tip) or r.finished
            found = []
            for account, family, named, merges in indexed:
                for pid, call in merges:
                    if pid == r.id and finished <= call <= late:
                        first = [t for t in named.get(pid, []) if finished <= t <= call]
                        found.append((account, family, r.tip, min(first, default=call), call))
            if not found:
                for account, family, named, _ in indexed:
                    inside = [t for t in named.get(r.id, []) if finished <= t <= late]
                    if inside:
                        found.append((account, family, r.tip, inside[0], inside[-1]))
            self.windows += found

    def spend(self, round_: Round, into: Spend) -> None:
        for account, family, tip, start, end in self.windows:
            if tip != round_.tip:
                continue
            others = [(s, e) for _, fam, _, s, e in self.windows if fam[0] is family[0]]
            for message in (m for s in family for m in s.messages.values()):
                if start <= message.time <= end:
                    overlap = sum(1 for s, e in others if s <= message.time <= e)
                    into.add("review", message.model, account, message.usage, 1 / overlap)


def round_spend(root: Path, round_: Round, accounts: dict[str, Path]) -> Spend:
    spend = Spend()
    end = round_.merged or dt.datetime.now(dt.UTC)
    worktree = root / ".worktrees" / f"dr-{round_.id}"
    times = []
    for account, config_dir in accounts.items():
        folder = transcripts.project_dir(config_dir, worktree)
        for session in transcripts.sessions(folder, config_dir, round_.start):
            inside = [m for m in session.messages.values() if round_.start <= m.time <= end]
            if not inside:
                continue
            role = _role(session)
            spend.sessions[role] += 1
            times.append(session.times)
            spend.limit_hits += len(session.limit_hits(round_.start, end))
            for message in inside:
                spend.add(role, message.model, account, message.usage)
                spend.tool_calls += len(message.tool_uses)
            latest = max(m.time for m in inside)
            spend.last = max(spend.last or latest, latest)
    spend.active = transcripts.active_time(times, round_.start, end)
    return spend


def measure(
    root: Path, rounds: list[Round], accounts: dict[str, Path], notify=None
) -> dict[str, Spend]:
    """Each round's own spend plus the coordinator's review of it, by the round's tip."""
    spends = {}
    for i, r in enumerate(rounds, 1):
        spends[r.tip] = round_spend(root, r, accounts)
        if notify and i % 100 == 0:
            notify(t("{done} of {total} rounds", done=i, total=len(rounds)))
    ends = {tip: s.last for tip, s in spends.items() if s.last}
    coordinator = Coordinator(root, accounts, min(r.start for r in rounds), rounds, ends)
    for r in rounds:
        coordinator.spend(r, spends[r.tip])
    return spends


# --- yield from the GEDCOM diff ------------------------------------------------------------------------


@dataclass
class Yield:
    persons_added: int = 0
    families_added: int = 0
    events_added: int = 0
    events_changed: int = 0
    events_removed: int = 0
    citations_added: int = 0
    queue_added: int = 0

    @property
    def facts(self) -> int:
        return self.events_added + self.events_changed + self.events_removed


def _records(tree: Tree) -> dict[str, list]:
    return {
        **{p.id: p.events for p in tree.persons.values()},
        **{f.id: f.events for f in tree.families.values()},
    }


def _citations(tree: Tree) -> collections.Counter:
    found: collections.Counter = collections.Counter()
    for pid, person in tree.persons.items():
        found.update((pid, c.source_id, c.page) for c in person.all_citations())
    for fid, family in tree.families.items():
        found.update((fid, c.source_id, c.page) for e in family.events for c in e.citations)
    return found


def tree_yield(before: Tree, after: Tree) -> Yield:
    y = Yield(
        persons_added=len(after.persons.keys() - before.persons.keys()),
        families_added=len(after.families.keys() - before.families.keys()),
    )
    old, new = _records(before), _records(after)
    for record in old.keys() | new.keys():
        buckets: dict[str, list[collections.Counter]] = collections.defaultdict(
            lambda: [collections.Counter(), collections.Counter()]
        )
        for side, events in enumerate((old.get(record, []), new.get(record, []))):
            for e in events:
                buckets[e.tag][side][(str(e.date or ""), e.place, e.value)] += 1
        for was, now in buckets.values():
            removed, added = sum((was - now).values()), sum((now - was).values())
            changed = min(removed, added)
            y.events_changed += changed
            y.events_removed += removed - changed
            y.events_added += added - changed
    y.citations_added = sum((_citations(after) - _citations(before)).values())
    return y


def _queue_ids(text: str | None) -> set[str]:
    if not text:
        return set()
    return {line.split("\t", 1)[0] for line in text.splitlines()[1:] if line.strip()}


def round_yield(root: Path, round_: Round) -> tuple[Yield, Tree]:
    """The yield, and the tree at the round's tip."""
    config = settings.current()
    before = _show(root, round_.base, config.rel("gedcom")) or ""
    after = _show(root, round_.tip, config.rel("gedcom")) or ""
    tip = gedcom.parse(after)
    y = tree_yield(gedcom.parse(before), tip) if before != after else Yield()
    y.queue_added = len(
        _queue_ids(_show(root, round_.tip, config.rel("queue")))
        - _queue_ids(_show(root, round_.base, config.rel("queue")))
    )
    return y, tip


# --- the person -----------------------------------------------------------------------------------------


def century(tree: Tree, pid: str) -> str:
    person = tree.persons.get(pid)
    if person is None:
        return ""
    date = person.birth_date or next(
        (e.date for e in person.events if e.date and e.date.year), None
    )
    return f"{date.year // 100 * 100}" if date and date.year else ""


def region(tree: Tree, pid: str) -> str:
    """Province (Netherlands, Belgium) or country of the place the person's events name most."""
    person = tree.persons.get(pid)
    places = collections.Counter(e.place for e in (person.events if person else []) if e.place)
    if not places:
        return ""
    parts = [p.strip() for p in places.most_common(1)[0][0].split(",") if p.strip()]
    if len(parts) >= 3 and parts[-1].lower() in _BY_PROVINCE:
        return parts[-2]
    return parts[-1]


# --- archives and scans -----------------------------------------------------------------------------------


def _htr_credits(round_: Round) -> int:
    path = htr.log_path()
    if not path.exists():
        return 0
    end = round_.merged or dt.datetime.now(dt.UTC)
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        when, _, rest = line.partition("\t")
        image = rest.partition("\t")[2]
        stamp = transcripts.parse_time(when)
        if stamp is None or f"/dr-{round_.id}/" not in image:
            continue
        count += round_.start <= stamp.astimezone() <= end
    return count


def _scans(root: Path, round_: Round) -> tuple[int, int] | None:
    config = settings.current()
    worktree_out = root / ".worktrees" / f"dr-{round_.id}" / config.rel("output")
    kept = root / config.rel("sources") / "scans" / f"dr-{round_.id}"
    folder = worktree_out if worktree_out.is_dir() else kept
    if not folder.is_dir():
        return None
    files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in SCAN_TYPES]
    return len(files), sum(p.stat().st_size for p in files)


# --- one row -----------------------------------------------------------------------------------------------


def _local(when: dt.datetime | None) -> str:
    return when.astimezone().isoformat(timespec="minutes") if when else ""


def _mb(size: int) -> str:
    return f"{size / 1_000_000:.1f}"


def row(root: Path, round_: Round, spend: Spend) -> dict[str, str]:
    prices = costs.table()
    out: dict[str, str] = {c: "" for c in COLUMNS}
    # Review turns alone (an opencode round, transcripts already deleted) do not make a measured round.
    found = spend.sessions.total() > 0
    out.update(
        id=round_.id,
        kind=round_.kind,
        runtime="claude" if found else ("opencode" if round_.opencode else ""),
        start=_local(round_.start),
        merged=_local(round_.merged),
    )
    if found:
        per_role = {role: Usage() for role in ROLES}
        per_model: dict[str, Usage] = collections.defaultdict(Usage)
        eur_role = dict.fromkeys(ROLES, 0.0)
        eur_account: dict[str, float] = collections.defaultdict(float)
        for (role, model, account), usage in spend.usage.items():
            per_role[role].add(usage)
            per_model[model].add(usage)
            eur = prices.eur(model, usage)
            eur_role[role] += eur
            eur_account[account] += eur
        for role, usage in per_role.items():
            out[f"{role}_in"] = str(usage.input)
            out[f"{role}_out"] = str(usage.output)
            out[f"{role}_cache_read"] = str(usage.cache_read)
            out[f"{role}_cache_write"] = str(usage.cache_write_5m + usage.cache_write_1h)
            out[f"api_eur_{role}"] = f"{eur_role[role]:.2f}"
        subscription = [costs.subscription_eur(a, e) for a, e in eur_account.items()]
        out.update(
            active_min=str(round(spend.active.total_seconds() / 60)),
            leader_sessions=str(spend.sessions["leader"]),
            helper_sessions=str(spend.sessions["helpers"]),
            limit_hits=str(spend.limit_hits),
            tool_calls=str(spend.tool_calls),
            models=";".join(
                f"{m}={u.total}" for m, u in sorted(per_model.items()) if m != transcripts.SYNTHETIC
            ),
            accounts=";".join(sorted(eur_account)),
            api_eur=f"{sum(eur_role.values()):.2f}",
            sub_eur=f"{sum(subscription):.2f}" if None not in subscription else "",  # type: ignore[arg-type]
        )
    y, tree = round_yield(root, round_)
    out.update({k: str(v) for k, v in vars(y).items()})
    entries = metrics.read(
        root / ".worktrees" / f"dr-{round_.id}", settings.current().rel("output")
    )
    if entries:
        kinds = collections.Counter(e.get("kind") for e in entries)
        out.update(
            oa_requests=str(kinds["openarchieven"]),
            rat_requests=str(kinds["rat"]),
            web_requests=str(kinds["web"]),
            browser_pages=str(kinds["browser"]),
            download_mb=_mb(sum(int(e.get("bytes") or 0) for e in entries)),
        )
    if scans := _scans(root, round_):
        out.update(scans=str(scans[0]), scan_mb=_mb(scans[1]))
    out["htr_credits"] = str(_htr_credits(round_))
    out.update(century=century(tree, round_.id), region=region(tree, round_.id))
    return out


# --- the stats file ----------------------------------------------------------------------------------------


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [{c: r.get(c) or "" for c in COLUMNS} for r in csv.DictReader(f, delimiter="\t")]


def write_rows(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: (r["merged"] or "9999", r["id"]))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, COLUMNS, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(ordered)


def upsert(path: Path, new: Iterable[dict[str, str]]) -> None:
    rows = {(r["id"], r["merged"]): r for r in read_rows(path)}
    rows.update({(r["id"], r["merged"]): r for r in new})
    write_rows(path, rows.values())


def record(root: Path, pid: str, base: str, tip: str) -> dict[str, str]:
    """The row of a round being merged now; written to the stats file."""
    round_ = make_round(root, pid, base, tip, dt.datetime.now(dt.UTC))
    accounts = costs.account_dirs()
    recent = merged_rounds(root, main_branch(root), since=round_.start - dt.timedelta(days=1))
    spend = measure(root, [*recent, round_], accounts)[round_.tip]
    found = row(root, round_, spend)
    upsert(stats_path(root), [found])
    return found


def live(root: Path, pid: str) -> dict[str, str]:
    """The row of a round not merged yet, from its branch (no coordinator review counted)."""
    tip = _git(root, "rev-parse", f"dr/{pid}").strip()
    base = _git(root, "merge-base", main_branch(root), tip).strip()
    round_ = make_round(root, pid, base, tip, None)
    return row(root, round_, round_spend(root, round_, costs.account_dirs()))


def backfill(root: Path, force: bool = False, notify=print) -> int:
    path = stats_path(root)
    known = {(r["id"], r["merged"]) for r in read_rows(path)}
    todo = [
        r
        for r in merged_rounds(root, main_branch(root))
        if force or (r.id, _local(r.merged)) not in known
    ]
    if not todo:
        return 0
    spends = measure(root, todo, costs.account_dirs(), notify)
    rows = []
    for i, round_ in enumerate(todo, 1):
        rows.append(row(root, round_, spends[round_.tip]))
        if i % 25 == 0:
            notify(t("{done} of {total} rounds", done=i, total=len(todo)))
            upsert(path, rows)
            rows = []
    upsert(path, rows)
    return len(todo)


# --- summaries ---------------------------------------------------------------------------------------------


def _float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


@dataclass
class Group:
    name: str
    rows: list[dict[str, str]]

    def values(self, column: str) -> list[float]:
        return [v for r in self.rows if (v := _float(r[column])) is not None]

    def per_fact(self) -> float | None:
        facts = sum(
            int(r["events_added"] or 0)
            + int(r["events_changed"] or 0)
            + int(r["events_removed"] or 0)
            for r in self.rows
        )
        return sum(self.values("api_eur")) / facts if facts else None


def _median(values: list[float]) -> str:
    return f"{statistics.median(values):.2f}" if values else "-"


def _mean(values: list[float]) -> str:
    return f"{statistics.mean(values):.2f}" if values else "-"


def summary(rows: list[dict[str, str]]) -> str:
    measured = [r for r in rows if r["runtime"] == "claude" and r["api_eur"]]
    if not measured:
        return t("no measured rounds in the stats file; run 'lineage stats backfill' first")
    lines = [
        t(
            "{count} measured rounds (of {total} in the stats file)",
            count=len(measured),
            total=len(rows),
        ),
        "",
        "\t".join(
            [
                t("group"),
                "n",
                t("median EUR"),
                t("mean EUR"),
                t("median subscr. EUR"),
                t("EUR/fact"),
                t("median active min"),
            ]
        ),
    ]
    splits = [
        (t("all"), lambda r: t("all")),
        (t("kind"), lambda r: r["kind"]),
        (t("century"), lambda r: r["century"] or "?"),
        (t("region"), lambda r: r["region"] or "?"),
    ]
    for label, key in splits:
        groups: dict[str, list] = collections.defaultdict(list)
        for r in measured:
            groups[key(r)].append(r)
        if label != t("all"):
            lines.append(f"-- {label}")
        for name in sorted(groups):
            g = Group(name, groups[name])
            fact = g.per_fact()
            lines.append(
                "\t".join(
                    [
                        name,
                        str(len(g.rows)),
                        _median(g.values("api_eur")),
                        _mean(g.values("api_eur")),
                        _median(g.values("sub_eur")),
                        f"{fact:.2f}" if fact is not None else "-",
                        _median(g.values("active_min")),
                    ]
                )  # fmt: skip
            )
    total = sum(_float(r["api_eur"]) or 0 for r in measured)
    if total:
        lines += ["", t("share of API cost")]
        labels = {"leader": t("leader"), "helpers": t("helpers"), "review": t("review")}
        for role in ROLES:
            part = sum(_float(r[f"api_eur_{role}"]) or 0 for r in measured)
            lines.append(f"{labels[role]}\t{part:.2f}\t{part / total:.0%}")
    return "\n".join(lines)


def cost_line(r: dict[str, str]) -> str:
    """One line for the coordinator's report of a merge."""
    facts = sum(int(r[k] or 0) for k in ("events_added", "events_changed", "events_removed"))
    api = _float(r["api_eur"])
    per_fact = f"{api / facts:.2f}" if api is not None and facts else "-"
    return t(
        "cost {id}: EUR {api} at API prices (review EUR {review}), subscription EUR {sub}; "
        "{minutes} min active; {facts} facts, EUR {per_fact} per fact",
        id=r["id"], api=r["api_eur"] or "-", review=r["api_eur_review"] or "-", sub=r["sub_eur"] or "-",
        minutes=r["active_min"] or "-", facts=facts, per_fact=per_fact,
    )  # fmt: skip


def describe(r: dict[str, str]) -> str:
    """One round, human readable."""

    def tokens(role: str) -> str:
        return t(
            "in {i}, out {o}, cache read {cr}, cache write {cw}",
            i=r[f"{role}_in"] or "-", o=r[f"{role}_out"] or "-",
            cr=r[f"{role}_cache_read"] or "-", cw=r[f"{role}_cache_write"] or "-",
        )  # fmt: skip

    lines = [
        t("{id} ({kind} round, {runtime}), {start} to {merged}", id=r["id"], kind=r["kind"],
          runtime=r["runtime"] or "?", start=r["start"], merged=r["merged"] or t("not merged")),
        t("API cost: EUR {total} (leader {leader}, helpers {helpers}, review {review}); subscription: EUR {sub}",
          total=r["api_eur"] or "-", leader=r["api_eur_leader"] or "-", helpers=r["api_eur_helpers"] or "-",
          review=r["api_eur_review"] or "-", sub=r["sub_eur"] or "-"),
        t("leader tokens: {tokens}", tokens=tokens("leader")),
        t("helper tokens: {tokens}", tokens=tokens("helpers")),
        t("review tokens: {tokens}", tokens=tokens("review")),
        t("models: {models}; accounts: {accounts}", models=r["models"] or "-", accounts=r["accounts"] or "-"),
        t("active {minutes} min; sessions: {leader} leader, {helpers} helpers; {hits} limit hits; {tools} tool calls",
          minutes=r["active_min"] or "-", leader=r["leader_sessions"] or "-", helpers=r["helper_sessions"] or "-",
          hits=r["limit_hits"] or "-", tools=r["tool_calls"] or "-"),
        t("archives: {oa} Open Archieven, {rat} RAT, {web} web, {browser} browser pages, {mb} MB; "
          "{scans} scans ({scan_mb} MB); {htr} Transkribus credits",
          oa=r["oa_requests"] or "-", rat=r["rat_requests"] or "-", web=r["web_requests"] or "-",
          browser=r["browser_pages"] or "-", mb=r["download_mb"] or "-", scans=r["scans"] or "-",
          scan_mb=r["scan_mb"] or "-", htr=r["htr_credits"] or "-"),
        t("yield: {persons} persons and {families} families added; events {added} added, {changed} changed, "
          "{removed} removed; {citations} citations; {queue} added to the queue",
          persons=r["persons_added"], families=r["families_added"], added=r["events_added"],
          changed=r["events_changed"], removed=r["events_removed"], citations=r["citations_added"],
          queue=r["queue_added"]),
        t("person: century {century}, region {region}", century=r["century"] or "?", region=r["region"] or "?"),
    ]  # fmt: skip
    return "\n".join(lines)

import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest

from lineage import costs, metrics, roundstats, settings, transcripts
from lineage.gedcom import parse
from lineage.transcripts import Usage
from tests.conftest import ged, project

T0 = dt.datetime(2026, 11, 1, 10, 0, tzinfo=dt.UTC)
QUEUE = "id\tstatus\tpriority\tround\tvia\treason\tadded\tid_block\treport\n"
PERSON = (
    "0 @I1@ INDI", "1 NAME Peter /Hart/", "1 BIRT", "2 DATE 1702", "2 PLAC Breda, Noord-Brabant, Nederland",
)  # fmt: skip


def _at(minutes: float) -> str:
    return (T0 + dt.timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def assistant(minutes, msg_id, model="claude-opus-5-5", usage=None, blocks=()):
    return {
        "type": "assistant",
        "timestamp": _at(minutes),
        "message": {
            "id": msg_id,
            "model": model,
            "usage": usage or {"input_tokens": 10, "output_tokens": 100, "cache_read_input_tokens": 1000,
                               "cache_creation_input_tokens": 200,
                               "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 200}},
            "content": list(blocks),
        },
    }  # fmt: skip


def user(minutes, text):
    return {"type": "user", "timestamp": _at(minutes), "message": {"role": "user", "content": text}}


def bash(command, tool_id="t1"):
    return {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}


def write_session(path: Path, *entries) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


# --- transcripts ---------------------------------------------------------------------------------------


def test_usage_counts_once_per_message_and_blocks_all(tmp_path):
    path = write_session(
        tmp_path / "s.jsonl",
        user(0, "Use the deep-research skill for person I1."),
        assistant(1, "m1", blocks=[{"type": "text", "text": "a"}]),
        assistant(1, "m1", blocks=[bash("ls", "t1")]),
        assistant(2, "m1", blocks=[bash("pwd", "t2")]),
    )
    session = transcripts.read(path, tmp_path)
    assert session.first_prompt.startswith("Use the deep-research skill")
    [message] = session.messages.values()
    assert message.usage == Usage(10, 100, 1000, 0, 200)
    assert message.tool_uses == {"t1", "t2"}
    assert message.commands == ["ls", "pwd"]


def test_cache_write_without_split_counts_as_five_minutes():
    usage = Usage.from_api({"input_tokens": 1, "output_tokens": 2, "cache_creation_input_tokens": 50})
    assert (usage.cache_write_5m, usage.cache_write_1h) == (50, 0)


def test_active_time_joins_parallel_sessions_and_skips_long_gaps():
    def times(*minutes):
        return [T0 + dt.timedelta(minutes=m) for m in minutes]

    leader = times(0, 5, 10, 60, 65)  # 0-10 and 60-65 active; the 50-minute gap is a wait
    helper = times(8, 12)  # overlaps the leader from 8 to 10
    total = transcripts.active_time([leader, helper], T0, T0 + dt.timedelta(hours=2))
    assert total == dt.timedelta(minutes=17)


def test_project_dir_replaces_every_non_alphanumeric():
    folder = transcripts.project_dir(Path("/c"), Path("/home/a/proj/.worktrees/dr-I1"))
    assert folder == Path("/c/projects/-home-a-proj--worktrees-dr-I1")


# --- prices and subscription ------------------------------------------------------------------------------


def test_eur_at_api_prices():
    prices = costs.PriceTable({"claude-opus-5-5": (4.0, 20.0, 0.2)}, usd_eur=0.5)
    usage = Usage(input=1_000_000, output=1_000_000, cache_read=1_000_000, cache_write_5m=1_000_000,
                  cache_write_1h=1_000_000)  # fmt: skip
    assert prices.eur("claude-opus-5-5", usage) == pytest.approx((4 + 20 + 0.2 + 5 + 8) * 0.5)
    assert prices.eur("claude-opus-5-5-20260101", usage) == prices.eur("claude-opus-5-5", usage)
    assert prices.eur(transcripts.SYNTHETIC, usage) == 0
    with pytest.raises(costs.PriceError):
        prices.eur("claude-unknown", usage)


def test_prices_from_lineage_toml(tmp_path):
    file = tmp_path / settings.FILE
    config = settings.parse('[prices]\nusd_eur = 0.9\n"claude-new-1" = [1, 2, 0.1]\n', file)
    table = costs.table(config)
    assert table.usd_eur == 0.9
    assert table.price("claude-new-1") == (1.0, 2.0, 0.1)
    assert table.price("claude-opus-5-5") == costs.PRICES["claude-opus-5-5"]
    with pytest.raises(settings.ConfigError):
        settings.parse('[prices]\n"claude-x" = [1, 2]\n', file)
    assert settings.parse(settings.dump(config), file).prices == config.prices


def test_subscription_share_needs_price_and_budget(tmp_path):
    config = project(tmp_path, accounts={"personal": {"subscription_eur": "90", "monthly_budget_eur": "900"},
                                         "work": {"subscription_eur": "90"}})  # fmt: skip
    assert costs.subscription_eur("personal", 30.0, config) == pytest.approx(3.0)
    assert costs.subscription_eur("work", 30.0, config) is None


def test_account_values_are_written_in_place(tmp_path):
    file = tmp_path / "lineage.toml"
    file.write_text('# mine\n[accounts.personal]\nconfig_dir = "/x"\nmonthly_budget_eur = 1\n\n[mail]\n', "utf-8")
    costs.write_account_values(file, "personal", {"monthly_budget_eur": "500", "calibrated": '"2026-11-07"'})
    costs.write_account_values(file, "work", {"monthly_budget_eur": "300"})
    text = file.read_text("utf-8")
    assert text.startswith("# mine\n[accounts.personal]\nconfig_dir = \"/x\"\nmonthly_budget_eur = 500\n"
                           'calibrated = "2026-11-07"\n\n[mail]')  # fmt: skip
    assert settings.parse(text, file).accounts["work"] == {"monthly_budget_eur": "300"}


def test_calibration_takes_the_week_before_a_weekly_limit(tmp_path):
    hit = dt.datetime(2026, 10, 14, 20, 0).astimezone()
    limit = "You've hit your weekly limit · resets Oct 15, 12am (Europe/Amsterdam)"
    reset = dt.datetime(2026, 10, 15, 0, 0).astimezone()

    def entry(when, msg_id, model="claude-opus-5-5", text=""):
        e = assistant(0, msg_id, model, blocks=[{"type": "text", "text": text}] if text else [])
        e["timestamp"] = when.astimezone(dt.UTC).isoformat()
        if model == transcripts.SYNTHETIC:
            e["message"]["usage"] = {}
        return e

    write_session(
        tmp_path / "projects/-p/s.jsonl",
        entry(reset - dt.timedelta(days=8), "before"),  # outside the week
        entry(reset - dt.timedelta(days=3), "inside"),
        entry(hit, "limit", transcripts.SYNTHETIC, limit),
    )
    prices = costs.PriceTable(costs.PRICES, 1.0)
    [week] = costs.calibrate(tmp_path, prices)
    one = prices.eur("claude-opus-5-5", Usage.from_api(assistant(0, "x")["message"]["usage"]))
    assert week.api_eur == pytest.approx(one)
    assert week.start == reset.replace(tzinfo=None) - dt.timedelta(days=7)
    assert costs.monthly_budget([week]) == pytest.approx(week.monthly)


# --- yield ----------------------------------------------------------------------------------------------------


def test_yield_counts_events_persons_and_citations():
    before = parse(ged(*PERSON, "1 DEAT", "2 DATE 1750", "0 @S1@ SOUR", "1 TITL Register"))
    after = parse(ged(
        *PERSON[:3], "2 DATE 12 MAR 1702", "2 PLAC Breda, Noord-Brabant, Nederland", "2 SOUR @S1@", "3 PAGE fol. 3",
        "1 BURI", "2 DATE 1760",
        "0 @I2@ INDI", "1 NAME Anna /Cole/", "1 BIRT", "2 DATE 1705",
        "0 @S1@ SOUR", "1 TITL Register",
    ))  # fmt: skip
    y = roundstats.tree_yield(before, after)
    assert (y.persons_added, y.events_changed, y.events_added, y.events_removed) == (1, 1, 2, 1)
    assert y.citations_added == 1
    assert y.facts == 4


def test_century_and_region():
    tree = parse(ged(*PERSON, "0 @I2@ INDI", "1 DEAT", "2 PLAC Oberhaid, Rheinland-Pfalz, Deutschland"))
    assert roundstats.century(tree, "I1") == "1700"
    assert roundstats.region(tree, "I1") == "Noord-Brabant"
    assert roundstats.region(tree, "I2") == "Deutschland"
    assert roundstats.century(tree, "I9") == roundstats.region(tree, "I9") == ""


# --- rounds from git, end to end ------------------------------------------------------------------------------


def _git(root: Path, *args: str, when: dt.datetime | None = None) -> str:
    stamp = (when or T0).isoformat()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp,
           "HOME": str(root), "PATH": "/usr/bin:/bin"}  # fmt: skip
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True, env=env).stdout


def _commit(root: Path, message: str, minutes: float, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message, when=T0 + dt.timedelta(minutes=minutes))


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "lineage.toml").write_text('[accounts.personal]\nconfig_dir = "%s"\n' % (tmp_path / "cfg"), "utf-8")
    _commit(root, "tree", -60, {"data/tree.ged": ged(*PERSON) + "\n", "research/queue.tsv": QUEUE})
    settings.use(settings.load(root))
    return root


def _round(root: Path, pid: str, start: float, end: float, *, fast_forward: bool) -> None:
    _commit(root, f"Queue: deep research {pid} started", start, {"research/queue.tsv": QUEUE + f"{pid}\tin_progress\n"})
    _git(root, "checkout", "-qb", f"dr/{pid}")
    _commit(root, f"{pid}: baptism", start + 5, {
        "data/tree.ged": ged(*PERSON, "1 CHR", "2 DATE 13 MAR 1702") + "\n",
        "research/queue.tsv": QUEUE + f"{pid}\tin_progress\nI7\topen\n",
    })  # fmt: skip
    _git(root, "checkout", "-q", "main")
    if not fast_forward:
        _commit(root, "Log", start + 6, {"research/log.md": "x\n"})
    _git(root, "merge", "--no-edit", "-q", f"dr/{pid}", when=T0 + dt.timedelta(minutes=end))
    _commit(root, f"Deep research {pid} merged: queue updated, duplicate source records removed", end + 0.5,
            {"research/queue.tsv": QUEUE + f"{pid}\tdone\nI7\topen\n"})  # fmt: skip
    _git(root, "branch", "-qd", f"dr/{pid}")


def test_rounds_are_found_with_and_without_merge_commit(repo):
    _round(repo, "I1", 0, 30, fast_forward=False)
    _round(repo, "I1", 100, 130, fast_forward=True)
    first, second = roundstats.merged_rounds(repo)
    assert (first.id, first.kind, second.kind) == ("I1", "normal", "normal")
    assert first.start == T0 and second.start == T0 + dt.timedelta(minutes=100)
    assert second.merged == T0 + dt.timedelta(minutes=130.5)
    assert roundstats.round_yield(repo, first)[0].events_added == 1
    assert roundstats.round_yield(repo, second)[0].queue_added == 1


def test_row_attributes_sessions_review_and_counters(repo, tmp_path):
    _round(repo, "I1", 0, 30, fast_forward=False)
    cfg = tmp_path / "cfg"
    worktree = transcripts.project_dir(cfg, repo / ".worktrees" / "dr-I1")
    write_session(worktree / "a.jsonl", user(1, "Use the deep-research skill for person I1."),
                  assistant(1, "l1", blocks=[bash("lineage round helper search b.md")]), assistant(4, "l2"))
    write_session(worktree / "b.jsonl", user(2, "Read the brief in x.brief.md and do it."),
                  assistant(2, "h1", "claude-sonnet-5-5"), assistant(3, "h2", "claude-sonnet-5-5"))
    write_session(worktree / "c.jsonl", user(200, "later round"), assistant(200, "late"))
    main = transcripts.project_dir(cfg, repo)
    write_session(main / "co.jsonl", assistant(20, "c0"), assistant(25, "c1", blocks=[bash("lineage review I1")]),
                  assistant(27, "c2"), assistant(29, "c3", blocks=[bash("lineage round merge I1", "t9")]))
    write_session(main / "co/subagents/agent-1.jsonl", assistant(26, "s1", "claude-sonnet-5-5"))
    out = repo / ".worktrees/dr-I1/output"
    out.mkdir(parents=True)
    (out / "scan.jpg").write_bytes(b"x" * 2_000_000)
    (out / "metrics.jsonl").write_text('{"kind": "openarchieven", "bytes": 1000000}\n{"kind": "rat"}\n', "utf-8")

    [round_] = roundstats.merged_rounds(repo)
    accounts = costs.account_dirs()
    row = roundstats.row(repo, round_, accounts, roundstats.Coordinator(repo, accounts, round_.start))
    assert (row["leader_sessions"], row["helper_sessions"], row["tool_calls"]) == ("1", "1", "1")
    assert row["leader_out"] == "200" and row["helpers_out"] == "200"
    assert row["review_out"] == "400"  # c1, c2, c3 and the review sub-agent; c0 is before the review
    assert row["active_min"] == "3"
    assert row["models"] == "claude-opus-5-5=6550;claude-sonnet-5-5=3930"
    assert (row["oa_requests"], row["rat_requests"], row["download_mb"]) == ("1", "1", "1.0")
    assert (row["scans"], row["scan_mb"]) == ("1", "2.0")
    assert (row["events_added"], row["queue_added"], row["century"]) == ("1", "1", "1700")
    assert float(row["api_eur"]) == pytest.approx(
        sum(float(row[f"api_eur_{r}"]) for r in roundstats.ROLES), abs=0.011
    )
    assert row["sub_eur"] == ""

    path = roundstats.stats_path(repo)
    roundstats.upsert(path, [row])
    roundstats.upsert(path, [row])
    assert len(roundstats.read_rows(path)) == 1
    assert "1 measured rounds" in roundstats.summary(roundstats.read_rows(path))


def test_metrics_only_inside_a_round_worktree(tmp_path, monkeypatch):
    worktree = tmp_path / ".worktrees" / "dr-I1"
    (worktree / "sub").mkdir(parents=True)
    project(worktree)
    monkeypatch.chdir(tmp_path)
    metrics.record("web", "example.org", 10)
    assert not (worktree / "output").exists()
    monkeypatch.chdir(worktree / "sub")
    metrics.record("web", "example.org", 10)
    assert metrics.read(worktree, Path("output")) == [
        {"t": metrics.read(worktree, Path("output"))[0]["t"], "kind": "web", "host": "example.org", "bytes": 10}
    ]

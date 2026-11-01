import datetime as dt
import json
import os
import subprocess
from pathlib import Path

import pytest

from lineage import guard, limits

from .conftest import project

ACC = ("work", "personal")
NOW = dt.datetime(2026, 10, 3, 11, 0)


@pytest.fixture(autouse=True)
def two_accounts(tmp_path):
    project(tmp_path, accounts={"work": {}, "personal": {}})


def ts(*args):
    return int(dt.datetime(*args).timestamp())


def test_weekly_limit_with_date():
    scherm = "  ⎿  You've hit your weekly limit · resets Oct 8, 2pm (Europe/Amsterdam)\n     /usage-credits"
    assert limits.limit_reset(scherm, NOW) == ts(2026, 10, 8, 14, 0)


def test_session_limit_later_today_and_after_midnight():
    assert limits.limit_reset("You've hit your session limit · resets 3:30pm", NOW) == ts(2026, 10, 3, 15, 30)
    assert limits.limit_reset("You've hit your session limit · resets 12:30am", NOW) == ts(2026, 10, 4, 0, 30)


def test_reset_is_counted_from_when_the_message_appeared():
    scherm = "  ⎿  You've hit your session limit · resets 12:30am\n✻ Baked for 1m 13s · done 9:43 PM\n❯ "
    assert limits.limit_reset(scherm, NOW) == ts(2026, 10, 3, 0, 30)


def test_other_wordings_of_the_limit():
    assert limits.limit_reset("5-hour limit reached ∙ resets 4pm", NOW) == ts(2026, 10, 3, 16, 0)
    assert limits.limit_reset(
        "Claude usage limit reached. Your limit will reset at 1pm (Europe/Amsterdam).", NOW
    ) == ts(2026, 10, 3, 13, 0)


def test_the_last_message_on_screen_counts():
    scherm = "session limit · resets 9am\n...\nYou've hit your weekly limit · resets Oct 8, 2pm"
    assert limits.limit_reset(scherm, NOW) == ts(2026, 10, 8, 14, 0)


def test_usage_warning_is_not_a_limit():
    scherm = ("✻ Churned for 2s · done 12:33 PM\n  You've used 76% of your weekly limit · resets Oct 8, 12am "
              "(Europe/Amsterdam) · Run /usage-credits to ask your admin for more\n❯ ")
    assert limits.limit_reset(scherm, NOW) is None


def test_no_limit_on_screen():
    assert limits.limit_reset("● Report committed.\n❯ ", NOW) is None


def test_account_choice_prefers_current_then_any_free():
    now = ts(2026, 10, 3, 11, 0)
    free, full = now - 60, now + 3600
    assert guard.choose_account("work", {"work": free, "personal": free}, now, ACC) == "work"
    assert guard.choose_account("work", {"work": full, "personal": free}, now, ACC) == "personal"
    assert guard.choose_account("work", {"work": full, "personal": full}, now, ACC) is None
    assert guard.choose_account("work", {}, now, ACC) == "work"


class World:
    """Runner and `lineage round start` stand-in: agents with status and screen, and a log of resumes."""

    def __init__(self, root):
        self.root = root
        self.agents = {}
        self.screens = {}
        self.resumed = []
        self.closed = []
        self.sessions = {"w1:p-other"}

    def research(self, id_, account="work", done=False):
        out = self.root / ".worktrees" / f"dr-{id_}" / "output"
        out.mkdir(parents=True)
        (out / "account").write_text(account + "\n")
        if done:
            (out / "DONE").write_text("")
        return out

    def agent_status(self):
        return dict(self.agents)

    def agent_panes(self):
        return {name: f"w1:p-{name}" for name in self.agents}

    def live_panes(self):
        return {*self.agent_panes().values(), *self.sessions}

    def screen(self, name):
        return self.screens.get(name, "")

    def close_round(self, id_, out):
        self.closed.append(id_)
        for name in [n for n in self.agents if n == f"dr-{id_.lower()}" or n.startswith(f"{id_.lower()}-")]:
            del self.agents[name]
        return True

    def resume_stub(self, id_, account, out):
        self.resumed.append((id_, account))
        (out / "account").write_text(account + "\n")
        self.agents[f"dr-{id_.lower()}"] = "working"
        self.screens.pop(f"dr-{id_.lower()}", None)
        return True


def run_round(world, tmp_path, now):
    b = guard.Guard(tmp_path, state=tmp_path / "state", runner=world, starter=world.resume_stub)
    return b, b.run_round(now)


def test_limit_on_work_resumes_on_personal(tmp_path):
    w = World(tmp_path)
    w.research("I1")
    w.agents["dr-i1"] = "idle"
    w.screens["dr-i1"] = "You've hit your session limit · resets 3pm"
    b, _ = run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    assert w.resumed == [("I1", "personal")]
    assert b.resets()["work"] == ts(2026, 10, 3, 15, 0)


def test_both_accounts_full_waits_then_resumes_after_reset(tmp_path):
    w = World(tmp_path)
    w.research("I1")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "dr-limit-personal").write_text(str(ts(2026, 10, 8, 14, 0)))
    w.agents["dr-i1"] = "idle"
    w.screens["dr-i1"] = "You've hit your session limit · resets 3pm"
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    assert w.resumed == []
    run_round(w, tmp_path, ts(2026, 10, 3, 14, 0))
    assert w.resumed == []
    run_round(w, tmp_path, ts(2026, 10, 3, 15, 1))
    assert w.resumed == [("I1", "work")]


def test_a_round_waiting_for_the_limit_is_closed_until_it_resumes(tmp_path):
    w = World(tmp_path)
    w.research("I1")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "dr-limit-personal").write_text(str(ts(2026, 10, 8, 14, 0)))
    w.agents.update({"dr-i1": "idle", "i1-search-01": "idle"})
    w.screens["dr-i1"] = "You've hit your session limit · resets 3pm"
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    assert w.closed == []
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 2))
    assert w.closed == ["I1"] and w.agents == {}
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 4))
    assert w.closed == ["I1"] and w.resumed == []
    run_round(w, tmp_path, ts(2026, 10, 3, 15, 1))
    assert w.resumed == [("I1", "work")]


def test_a_waiting_round_with_a_working_helper_stays_open(tmp_path):
    w = World(tmp_path)
    w.research("I1")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "dr-limit-personal").write_text(str(ts(2026, 10, 8, 14, 0)))
    w.agents.update({"dr-i1": "idle", "i1-search-01": "working"})
    w.screens["dr-i1"] = "You've hit your session limit · resets 3pm"
    for minute in (0, 2):
        run_round(w, tmp_path, ts(2026, 10, 3, 11, minute))
    assert w.closed == []


def test_a_waiting_round_resumed_by_someone_else_is_left_alone(tmp_path):
    w = World(tmp_path)
    w.research("I1")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "dr-limit-personal").write_text(str(ts(2026, 10, 8, 14, 0)))
    w.agents["dr-i1"] = "idle"
    w.screens["dr-i1"] = "You've hit your session limit · resets 3pm"
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    w.agents["dr-i1"] = "working"
    w.screens.pop("dr-i1")
    run_round(w, tmp_path, ts(2026, 10, 3, 15, 1))
    assert w.resumed == []


def test_limit_on_a_helper_moves_the_round(tmp_path):
    w = World(tmp_path)
    w.research("I1", account="personal")
    w.agents["dr-i1"] = "idle"
    w.agents["i1-zoek-3"] = "idle"
    w.screens["i1-zoek-3"] = "You've hit your weekly limit · resets Oct 8, 2pm"
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    assert w.resumed == [("I1", "work")]


def test_working_leader_and_finished_round_are_left_alone(tmp_path):
    w = World(tmp_path)
    w.research("I1")
    w.research("I2", done=True)
    w.agents["dr-i1"] = "working"
    w.screens["dr-i1"] = "You've hit your session limit · resets 3pm"
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    assert w.resumed == []


def test_missing_leader_is_resumed_after_two_checks(tmp_path):
    w = World(tmp_path)
    w.research("I1")
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    assert w.resumed == []
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 2))
    assert w.resumed == [("I1", "work")]


def test_stale_limit_from_last_night_resumes_on_the_same_account(tmp_path):
    w = World(tmp_path)
    w.research("I1")
    w.agents["dr-i1"] = "idle"
    w.screens["dr-i1"] = "You've hit your session limit · resets 12:30am\n✻ Baked for 1m · done 9:43 PM\n❯ "
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    assert w.resumed == [("I1", "work")]


def test_idle_leader_without_limit_is_not_touched(tmp_path):
    w = World(tmp_path)
    w.research("I1")
    w.agents["dr-i1"] = "idle"
    w.screens["dr-i1"] = "● Waiting for the scan reader.\n❯ "
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 2))
    assert w.resumed == []


def test_failed_resume_is_retried_next_round(tmp_path):
    w = World(tmp_path)
    w.research("I1")
    w.agents["dr-i1"] = "idle"
    w.screens["dr-i1"] = "You've hit your session limit · resets 3pm"
    attempts = []

    def fails_first(id_, account, out):
        attempts.append(account)
        return len(attempts) > 1 and w.resume_stub(id_, account, out)

    for minute in (0, 2):
        guard.Guard(tmp_path, state=tmp_path / "state", runner=w, starter=fails_first).run_round(
            ts(2026, 10, 3, 11, minute))
    assert attempts == ["personal", "personal"] and w.resumed == [("I1", "personal")]


class Coord:
    def __init__(self, wereld, clean=True):
        self.world = wereld
        self.started = []
        self.nudged = 0
        self.closed = 0
        self.clean = clean

    def close(self):
        if not self.clean:
            return False
        self.closed += 1
        self.world.agents.pop("coordinator", None)
        return True

    def start(self, account):
        self.started.append(account)
        self.world.agents["coordinator"] = "working"
        self.world.screens.pop("coordinator", None)
        return True

    def nudge(self):
        self.nudged += 1
        return True


def coord_round(w, c, tmp_path, now, beat=None, pane="w1:p-other"):
    state = tmp_path / "state"
    (state / "dr-coordinator.alive.d").mkdir(parents=True, exist_ok=True)
    if beat is not None:
        (state / "dr-coordinator.alive.d" / pane.replace(":", "_")).write_text(str(beat))
    lines = []
    guard.Guard(tmp_path, state=state, runner=w, starter=w.resume_stub, coordinator=c,
                    log=lines.append).run_round(now)
    return lines


def test_coordinator_started_when_no_session_coordinates(tmp_path):
    w = World(tmp_path)
    (tmp_path / ".worktrees").mkdir()
    c = Coord(w)
    now = ts(2026, 10, 3, 13, 0)
    coord_round(w, c, tmp_path, now, beat=now - 60)
    assert c.started == []
    coord_round(w, c, tmp_path, now, beat=now - 3600)
    assert c.started == ["work"]


def test_coordinator_on_a_limit_is_restarted_elsewhere(tmp_path):
    w = World(tmp_path)
    (tmp_path / ".worktrees").mkdir()
    c = Coord(w)
    w.agents["coordinator"] = "idle"
    w.screens["coordinator"] = "You've hit your session limit · resets 3pm"
    coord_round(w, c, tmp_path, ts(2026, 10, 3, 13, 0), beat=ts(2026, 10, 3, 12, 0))
    assert c.started == ["personal"]


def test_coordinator_on_a_limit_with_every_account_full_is_closed_and_started_after_reset(tmp_path):
    w = World(tmp_path)
    (tmp_path / ".worktrees").mkdir()
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "dr-limit-personal").write_text(str(ts(2026, 10, 8, 14, 0)))
    c = Coord(w)
    w.agents["coordinator"] = "idle"
    w.screens["coordinator"] = "You've hit your session limit · resets 3pm"
    old = ts(2026, 10, 3, 12, 0)
    coord_round(w, c, tmp_path, ts(2026, 10, 3, 13, 0), beat=old)
    assert c.closed == 1 and c.started == [] and "coordinator" not in w.agents
    coord_round(w, c, tmp_path, ts(2026, 10, 3, 14, 0), beat=old)
    assert c.started == []
    coord_round(w, c, tmp_path, ts(2026, 10, 3, 15, 1), beat=old)
    assert c.started == ["work"]


def test_idle_coordinator_without_heartbeat_is_nudged_once_per_half_hour(tmp_path):
    w = World(tmp_path)
    (tmp_path / ".worktrees").mkdir()
    c = Coord(w)
    w.agents["coordinator"] = "idle"
    old = ts(2026, 10, 3, 12, 0)
    for minute in (0, 2, 31):
        coord_round(w, c, tmp_path, ts(2026, 10, 3, 13, minute), beat=old)
    assert c.started == [] and c.nudged == 2


def test_round_logs_one_status_line(tmp_path):
    w = World(tmp_path)
    w.research("I1")
    w.agents["dr-i1"] = "working"
    w.agents["i1-zoek-2"] = "working"
    lines = coord_round(w, None, tmp_path, ts(2026, 10, 3, 13, 0))
    assert len(lines) == 1 and "I1 work working +1 helper" in lines[0] and "work free" in lines[0]


def test_auto_coordinator_closed_when_another_session_coordinates(tmp_path):
    w = World(tmp_path)
    (tmp_path / ".worktrees").mkdir()
    c = Coord(w)
    w.agents["coordinator"] = "working"
    now = ts(2026, 10, 3, 13, 0)
    coord_round(w, c, tmp_path, now, beat=now - 30, pane="w1:p-coordinator")
    coord_round(w, c, tmp_path, now, beat=now - 30)
    assert c.closed == 0
    w.agents["coordinator"] = "idle"
    coord_round(w, c, tmp_path, now + 120, beat=now + 100)
    assert c.closed == 1 and c.started == []


def test_heartbeat_of_a_closed_pane_is_not_another_session(tmp_path):
    w = World(tmp_path)
    (tmp_path / ".worktrees").mkdir()
    c = Coord(w)
    w.agents["coordinator"] = "idle"
    w.sessions = set()
    now = ts(2026, 10, 3, 13, 0)
    coord_round(w, c, tmp_path, now, beat=now - 60)
    assert c.closed == 0 and "coordinator" in w.agents


def test_auto_coordinator_kept_while_main_is_not_clean(tmp_path):
    w = World(tmp_path)
    (tmp_path / ".worktrees").mkdir()
    c = Coord(w, clean=False)
    w.agents["coordinator"] = "idle"
    now = ts(2026, 10, 3, 13, 0)
    coord_round(w, c, tmp_path, now, beat=now - 30)
    assert c.closed == 0 and "coordinator" in w.agents


def test_own_heartbeat_of_auto_coordinator_does_not_count_as_another_session(tmp_path):
    w = World(tmp_path)
    (tmp_path / ".worktrees").mkdir()
    c = Coord(w)
    w.agents["coordinator"] = "idle"
    now = ts(2026, 10, 3, 13, 0)
    coord_round(w, c, tmp_path, now, beat=now - 30, pane="w1:p-coordinator")
    assert c.closed == 0 and c.nudged == 0


def test_disabled_subscription_blocks_the_account_for_a_day():
    scherm = ("● Your organization has disabled Claude subscription access for Claude Code · Use an Anthropic "
              "API key instead,\n  or ask your admin to enable access\n✻ Worked for 0s · done 2:02 PM\n❯ ")
    assert limits.limit_reset(scherm, NOW) == ts(2026, 10, 4, 11, 0)


def test_disabled_account_moves_the_round_to_the_other(tmp_path):
    w = World(tmp_path)
    w.research("I1", account="personal")
    w.agents["dr-i1"] = "done"
    w.screens["dr-i1"] = "Your organization has disabled Claude subscription access for Claude Code"
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    assert w.resumed == [("I1", "work")]


def test_blocked_account_is_not_pushed_ahead_on_every_check(tmp_path):
    w = World(tmp_path)
    w.research("I1", account="personal")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "dr-limit-work").write_text(str(ts(2026, 10, 9, 0, 0)))
    w.agents["dr-i1"] = "done"
    w.screens["dr-i1"] = "Your organization has disabled Claude subscription access for Claude Code"
    b, _ = run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    eerste = b.resets()["personal"]
    b, _ = run_round(w, tmp_path, ts(2026, 10, 3, 11, 2))
    assert b.resets()["personal"] == eerste


def test_only_allowed_accounts_are_used(tmp_path):
    w = World(tmp_path)
    w.research("I1", account="personal")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "dr-accounts").write_text("personal\n")
    w.agents["dr-i1"] = "idle"
    w.screens["dr-i1"] = "You've hit your session limit · resets 3pm"
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    assert w.resumed == []
    run_round(w, tmp_path, ts(2026, 10, 3, 15, 1))
    assert w.resumed == [("I1", "personal")]


def test_resuming_waits_for_a_free_slot(tmp_path):
    w = World(tmp_path)
    w.research("I1")
    w.research("I2")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "dr-max-rounds").write_text("1\n")
    for _ in range(2):
        run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    assert w.resumed == [("I1", "work")]
    w.agents.pop("dr-i1")
    (tmp_path / ".worktrees" / "dr-I1" / "output" / "KLAAR").write_text("")
    for _ in range(2):
        run_round(w, tmp_path, ts(2026, 10, 3, 12, 0))
    assert w.resumed == [("I1", "work"), ("I2", "work")]


def test_a_worktree_with_the_old_dutch_names_is_still_understood(tmp_path):
    w = World(tmp_path)
    out = tmp_path / ".worktrees" / "dr-I1" / "uitvoer"
    out.mkdir(parents=True)
    (out / "account").write_text("work\n")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "dr-limiet-personal").write_text(str(ts(2026, 10, 3, 15, 0)))
    (tmp_path / "state" / "dr-max-rondes").write_text("1\n")
    b = guard.Guard(tmp_path, state=tmp_path / "state", runner=w, starter=w.resume_stub)
    assert b.resets() == {"personal": ts(2026, 10, 3, 15, 0)}
    assert b.max_rounds() == 1
    (out / "KLAAR").write_text("")
    b.run_round(ts(2026, 10, 3, 11, 0))
    b.run_round(ts(2026, 10, 3, 11, 2))
    assert w.resumed == []


def test_the_new_limit_file_wins_over_the_old_one(tmp_path):
    w = World(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "dr-limiet-work").write_text("100")
    (tmp_path / "state" / "dr-limit-work").write_text("200")
    b = guard.Guard(tmp_path, state=tmp_path / "state", runner=w, starter=w.resume_stub)
    assert b.resets()["work"] == 200


def test_accounts_come_from_the_project(tmp_path):
    project(tmp_path, accounts={"a": {}, "b": {"config_dir": "/x"}})
    w = World(tmp_path)
    w.research("I1", account="a")
    w.agents["dr-i1"] = "idle"
    w.screens["dr-i1"] = "You've hit your session limit · resets 3pm"
    run_round(w, tmp_path, ts(2026, 10, 3, 11, 0))
    assert w.resumed == [("I1", "b")]


def test_without_accounts_the_default_account_is_used(tmp_path):
    project(tmp_path)
    assert guard.project_accounts() == ("default",)


def test_new_heartbeat_folder_and_new_markers_are_read(tmp_path):
    w = World(tmp_path)
    out = w.research("I1")
    (out / "DONE").write_text("")
    (tmp_path / "state").mkdir()
    folder = tmp_path / "state" / "dr-watch.alive.d"
    folder.mkdir()
    (folder / "w1_p-x").write_text("42")
    b = guard.Guard(tmp_path, state=tmp_path / "state", runner=w, starter=w.resume_stub)
    assert b._heartbeats() == {"w1_p-x": 42}
    assert guard.marker(out, "DONE") == out / "DONE"
    (out / "KLAAR").write_text("")
    (out / "DONE").unlink()
    assert guard.marker(out, "DONE") == out / "KLAAR"


def test_output_folder_comes_from_the_settings(tmp_path):
    project(tmp_path, paths={"output": "uitvoer"})
    wt = tmp_path / "wt"
    (wt / "uitvoer").mkdir(parents=True)
    assert guard.output_dir(wt) == wt / "uitvoer"


def test_resume_runs_lineage_round_start(tmp_path):
    fake = tmp_path / "lineage"
    fake.write_text(f"#!/bin/sh\necho \"$@\" > {tmp_path}/args\n")
    fake.chmod(0o755)
    out = tmp_path / "out"
    out.mkdir()
    (out / "brief").write_text("research/brief.md\n")
    assert guard.research_starter(str(fake), tmp_path)("I9", "work", out)
    assert (tmp_path / "args").read_text().strip() == (
        "round start I9 --resume --account work --model opus --brief research/brief.md")


def test_lineage_command_can_be_overridden(monkeypatch):
    monkeypatch.setenv("LINEAGE_BIN", "/x/lineage")
    assert guard.lineage_command() == "/x/lineage"


FAKE_HC = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
here = Path(__file__).parent
with (here / "hc.calls").open("a") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
terminals = json.loads((here / "hc.json").read_text())
cmd, rest = sys.argv[1], sys.argv[2:]
if cmd == "ls":
    wanted = [rest[i + 1] for i, a in enumerate(rest) if a == "--label"]
    def match(t):
        return all(t.get("labels", {}).get(k) == v for k, _, v in (w.partition("=") for w in wanted))
    print(json.dumps({"terminals": [
        {k: v for k, v in t.items() if k != "labels"} for t in terminals if match(t)]}))
elif cmd == "read":
    print(next(t.get("screen", "") for t in terminals if t["address"] == rest[0]))
'''

PROJECT = "/p/.git"


def fake_hc(tmp_path, monkeypatch, terminals):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "hc").write_text(FAKE_HC)
    (bin_dir / "hc").chmod(0o755)
    (bin_dir / "hc.json").write_text(json.dumps(terminals))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir / "hc.calls"


def own(address, name, status=None, **labels):
    t = {"address": address, "name": name, "state": "live",
         "labels": {"lineage.project": PROJECT, **labels}}
    if status is not None:
        t["status"] = status
    return t


def test_hc_runner_sees_only_the_projects_named_terminals(tmp_path, monkeypatch):
    fake_hc(tmp_path, monkeypatch, [
        own("t3", "dr-i1", "working"),
        own("t4", "i1-search-01", "blocked"),
        own("t5", "coordinator", "error"),
        own("t6", "guard"),
        own("t7", None, "idle"),
        {"address": "t8", "name": "dr-i1", "status": "idle", "labels": {"lineage.project": "/other/.git"}},
        {"address": "t9", "status": "idle"},
    ])
    hc = guard.HcCli(Path(PROJECT))
    assert hc.agent_status() == {
        "dr-i1": "working", "i1-search-01": "blocked", "coordinator": "idle", "guard": "working"}
    assert hc.agent_panes()["dr-i1"] == "t3"
    assert hc.live_panes() == {f"t{n}" for n in range(3, 10)}


def test_hc_runner_reads_screen_and_prompts_by_address(tmp_path, monkeypatch):
    coordinator = own("t5", "coordinator", "idle")
    coordinator["screen"] = "You've hit your session limit · resets 3pm"
    calls = fake_hc(tmp_path, monkeypatch, [
        coordinator, {"address": "t1", "name": "coordinator", "status": "idle"}])
    hc = guard.HcCli(Path(PROJECT))
    assert "session limit" in hc.screen("coordinator")
    assert hc.screen("dr-gone") == ""
    assert hc.prompt("coordinator", "carry on")
    assert not hc.prompt("dr-gone", "carry on")
    assert hc.close_coordinator(tmp_path)
    lines = calls.read_text().splitlines()
    assert "read t5" in lines and "send t5 carry on" in lines
    assert lines[-2:] == ["kill t5", "rm t5"]


def test_hc_coordinator_close_without_one_does_nothing(tmp_path, monkeypatch):
    calls = fake_hc(tmp_path, monkeypatch, [])
    assert not guard.HcCli(Path(PROJECT)).close_coordinator(tmp_path)
    assert "kill" not in calls.read_text()


def test_hc_close_round_ends_the_rounds_terminals_only(tmp_path, monkeypatch):
    calls = fake_hc(tmp_path, monkeypatch, [
        own("t3", "dr-i1", "idle", **{"lineage.round": "I1"}),
        own("t4", "i1-search-01", "idle", **{"lineage.round": "I1"}),
        own("t5", "dr-i2", "idle", **{"lineage.round": "I2"}),
    ])
    assert guard.HcCli(Path(PROJECT)).close_round("I1", tmp_path)
    killed = [line for line in calls.read_text().splitlines() if line.startswith("kill")]
    assert killed == ["kill t3", "kill t4"]


def test_hc_status_mapping():
    assert guard.hc_status({}) == "working"
    assert guard.hc_status({"status": "error"}) == "idle"
    assert guard.hc_status({"status": {"app": "claude-code", "state": "blocked"}}) == "blocked"
    assert guard.hc_status({"status": "done"}) == "done"


def test_runner_choice(tmp_path):
    assert isinstance(guard.runner_for("hc", tmp_path), guard.HcCli)
    assert isinstance(guard.runner_for("herdr", tmp_path), guard.HerdrCli)
    with pytest.raises(ValueError):
        guard.runner_for("inline", tmp_path)


def test_hc_terminal_heartbeat_counts_as_a_live_session(tmp_path):
    """An hc address such as t7 or mac/t7 is the heartbeat's pane id."""
    w = World(tmp_path)
    (tmp_path / ".worktrees").mkdir()
    c = Coord(w)
    w.agents["coordinator"] = "idle"
    w.sessions = {"mac/t7"}
    now = ts(2026, 10, 3, 13, 0)
    coord_round(w, c, tmp_path, now, beat=now - 30, pane="mac_t7")
    assert c.closed == 1
    assert guard.heartbeat_key("mac/t7") == guard.heartbeat_key("mac_t7") == "mac_t7"
    assert guard.heartbeat_key("w1:p3") == "w1_p3"


class RecordingRunner:
    def __init__(self):
        self.prompts, self.closed = [], []

    def prompt(self, name, text):
        self.prompts.append(name)
        return True

    def close_coordinator(self, state):
        self.closed.append(state)
        return True


def test_coordinator_nudge_and_close_go_through_the_runner(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    runner = RecordingRunner()
    c = guard.CoordinatorCli("lineage", tmp_path, tmp_path / "state", runner)
    assert c.nudge() and runner.prompts == ["coordinator"]
    assert c.close() and runner.closed == [tmp_path / "state"]
    (tmp_path / "f").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "f"], check=True)
    assert not c.close() and len(runner.closed) == 1

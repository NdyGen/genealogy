"""Keeps the running deep-research rounds going across usage limits, independently of any Claude session.

A plain loop in its own terminal (`lineage guard`, a Herdr tab or an hc terminal), so it keeps working when the coordinator itself is
out of usage. Every round it looks at each research worktree that is not finished:

- a leader or helper that stopped on a usage-limit message: the reset is recorded for that leader's account
  (`dr-limit-<account>` in the git common dir, shared with `lineage round start`) and the round is resumed on
  an account with room; with every account at its limit, the round waits until the earliest reset;
- a leader that is gone while the round is not finished, two checks in a row: resumed.

It also keeps the disk from filling up (`lineage.disk`): with too little room it removes old register scans,
and while the disk stays full it resumes nothing.

It never merges, reviews or starts new rounds; that stays with the coordinator.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from lineage import disk, settings
from lineage.limits import LIMIT, limit_reset

QUIET = ("idle", "done", "blocked")
# Worktrees and state files written before the rename carry the Dutch names.
LEGACY_OUTPUT = "uitvoer"
LEGACY_MARKERS = {
    "DONE": ("DONE", "KLAAR"),
    "update": ("update", "stale", "bijwerk"),
    "brief": ("brief", "assignment", "opdracht"),
    "runner-tab": ("runner-tab", "herdr-tab"),
}
LEGACY_NAMES = {
    "dr-limit-": "dr-limiet-",
    "dr-max-rounds": "dr-max-rondes",
    "dr-guard.json": "dr-bewaker.json",
}
HEARTBEAT_FOLDERS = ("dr-coordinator.alive.d", "dr-watch.alive.d")


def project_accounts() -> tuple[str, ...]:
    return tuple(settings.current().accounts) or ("default",)


def choose_account(
    current: str, resets: dict[str, int], now: int, accounts: tuple[str, ...]
) -> str | None:
    free = [a for a in accounts if resets.get(a, 0) <= now]
    if current in free:
        return current
    return free[0] if free else None


class Runner(Protocol):
    """What the guard needs from the runner that hosts the rounds (herdr or hc)."""

    def agent_status(self) -> dict[str, str]: ...
    def agent_panes(self) -> dict[str, str]: ...
    def live_panes(self) -> set[str]: ...
    def screen(self, name: str) -> str: ...
    def prompt(self, name: str, text: str) -> bool: ...
    def close_coordinator(self, state: Path) -> bool: ...


def heartbeat_key(pane: str) -> str:
    """File name of a pane's heartbeat, as `lineage round watch` writes it."""
    return pane.replace(":", "_").replace("/", "_")


class HerdrCli:
    def _agents(self) -> list[dict]:
        out = subprocess.run(["herdr", "agent", "list"], capture_output=True, text=True, check=True).stdout
        return json.loads(out)["result"]["agents"]

    def agent_status(self) -> dict[str, str]:
        return {a["name"]: a["agent_status"] for a in self._agents() if a.get("name")}

    def agent_panes(self) -> dict[str, str]:
        return {a["name"]: a["pane_id"] for a in self._agents() if a.get("name")}

    def live_panes(self) -> set[str]:
        return {a["pane_id"] for a in self._agents()}

    def screen(self, name: str) -> str:
        return subprocess.run(
            ["herdr", "agent", "read", name, "--source", "visible"], capture_output=True, text=True
        ).stdout

    def prompt(self, name: str, text: str) -> bool:
        return subprocess.run(["herdr", "agent", "prompt", name, text],
                              capture_output=True, text=True).returncode == 0

    def close_coordinator(self, state: Path) -> bool:
        tab = state / "dr-coordinator.tab"
        if not tab.exists():
            return False
        subprocess.run(["herdr", "tab", "close", tab.read_text().strip()], capture_output=True)
        tab.unlink()
        return True


# hc reports no status for a program that has not reported yet (booting); an error ends a turn like idle,
# so the guard still reads the screen for a usage limit.
HC_STATUS = {None: "working", "error": "idle"}


def hc_status(terminal: dict) -> str:
    status = terminal.get("status")
    if isinstance(status, dict):
        status = status.get("state")
    return HC_STATUS.get(status, status)


class HcCli:
    """herdr-core: the project's terminals carry the label lineage.project=<git common dir>, because hc
    names are unique among all live terminals of the user, not per project."""

    def __init__(self, project: Path):
        self.project = str(project)

    def _hc(self, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(["hc", *args], capture_output=True, text=True, check=check)

    def _terminals(self, *labels: str) -> list[dict]:
        filters = [f for label in labels for f in ("--label", label)]
        out = self._hc("ls", "--json", *filters, check=True).stdout
        return json.loads(out)["terminals"]

    def _own(self) -> list[dict]:
        return [t for t in self._terminals(f"lineage.project={self.project}") if t.get("name")]

    def address(self, name: str) -> str | None:
        return next((t["address"] for t in self._own() if t["name"] == name), None)

    def agent_status(self) -> dict[str, str]:
        return {t["name"]: hc_status(t) for t in self._own()}

    def agent_panes(self) -> dict[str, str]:
        return {t["name"]: t["address"] for t in self._own()}

    def live_panes(self) -> set[str]:
        return {t["address"] for t in self._terminals()}

    def screen(self, name: str) -> str:
        address = self.address(name)
        return self._hc("read", address).stdout if address else ""

    def prompt(self, name: str, text: str) -> bool:
        address = self.address(name)
        return bool(address) and self._hc("send", address, text).returncode == 0

    def close_coordinator(self, state: Path) -> bool:
        address = self.address(COORDINATOR)
        if not address:
            return False
        self._hc("kill", address)
        self._hc("rm", address)
        return True


RUNNERS = ("herdr", "hc")


def runner_for(name: str, project: Path) -> Runner:
    if name == "hc":
        return HcCli(project)
    if name == "herdr":
        return HerdrCli()
    raise ValueError(f"the guard needs the herdr or hc runner, not {name!r}")


def marker(directory: Path, name: str) -> Path | None:
    return next((p for n in LEGACY_MARKERS[name] if (p := directory / n).exists()), None)


def output_dir(worktree: Path) -> Path:
    current = settings.current().rel("output")
    candidates = [worktree / current, worktree / "output", worktree / LEGACY_OUTPUT]
    return next((c for c in candidates if c.exists()), candidates[0])


def lineage_command() -> str:
    return os.environ.get("LINEAGE_BIN", "lineage")


def research_starter(lineage: str | None = None, cwd: Path | None = None) -> Callable[[str, str, Path], bool]:
    def resume(id_: str, account: str, out: Path) -> bool:
        cmd = [lineage or lineage_command(), "round", "start", id_, "--resume", "--account", account]
        model_file = out / "model"
        model = model_file.read_text().strip() if model_file.exists() else (
            "sonnet" if marker(out, "update") else "opus")
        cmd += ["--model", model]
        if brief := marker(out, "brief"):
            cmd += ["--brief", brief.read_text().strip()]
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).returncode == 0

    return resume


class Coordinator(Protocol):
    def start(self, account: str) -> bool: ...
    def nudge(self) -> bool: ...
    def close(self) -> bool: ...


class CoordinatorCli:
    def __init__(self, lineage: str | None, main: Path, state: Path, runner: Runner):
        self.lineage = lineage or lineage_command()
        self.main = main
        self.state = state
        self.runner = runner

    def close(self) -> bool:
        """Only with a clean main: a coordinator closed mid-merge would leave it half done."""
        if subprocess.run(["git", "-C", str(self.main), "status", "--porcelain", "--untracked-files=no"],
                          capture_output=True, text=True).stdout.strip():
            return False
        return self.runner.close_coordinator(self.state)

    def start(self, account: str) -> bool:
        return subprocess.run([self.lineage, "round", "start-coordinator", account], cwd=self.main,
                              capture_output=True, text=True).returncode == 0

    def nudge(self) -> bool:
        return self.runner.prompt(
            COORDINATOR,
            "The guard has seen no watcher for half an hour. Follow the coordinate skill: see what is "
            "open, restart `lineage round watch` in the background and carry on.")


COORDINATOR = "coordinator"
# Every wacht.sh beats per pane each loop; silent this long means that session no longer coordinates.
COORDINATOR_QUIET = 1800


class Guard:
    def __init__(self, root: Path, state: Path, runner: Runner, starter: Callable[[str, str, Path], bool],
                 log: Callable[[str], None] = lambda line: None, coordinator: Coordinator | None = None,
                 accounts: tuple[str, ...] | None = None, keeper: disk.Keeper | None = None):
        self.root = root
        self.state = state
        self.runner = runner
        self.starter = starter
        self.log = log
        self.coordinator = coordinator
        self.known = accounts or project_accounts()
        self.keeper = keeper
        self._active: set[str] = set()
        self._room = True
        state.mkdir(parents=True, exist_ok=True)

    def _state_file(self, name: str) -> Path:
        """The current file, or the pre-rename one while only that exists."""
        path = self.state / name
        for new, old in LEGACY_NAMES.items():
            if name.startswith(new):
                legacy = self.state / (old + name.removeprefix(new))
                return legacy if not path.exists() and legacy.exists() else path
        return path

    def accounts(self) -> tuple[str, ...]:
        """dr-accounts limits which accounts may be used (e.g. only personal); default all."""
        f = self.state / "dr-accounts"
        chosen = tuple(a for a in (f.read_text().split() if f.exists() else ()) if a in self.known)
        return chosen or self.known

    def max_rounds(self) -> int | None:
        """dr-max-rounds caps how many research leaders may run at once; resuming waits for a free slot."""
        f = self._state_file("dr-max-rounds")
        return int(f.read_text().strip()) if f.exists() and f.read_text().strip() else None

    def _choose(self, current: str, now: int) -> str | None:
        return choose_account(current, self.resets(), now, self.accounts())

    def _full(self) -> bool:
        maximum = self.max_rounds()
        return maximum is not None and len(self._active) >= maximum

    def resets(self) -> dict[str, int]:
        found = {}
        for acc in self.known:
            f = self._state_file(f"dr-limit-{acc}")
            if f.exists() and f.read_text().strip():
                found[acc] = int(f.read_text().strip())
        return found

    def _record_limit(self, account: str, reset: int) -> None:
        (self.state / f"dr-limit-{account}").write_text(f"{reset}\n")

    def _handled(self) -> dict:
        f = self._state_file("dr-guard.json")
        return json.loads(f.read_text()) if f.exists() else {}

    def _save(self, state: dict) -> None:
        (self.state / "dr-guard.json").write_text(json.dumps(state, indent=1, sort_keys=True))

    def _resume(self, id_: str, account: str, out: Path, reason: str) -> bool:
        succeeded = self.starter(id_, account, out)
        if succeeded:
            self._active.add(f"dr-{id_.lower()}")
        self.log(f"{id_} {reason}: {'resumed' if succeeded else 'resuming FAILED'} on {account}")
        return succeeded

    def _wait_until(self) -> int:
        resets = self.resets()
        return min(resets.get(a, 0) for a in self.accounts())

    def _limit_on(self, names: list[str], now_dt: dt.datetime, account: str) -> int | None:
        """A blocked-access message has no reset time and stays on screen: it must not push an
        already recorded block further ahead on every check."""
        now = int(now_dt.timestamp())
        for name in names:
            screen = self.runner.screen(name)
            reset = limit_reset(screen, now_dt)
            if reset is None:
                continue
            existing = self.resets().get(account, 0)
            if not LIMIT.search(screen) and existing > now:
                return existing
            return reset
        return None

    def _research(self, wt: Path, agents: dict[str, str], state: dict, now: int) -> str | None:
        """Handles one research worktree; returns its status for the log line, None when finished."""
        id_, out = wt.name[3:], output_dir(wt)
        idl = id_.lower()
        if marker(out, "DONE") or not (out / "account").exists():
            state.pop(id_, None)
            return None
        mine = state.setdefault(id_, {})
        account = (out / "account").read_text().strip() or self.known[0]
        leader = agents.get(f"dr-{idl}")
        helpers = [n for n in agents if n.startswith(f"{idl}-")]
        status = f"{id_} {account} {'working' if leader == 'working' else leader or 'gone'}"
        if helpers:
            status += f" +{len(helpers)} helper{'s' if len(helpers) > 1 else ''}"

        if not self._room and (leader is None or leader in QUIET):
            mine.pop("gone", None)
            return f"{status} waiting for disk space"
        if leader is None and self._full():
            mine.pop("gone", None)
            return f"{status} waiting for a free slot (max {self.max_rounds()})"

        if mine.get("wait_until") and leader == "working":
            # Resumed by someone else (the coordinator, by hand) while it waited for the limit.
            mine.pop("wait_until")
        if mine.get("wait_until"):
            choice = self._choose(account, now)
            if choice and self._resume(id_, choice, out, "limit over"):
                state[id_] = {}
                return f"{status} -> resumed on {choice}"
            return f"{status} waiting until {dt.datetime.fromtimestamp(mine['wait_until']):%d-%m %H:%M}"

        if leader is None:
            mine["gone"] = mine.get("gone", 0) + 1
            if mine["gone"] < 2:
                return f"{status} (first time)"
            choice = self._choose(account, now)
            if choice is None:
                mine["wait_until"] = self._wait_until()
                self.log(f"{id_} no leader and every account at its limit; waiting")
                return f"{status} waiting"
            if self._resume(id_, choice, out, "no leader"):
                state[id_] = {}
            return f"{status} -> resumed on {choice}"
        mine.pop("gone", None)
        if leader not in QUIET:
            return status

        reset = self._limit_on([f"dr-{idl}", *helpers], dt.datetime.fromtimestamp(now), account)
        if reset is None:
            return status
        self._record_limit(account, reset)
        choice = self._choose(account, now)
        if choice is None:
            mine["wait_until"] = self._wait_until()
            self.log(f"{id_} limit {account}; every account full, waiting until "
                     f"{dt.datetime.fromtimestamp(mine['wait_until']):%d-%m %H:%M}")
            return f"{status} limit, waiting"
        if self._resume(id_, choice, out, f"limit {account}"):
            state[id_] = {}
        return f"{status} limit -> {choice}"

    def _heartbeats(self) -> dict[str, int]:
        """Last `lineage round watch` beat per pane, keyed by heartbeat_key(pane)."""
        beats: dict[str, int] = {}
        for name in HEARTBEAT_FOLDERS:
            folder = self.state / name
            if folder.is_dir():
                for f in folder.iterdir():
                    beats[f.name] = max(beats.get(f.name, 0), int(f.read_text().strip() or 0))
        return beats

    def _coordinate(self, agents: dict[str, str], state: dict, now: int) -> str:
        mine = state.setdefault("_coordinator", {})
        account = mine.get("account", self.known[0])
        status = agents.get(COORDINATOR)
        own_pane = self.runner.agent_panes().get(COORDINATOR) if status else None
        own_pane = heartbeat_key(own_pane) if own_pane else None
        beats = self._heartbeats()
        # A closed pane leaves its last beat behind; only a pane that still runs an agent is another session.
        live = {heartbeat_key(p) for p in self.runner.live_panes()}
        others = [
            max(0, now - s) for p, s in beats.items()
            if p != own_pane and p in live and now - s < COORDINATOR_QUIET
        ]
        own = beats.get(own_pane, 0) if own_pane else 0
        watcher = (f"other watcher {min(others) // 60}m ago" if others else
                   f"own watcher {(now - own) // 60}m ago" if own else "no watcher")

        def start(reason: str) -> str:
            choice = self._choose(account, now)
            if choice is None:
                return f"coordinator {reason}, every account full"
            succeeded = self.coordinator.start(choice)
            self.log(f"coordinator {reason}: {'started' if succeeded else 'starting FAILED'} on {choice}")
            if succeeded:
                state["_coordinator"] = {"account": choice}
            return f"coordinator {reason} -> {choice}"

        if status is None:
            if others:
                return f"coordinator: other session ({watcher})"
            return start("missing")
        if others:
            if status not in QUIET:
                return f"coordinator {account} working, other session active: closing once quiet ({watcher})"
            succeeded = self.coordinator.close()
            self.log("coordinator: other session coordinates, " +
                     ("auto coordinator closed" if succeeded else "closing postponed (main not clean)"))
            if succeeded:
                state.pop("_coordinator", None)
            return f"coordinator {'closed' if succeeded else 'stays'}, other session ({watcher})"
        if status not in QUIET:
            return f"coordinator {account} working ({watcher})"
        reset = self._limit_on([COORDINATOR], dt.datetime.fromtimestamp(now), account)
        if reset is not None:
            self._record_limit(account, reset)
            return start(f"limit {account}")
        if now - own >= COORDINATOR_QUIET and now - mine.get("nudged", 0) >= COORDINATOR_QUIET:
            succeeded = self.coordinator.nudge()
            mine["nudged"] = now
            self.log(f"coordinator quiet without watcher: {'nudged' if succeeded else 'nudging FAILED'}")
            return f"coordinator {account} {status}, nudged ({watcher})"
        return f"coordinator {account} {status} ({watcher})"

    def run_round(self, now: int) -> None:
        agents = self.runner.agent_status()
        self._active = {n for n in agents if n.startswith("dr-")}
        state = self._handled()
        disk_status = ""
        if self.keeper is not None:
            disk_status, self._room = self.keeper.check(now, state.setdefault("_disk", {}))
        parts = [s for wt in sorted((self.root / ".worktrees").glob("dr-I*"))
                 if (s := self._research(wt, agents, state, now))]
        resets = self.resets()
        parts.append(", ".join(
            f"{a} {'free' if resets.get(a, 0) <= now else 'until ' + f'{dt.datetime.fromtimestamp(resets[a]):%d-%m %H:%M}'}"
            for a in self.accounts()))
        if self.coordinator is not None:
            parts.append(self._coordinate(agents, state, now))
        if disk_status:
            parts.append(disk_status)
        self._save(state)
        self.log(" | ".join(parts))


def _notify(subject: str, body: str) -> None:
    """Only to the user's own address, which needs no approval; nothing without mail in the project."""
    from lineage import mail

    project = settings.current()
    if project.mail_enabled and project.own_address:
        mail.notify(project.own_address, subject, body)


class _DryCoordinator:
    def start(self, account: str) -> bool:
        return True

    def close(self) -> bool:
        return True

    def nudge(self) -> bool:
        return True


def run(root: Path, state: Path, interval: int = 120, once: bool = False,
        dry_run: bool = False, with_coordinator: bool = False, lineage: str | None = None,
        runner: str = "herdr") -> None:
    """With dry_run the decisions are real but nothing starts and the shared state stays untouched."""
    project = state
    if dry_run:
        copy = Path(tempfile.mkdtemp(prefix="guard-dryrun-"))
        names = [*state.glob("dr-limit-*"), *state.glob("dr-limiet-*"), state / "dr-accounts",
                 state / "dr-max-rounds", state / "dr-max-rondes", state / "dr-guard.json",
                 state / "dr-bewaker.json"]
        for f in names:
            if f.exists():
                shutil.copy(f, copy)
        for folder in HEARTBEAT_FOLDERS:
            if (state / folder).is_dir():
                shutil.copytree(state / folder, copy / folder)
        state = copy
    log_file = state / "dr-guard.log"

    def log(line: str) -> None:
        line = f"{dt.datetime.now():%d-%m %H:%M} {'(dry run) ' if dry_run else ''}{line}"
        print(line, flush=True)
        # On a full disk the guard must keep running: it is what frees the space.
        try:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    backend = runner_for(runner, project)
    starter = (lambda id_, account, out: True) if dry_run else research_starter(lineage, root)
    coordinator = None
    if with_coordinator:
        coordinator = _DryCoordinator() if dry_run else CoordinatorCli(lineage, root, state, backend)
    keeper = disk.Keeper(root, log, _notify, dry_run)
    guard = Guard(root, state, backend, starter, log, coordinator, keeper=keeper)
    if not once:
        log(f"guard started ({runner} runner)")
    while True:
        now = int(time.time())
        try:
            (state / "dr-guard.alive").write_text(f"{now}\n")
            guard.run_round(now)
        except (subprocess.SubprocessError, OSError, ValueError, KeyError) as exc:
            log(f"error in round: {exc}")
        if once:
            return
        time.sleep(interval)

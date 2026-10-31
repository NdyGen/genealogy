"""scripts/round/runner-hc.sh against a real herdr-core, in a core of its own (own HC_SESSION and XDG
folders, so the user's terminals are never touched), with a stand-in for claude."""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

import pytest

ROUND = Path(__file__).parents[2] / "scripts" / "round"

pytestmark = pytest.mark.skipif(shutil.which("hc") is None, reason="hc (herdr-core) is not installed")

# Reports its status the way Claude Code does (OSC 7501), shows the trust dialog once per folder when asked
# to, records how it was started and writes the helper's result unless told not to.
FAKE_CLAUDE = r"""#!/bin/sh
here=$(dirname "$0")
for last; do :; done
printf '%s\t%s\t%s\n' "${CLAUDE_CONFIG_DIR-unset}" "${ANTHROPIC_MODEL-unset}" "$*" >> "$here/calls"
if [ -f "$here/trust" ] && [ ! -f "$PWD/.trusted" ]; then
  echo "Do you trust the files in this folder?  No, exit / Yes, I trust this folder"
  read -r answer
  touch "$PWD/.trusted"
fi
printf '\033]7501;app=claude-code:state=working\007'
if [ -f "$here/block" ]; then
  sleep 1
  printf '\033]7501;app=claude-code:state=blocked:kind=permission\007'
  stty raw -echo; dd bs=1 count=1 >/dev/null 2>&1; stty sane
  printf '\033]7501;app=claude-code:state=idle\007'
  read -r answer
  echo "$answer" > "$here/answer"
  printf '\033]7501;app=claude-code:state=working\007'
fi
case "$last" in
  *"Write your result to "*)
    result=${last#*Write your result to }; result=${result%%. *}
    [ -f "$here/noresult" ] || echo "found it" > "$result";;
esac
sleep 1
printf '\033]7501;app=claude-code:state=idle\007'
exec sleep 600
"""


def hc(env, *args, check=True):
    return subprocess.run(["hc", *args], env=env, capture_output=True, text=True, check=check)


@pytest.fixture
def core():
    base = Path(tempfile.mkdtemp(prefix="hc", dir="/tmp"))
    bin_dir = base / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(FAKE_CLAUDE)
    (bin_dir / "claude").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HC_", "HERDR_", "CLAUDE"))}
    env.update(HC_SESSION="lt", XDG_CONFIG_HOME=str(base / "c"), XDG_DATA_HOME=str(base / "d"),
               XDG_STATE_HOME=str(base / "s"), XDG_RUNTIME_DIR=str(base / "r"),
               PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    (base / "r").mkdir(mode=0o700)
    hc(env, "server", "start")
    yield env, base
    status = json.loads(hc(env, "server", "status", check=False).stdout or "{}")
    for pid in [status.get("pid"), *(h.get("pid") for h in status.get("holders", []))]:
        if pid:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
    shutil.rmtree(base, ignore_errors=True)


def runner(env, base, script, caller=None):
    """Runs bash with runner.sh and runner-hc.sh loaded and a minimal project around them."""
    wt = base / "wt"
    (wt / "output" / "helper").mkdir(parents=True, exist_ok=True)
    common = base / "repo.git"
    common.mkdir(exist_ok=True)
    prelude = f"""
set -euo pipefail
source '{ROUND}/runner.sh'
source '{ROUND}/runner-hc.sh'
COMMON='{common}'; ROOT='{base}'; OUT=output; WT='{wt}'
account_dir() {{ case "$1" in work) echo /cfg/work;; esac; }}
"""
    run_env = dict(env)
    if caller:
        run_env["HC_TERMINAL_ID"] = caller
    return subprocess.run(["bash", "-c", prelude + script], env=run_env, capture_output=True, text=True,
                          timeout=150)


def terminal(env, address):
    return json.loads(hc(env, "get", address).stdout)


def calls(base):
    return [line.split("\t") for line in (base / "bin" / "calls").read_text().splitlines()]


def test_leader_gets_its_own_tab_in_the_callers_space_with_its_account(core):
    env, base = core
    (base / "bin" / "trust").write_text("")
    caller = json.loads(hc(env, "run", "--bg", "--name", "me", "--no-parent", "--label", "herdr.space=S1",
                           "--label", "herdr.tab=T1", "--label", "where=Family / main", "sleep", "300").stdout)["address"]
    r = runner(env, base, """
runner_start_leader "$WT" dr-i7 "Jan Jansen" opus work "Use the deep-research skill for person I7."
echo "$RUNNER_WHERE"
runner_list
""", caller)
    assert r.returncode == 0, r.stderr
    where, listing = r.stdout.splitlines()[0], r.stdout.splitlines()[1:]
    assert "WARNING" not in r.stderr
    address = where.removeprefix("terminal ")
    t = terminal(env, address)
    assert t["name"] == "dr-i7" and t["parent"] is None and t["cwd"] == str(base / "wt")
    assert t["labels"] == {
        "herdr.space": "S1", "where": "Family / I7 Jan Jansen", "lineage.project": str(base / "repo.git"),
        "lineage.role": "leader", "lineage.round": "I7", "lineage.person": "Jan Jansen"}
    cfg, model, args = calls(base)[0]
    assert cfg == "/cfg/work" and model == "unset"
    assert args == "--model opus --permission-mode auto Use the deep-research skill for person I7."
    assert (base / "wt" / ".trusted").exists()
    assert listing[0].split("\t")[0] == "dr-i7"


def test_helper_is_a_child_of_its_leader_and_is_cleared_when_done(core):
    env, base = core
    r = runner(env, base, 'runner_start_leader "$WT" dr-i7 I7 opus default "go"; echo "$RUNNER_WHERE"')
    assert r.returncode == 0, r.stderr
    leader = r.stdout.split()[-1]
    result = base / "wt" / "output" / "helper" / "01-search.md"
    r = runner(env, base, f"""
export CLAUDE_CONFIG_DIR=/cfg/work
runner_start_helper "$WT" i7-search-01 genealogy-research:dr-archive-searcher \\
  "Read the brief in x and carry it out according to your role. Write your result to {result}. Commit nothing." \\
  '{result}'
""", leader)
    assert r.returncode == 0, r.stderr
    assert result.read_text() == "found it\n"
    cfg, _, args = calls(base)[-1]
    assert cfg == "/cfg/work" and args.startswith("--agent genealogy-research:dr-archive-searcher")
    finished = json.loads(hc(env, "ls", "--all").stdout)["terminals"]
    assert not [t for t in finished if t.get("name") == "i7-search-01"]


def test_helper_without_result_fails_with_its_screen(core):
    env, base = core
    (base / "bin" / "noresult").write_text("")
    result = base / "wt" / "output" / "helper" / "02-scan.md"
    r = runner(env, base, f"""
runner_start_helper "$WT" i7-scan-02 dr-scan-reader "Write your result to {result}. Go." '{result}'
""")
    assert r.returncode == 1
    error = result.with_name("02-scan.error.txt").read_text()
    assert error.startswith("stopped without a result")
    assert not [t for t in json.loads(hc(env, "ls").stdout)["terminals"] if t.get("name") == "i7-scan-02"]


def test_stop_ends_the_round_and_frees_its_names(core):
    env, base = core
    r = runner(env, base, """
runner_start_leader "$WT" dr-i7 I7 opus default "go"
runner_start_leader "$WT" dr-i8 I8 opus default "go"
runner_stop "$WT" dr-i7
runner_list
""")
    assert r.returncode == 0, r.stderr
    assert [line.split("\t")[0] for line in r.stdout.splitlines()] == ["dr-i8"]
    names = [t.get("name") for t in json.loads(hc(env, "ls", "--all").stdout)["terminals"]]
    assert "dr-i7" not in names


def test_screen_and_prompt_reach_only_this_projects_terminal(core):
    env, base = core
    hc(env, "run", "--bg", "--name", "coordinator", "--no-parent", "sleep", "300")
    r = runner(env, base, """
runner_screen coordinator && echo "screen:$(runner_screen coordinator)"
runner_prompt coordinator hello || echo "no prompt"
runner_start_coordinator "$ROOT" default "/genealogy-research:coordinate go" 2>&1 || echo "failed $?"
""")
    assert "no prompt" in r.stdout
    assert "failed" in r.stdout


def test_blocked_helper_is_refused_once_and_carries_on(core):
    env, base = core
    (base / "bin" / "block").write_text("")
    result = base / "wt" / "output" / "helper" / "03-back.md"
    r = runner(env, base, f"""
runner_start_helper "$WT" i7-back-03 dr-background "Write your result to {result}. Go." '{result}'
""")
    assert r.returncode == 0, r.stderr
    assert "That action was refused" in (base / "bin" / "answer").read_text()
    assert result.read_text() == "found it\n"


def test_guard_alive_follows_its_terminal(core):
    env, base = core
    r = runner(env, base, """
runner_guard_alive && echo before || echo none
runner_start_guard "$ROOT" sleep 300
runner_guard_alive && echo running
hc_close "$(_hc_addr guard)"
runner_guard_alive && echo still || echo gone
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["none", "running", "gone"]

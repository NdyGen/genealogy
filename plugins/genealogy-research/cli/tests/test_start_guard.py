"""scripts/round/start-guard.sh --cron in a throwaway git project, with a stand-in crontab and an hc core
that is never started (own HC_SESSION and XDG folders, so the user's terminals are never touched)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

START_GUARD = Path(__file__).parents[2] / "scripts" / "round" / "start-guard.sh"

pytestmark = pytest.mark.skipif(shutil.which("hc") is None, reason="hc (herdr-core) is not installed")

FAKE_CRONTAB = """#!/bin/sh
tab="$(dirname "$0")/tab"
case "$1" in
  -l) [ -f "$tab" ] && cat "$tab" || exit 1;;
  -) cat > "$tab";;
esac
"""


def test_cron_passes_the_callers_full_path_on_to_the_guard(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "lineage.toml").write_text('runner = "hc"\n')
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "start"], check=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "crontab").write_text(FAKE_CRONTAB)
    (bin_dir / "crontab").chmod(0o755)
    # A program only the user's shell finds, such as node for another plugin's hook.
    only_in_shell = tmp_path / "shell-only"
    only_in_shell.mkdir()
    (tmp_path / "r").mkdir(mode=0o700)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HC_", "HERDR_", "DR_", "LINEAGE_"))}
    env.update(HC_SESSION="lt-guard", XDG_RUNTIME_DIR=str(tmp_path / "r"), XDG_STATE_HOME=str(tmp_path / "s"),
               XDG_CONFIG_HOME=str(tmp_path / "c"), XDG_DATA_HOME=str(tmp_path / "d"),
               PATH=os.pathsep.join([str(bin_dir), str(Path(sys.executable).parent), env["PATH"],
                                     str(only_in_shell)]))

    r = subprocess.run(["bash", str(START_GUARD), "--cron"], cwd=root, env=env, capture_output=True, text=True,
                       timeout=30)

    assert r.returncode == 0, r.stderr
    path_file = root / ".git" / "dr-guard.path"
    assert str(only_in_shell) in path_file.read_text().strip().split(os.pathsep)
    line = (bin_dir / "tab").read_text()
    assert f"PATH=\"$(cat '{path_file}')\"" in line
    run = subprocess.run(["sh", "-c", line.split(" && ", 1)[1].split(" flock ", 1)[0] + ' sh -c \'echo "$PATH"\''],
                         env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, check=True)
    assert str(only_in_shell) in run.stdout.strip().split(os.pathsep)

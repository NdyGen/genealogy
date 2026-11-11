"""scripts/round/watch.sh in a throwaway git project with the inline runner (no leaders, no mail)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

WATCH = Path(__file__).parents[2] / "scripts" / "round" / "watch.sh"


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "lineage.toml").write_text('runner = "inline"\n')
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "start"], check=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HC_", "HERDR_", "DR_", "LINEAGE_"))}
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env['PATH']}"
    return root, env


def finish(root, id_, stamp):
    out = root / ".worktrees" / f"dr-{id_}" / "output"
    out.mkdir(parents=True, exist_ok=True)
    (out / "DONE").write_text(f"{stamp}\n")


def watch(root, env):
    """One watcher run; None when it found nothing new and kept waiting."""
    try:
        r = subprocess.run(["bash", str(WATCH), "1"], cwd=root, env=env, capture_output=True, text=True,
                           timeout=4)
    except subprocess.TimeoutExpired:
        return None
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_a_finished_round_is_reported_once(project):
    root, env = project
    finish(root, "I7", "2026-11-11T09:59+01:00")
    assert watch(root, env).startswith("I7 done")
    assert watch(root, env) is None


def test_a_new_finish_after_a_tell_is_reported_even_if_the_watcher_missed_the_repair(project):
    """`round tell` removes DONE; when the lead finishes again before the coordinator restarts the
    watcher, the watcher never saw the round without DONE."""
    root, env = project
    finish(root, "I7", "2026-11-11T09:40+01:00")
    assert watch(root, env).startswith("I7 done")
    finish(root, "I7", "2026-11-11T09:59+01:00")
    assert watch(root, env).startswith("I7 done")

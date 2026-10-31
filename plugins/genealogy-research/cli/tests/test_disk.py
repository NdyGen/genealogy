import os
import subprocess

import pytest

from lineage import disk, guard, settings
from tests.conftest import project
from tests.test_guard import World, ts

DAY = 86400
NOW = ts(2026, 10, 30, 12, 0)


def page(root, rel, age_days, size=1000):
    path = root / "sources" / "scans" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (NOW - age_days * DAY, NOW - age_days * DAY))
    return path


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    project(tmp_path, disk={"low_gb": 0.000002, "target_gb": 0.000003, "critical_gb": 0.000001})
    return tmp_path


def track(root, name, text):
    (root / name).write_text(text)
    subprocess.run(["git", "-C", str(root), "add", name], check=True)


def test_only_old_unreferenced_register_pages_of_merged_rounds_go(repo):
    old = page(repo, "dr-I1/scans/929-114/0086.jpg", 40)
    cited = page(repo, "dr-I1/scans/929-114/0087.jpg", 40)
    cited_folder = page(repo, "dr-I1/scans/929-116/0001.jpg", 40)
    recent = page(repo, "dr-I1/scans/929-114/0088.jpg", 10)
    crop = page(repo, "dr-I1/scans/929-114/0086_akte.jpg", 40)
    other_archive = page(repo, "dr-I1/scans/gar-1001/0001.jpg", 40)
    running = page(repo, "dr-I2/scans/929-1/0001.jpg", 40)
    (repo / ".worktrees" / "dr-I2").mkdir(parents=True)
    track(repo, "log.md", "see bronnen/scans/dr-I1/scans/929-114/0087.jpg, and the register "
                          "bronnen/scans/dr-I1/scans/929-116/. All in bronnen/scans/dr-I1/scans.")
    found = disk.candidates(repo, NOW, cache=repo / "cache")
    assert [c.path for c in found] == [old]
    assert all(p.exists() for p in (cited, cited_folder, recent, crop, other_archive, running))


def test_prune_takes_the_cache_first_and_stops_at_the_target(repo, monkeypatch):
    cache = repo / "cache"
    cache.mkdir()
    (cache / "a.jpg").write_bytes(b"x" * 1000)
    linked = cache / "b.jpg"
    linked.write_bytes(b"x" * 1000)
    os.link(linked, repo / "in-a-round.jpg")
    first = page(repo, "dr-I1/scans/929-114/0001.jpg", 50)
    second = page(repo, "dr-I1/scans/929-114/0002.jpg", 40)
    space = {"free": 1000}

    def free(_):
        return space["free"]

    def unlink_and_count(self, missing_ok=False):
        space["free"] += self.stat().st_size
        real_unlink(self, missing_ok=missing_ok)

    real_unlink = type(first).unlink
    monkeypatch.setattr(type(first), "unlink", unlink_and_count)
    done = disk.prune(repo, NOW, cache=cache, free=free)
    assert done.removed == {"cache": 1, "register": 1}
    assert not (cache / "a.jpg").exists() and linked.exists()
    assert not first.exists() and second.exists()


def test_dry_run_removes_nothing(repo):
    p = page(repo, "dr-I1/scans/929-114/0001.jpg", 40)
    done = disk.prune(repo, NOW, dry_run=True, cache=repo / "cache", free=lambda _: 0)
    assert done.removed == {"register": 1} and p.exists()


def test_settings_read_and_write_the_disk_table(tmp_path):
    config = settings.parse("[disk]\nlow_gb = 30\nkeep_days = 60\n", tmp_path / "lineage.toml")
    assert disk.limits(config).low == 30 * disk.GB and disk.limits(config).keep_days == 60
    assert disk.limits(config).critical == 5 * disk.GB
    assert "[disk]\nlow_gb = 30\nkeep_days = 60" in settings.dump(config)
    with pytest.raises(settings.ConfigError, match="unknown \\[disk\\] size"):
        settings.parse("[disk]\nsize = 3\n", tmp_path / "lineage.toml")


def test_a_full_disk_pauses_resuming_and_tells_the_user_once(repo):
    w = World(repo)
    w.research("I1")
    sent, lines = [], []
    keeper = disk.Keeper(repo, lines.append, notify=lambda s, b: sent.append(s), free=lambda _: 0,
                         cache=repo / "cache")
    b = guard.Guard(repo, state=repo / "state", runner=w, starter=w.resume_stub, log=lines.append,
                    accounts=("work", "personal"), keeper=keeper)
    for minute in (0, 2, 4):
        b.run_round(NOW + minute * 60)
    assert w.resumed == []
    assert len(sent) == 1
    assert "waiting for disk space" in lines[-1] and "disk FULL" in lines[-1]
    keeper.free = lambda _: 10**12
    b.run_round(NOW + 360)
    b.run_round(NOW + 480)
    assert w.resumed == [("I1", "work")]

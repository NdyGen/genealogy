"""Regionaal Archief Tilburg (RAT): inventory items, scans and crops via the Memorix API behind the RAT viewer.

The search covers only the titles of inventory items, not the deeds inside them.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from lineage.i18n import t

API = "https://webservices8.memorix.nl/archives"
DOWNLOAD = "https://download-images.memorix.nl/tlb/download/fullsize/{id}.jpg"
# Public key of the RAT web viewer, not a secret.
API_KEY = "7d527d90-52c6-11e4-bed0-5b4fee920d4f"
USER_AGENT = "lineage/0.1 (genealogy research)"
FONDS = {"929": "Schepenbank Dongen", "962": "Schepenbank 's-Gravenmoer"}


class RatError(RuntimeError):
    pass


# Every session, worktree and helper agent on this machine shares one throttle: on 2 October 2026
# parallel downloads that kept retrying after HTTP 429 got this IP address blocked by Memorix.
INTERVAL = float(os.environ.get("LINEAGE_RAT_INTERVAL", "3"))
API_TTL = 30 * 24 * 3600
PAUSE_429 = 30 * 60
PAUSE_403 = 6 * 3600


def _throttle_dir() -> Path:
    base = os.environ.get("LINEAGE_RAT_CACHE") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "lineage", "rat"
    )
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def _state():
    """Exclusive, cross-process access to the shared throttle state."""
    directory = _throttle_dir()
    with open(directory / "throttle.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / "throttle.json"
        try:
            state = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            state = {}
        yield state
        path.write_text(json.dumps(state))


def throttle_state() -> dict:
    with _state() as state:
        return dict(state)


def _clock(ts: float) -> str:
    return time.strftime("%d-%m %H:%M", time.localtime(ts))


def _locked_out(state: dict) -> str | None:
    until = state.get("locked_until", 0)
    if until > time.time():
        return t(
            "RAT traffic locked out until {until} ({reason}); nothing sent. "
            "Do not retry or work around it; `lineage rat throttle` shows the state, "
            "`lineage rat throttle --test` makes one probe request.",
            until=_clock(until),
            reason=state.get("reason", "?"),
        )
    return None


def _wait_turn() -> None:
    """Holds the lock while waiting, so concurrent processes queue up instead of bursting."""
    with _state() as state:
        message = _locked_out(state)
        if message:
            raise RatError(message)
        wait = state.get("last", 0) + INTERVAL - time.time()
        if wait > 0:
            time.sleep(wait)
        state["last"] = time.time()


def _lock_out(seconds: float, reason: str) -> None:
    with _state() as state:
        state["locked_until"] = max(state.get("locked_until", 0), time.time() + seconds)
        state["reason"] = reason


def release() -> None:
    with _state() as state:
        state.pop("locked_until", None)
        state.pop("reason", None)


def probe() -> str:
    """One deliberate request despite a lockout; lifts it on success, renews it on 429/403."""
    was_locked_out = throttle_state().get("locked_until", 0) > time.time()
    saved: dict = {}
    if was_locked_out:
        with _state() as state:
            saved = {k: state.pop(k) for k in ("locked_until", "reason") if k in state}
    try:
        _fetch(
            f"{API}/findingaiditems?"
            + urllib.parse.urlencode(
                {
                    "apiKey": API_KEY,
                    "lang": "nl_NL",
                    "filters[ead.eadheader.eadid]": _eadid("929"),
                    "filters[unitid]": "96",
                    "view": "list",
                    "limit": 1,
                }
            ),
            30,
        )
    except RatError as exc:
        if was_locked_out and not throttle_state().get("locked_until"):
            with _state() as state:
                state.update(saved)
        raise RatError(t("probe request failed: {error}", error=exc)) from exc
    return t("RAT reachable; lockout lifted") if was_locked_out else t("RAT reachable")


def _fetch(url: str, timeout: int) -> bytes:
    """One request through the throttle. 429/403 stop all RAT traffic; only network errors are retried."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        _wait_turn()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                _lock_out(
                    PAUSE_429, t("HTTP 429 too many requests, {time}", time=_clock(time.time()))
                )
            elif exc.code == 403:
                _lock_out(PAUSE_403, t("HTTP 403 blocked, {time}", time=_clock(time.time())))
            raise RatError(
                t(
                    "RAT server refuses: HTTP {code}. {lockout}",
                    code=exc.code,
                    lockout=_locked_out(throttle_state()) or "",
                )
            ) from exc
        except OSError as exc:
            if attempt == 2:
                raise RatError(t("RAT server unreachable: {error}", error=exc)) from exc
            time.sleep(10 * (attempt + 1))
    raise AssertionError("unreachable")


@dataclass
class Scan:
    number: int
    id: str
    name: str

    @property
    def url(self) -> str:
        return DOWNLOAD.format(id=self.id)


@dataclass
class Item:
    fonds: str
    inventory: str
    cpath: str
    title: str
    dating: str
    scan_count: int
    scans: list[Scan] = field(default_factory=list)

    def citation(self, scan: Scan | None = None) -> str:
        scan_part = (
            t(", scan {number} ({name})", number=scan.number, name=scan.name) if scan else ""
        )
        return t(
            "RAT {fonds} inv. {inventory}{scan}: {title}",
            fonds=self.fonds,
            inventory=self.inventory,
            scan=scan_part,
            title=self.title,
        )


def _get(path: str, params: dict[str, str | int]) -> dict:
    query = urllib.parse.urlencode({"apiKey": API_KEY, "lang": "nl_NL", **params})
    url = f"{API}/{path}?{query}"
    cache = _throttle_dir() / "api" / f"{hashlib.sha1(url.encode()).hexdigest()}.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < API_TTL:
        return json.loads(cache.read_text())
    try:
        data = json.loads(_fetch(url, 30).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RatError(t("unexpected answer from the RAT API: {error}", error=exc)) from exc
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data))
    return data


def _eadid(fonds: str) -> str:
    return f"NL-TbRAT-{fonds}"


def _item(fonds: str, raw: dict) -> Item:
    return Item(
        fonds=fonds,
        inventory=(raw.get("unitid") or ["?"])[0],
        cpath=raw.get("cpath") or "",
        title=raw.get("title") or "",
        dating=", ".join(raw.get("unitdate") or []),
        scan_count=int(raw.get("scancount") or 0),
    )


def search(terms: str, fonds: str = "929", limit: int = 25) -> tuple[int, list[Item]]:
    data = _get(
        "findingaiditems",
        {
            "filters[ead.eadheader.eadid]": _eadid(fonds),
            "keywords": terms,
            "view": "list",
            "limit": limit,
        },
    )
    items = [i for i in data.get("findingAidItems", []) if i.get("unitid")]
    return int(data.get("meta", {}).get("numFound") or 0), [_item(fonds, i) for i in items]


def item(inventory: str, fonds: str = "929") -> Item:
    data = _get(
        "findingaiditems",
        {
            "filters[ead.eadheader.eadid]": _eadid(fonds),
            "filters[unitid]": inventory,
            "view": "list",
            "limit": 5,
        },
    )
    items = [
        i for i in data.get("findingAidItems", []) if (i.get("unitid") or [None])[0] == inventory
    ]
    if not items:
        raise RatError(
            t(
                "inventory {inventory} not found in RAT fonds {fonds}",
                inventory=inventory,
                fonds=fonds,
            )
        )
    # A series and its single register can share one unitid (929 inv. 89); the register holds the scans.
    found = _item(fonds, max(items, key=lambda i: int(i.get("scancount") or 0)))
    raw: list[dict] = []
    # The scans endpoint returns ten at a time and ignores any page-size parameter.
    while found.cpath:
        page = _get(f"scans/{_eadid(fonds)}/{found.cpath}", {"start": len(raw)}).get("scans", {})
        batch = page.get("scans") or []
        raw.extend(batch)
        if not batch or len(raw) >= int(page.get("scancount") or 0):
            break
    found.scans = [
        Scan(number=n, id=s["id"], name=s.get("name") or "") for n, s in enumerate(raw, start=1)
    ]
    return found


def download(found: Item, numbers: list[int], directory: Path) -> list[Path]:
    """Scans already on disk are not fetched again."""
    by_number = {s.number: s for s in found.scans}
    missing = [n for n in numbers if n not in by_number]
    if missing:
        raise RatError(
            t(
                "inv. {inventory} has {count} scans; missing: {missing}",
                inventory=found.inventory,
                count=len(found.scans),
                missing=missing,
            )
        )
    target = directory / f"{found.fonds}-{found.inventory}"
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for n in numbers:
        path = target / f"{n:04d}.jpg"
        if not path.exists():
            _place_file(_cached_scan(by_number[n]), path)
        paths.append(path)
    return paths


def _cached_scan(scan: Scan) -> Path:
    """Each scan is fetched from Memorix at most once per machine."""
    cached = _throttle_dir() / "scans" / f"{scan.id}.jpg"
    if not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        data = _fetch(scan.url, 120)
        if not data.startswith(b"\xff\xd8"):
            # Memorix answers an outage with an HTML page and status 200; cached, it would poison every later download.
            raise RatError(
                t(
                    "scan {number} is not a JPEG (image server offline?): {start!r}",
                    number=scan.number,
                    start=data[:80],
                )
            )
        tmp = cached.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(cached)
    return cached


def _place_file(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def crop(
    source: Path, frame: tuple[float, float, float, float], out: Path, scale: float = 1.0
) -> Path:
    """Crop by fractions of the page (x0, y0, x1, y1), greyscale with stretched contrast: old ink reads better."""
    from PIL import Image, ImageOps

    x0, y0, x1, y1 = frame
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise RatError(t("frame must be fractions with 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1"))
    with Image.open(source) as image:
        w, h = image.size
        cropped = image.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))).convert("L")
    cropped = ImageOps.autocontrast(cropped, cutoff=1)
    if scale != 1.0:
        cropped = cropped.resize(
            (int(cropped.width * scale), int(cropped.height * scale)), Image.LANCZOS
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(out)
    return out


def parse_numbers(spec: str) -> list[int]:
    """'3,5,10-12' -> [3, 5, 10, 11, 12]"""
    numbers: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            numbers.extend(range(int(a), int(b) + 1))
        elif part.strip():
            numbers.append(int(part))
    return numbers

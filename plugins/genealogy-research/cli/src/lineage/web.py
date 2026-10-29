"""Plain HTTP for archive websites: a browser user agent (several archives answer 403 to anything
else), a pause per host so one run does not hammer a server, and patience on 429/503.
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from lineage.i18n import t

BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
PAUSE_PER_HOST = 1.0
ATTEMPTS = 4
MAX_WAIT = 120

_last: dict[str, float] = {}
_slot = threading.Lock()


class WebError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _take_turn(host: str, pause: float) -> None:
    with _slot:
        turn = max(time.monotonic(), _last.get(host, 0) + pause)
        _last[host] = turn
    time.sleep(max(0.0, turn - time.monotonic()))


def _wait_time(exc: urllib.error.HTTPError, attempt: int) -> float:
    retry = exc.headers.get("Retry-After", "") if exc.headers else ""
    seconds = float(retry) if retry.isdigit() else 10 * 2**attempt
    return min(seconds, MAX_WAIT)


def fetch(
    url: str,
    timeout: int = 60,
    extra_headers: dict[str, str] | None = None,
    pause: float = PAUSE_PER_HOST,
) -> bytes:
    host = urllib.parse.urlsplit(url).netloc
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.5",
        **(extra_headers or {}),
    }
    request = urllib.request.Request(url, headers=headers)
    for attempt in range(ATTEMPTS):
        _take_turn(host, pause)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 502, 503, 504) and attempt < ATTEMPTS - 1:
                time.sleep(_wait_time(exc, attempt))
                continue
            raise WebError(t("{url}: HTTP {code}", url=url, code=exc.code), exc.code) from exc
        except OSError as exc:
            if attempt == ATTEMPTS - 1:
                raise WebError(t("{url}: {error}", url=url, error=exc)) from exc
            time.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")

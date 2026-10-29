"""A headless Chromium via Playwright, for archive viewers that only work with JavaScript.

The Chromium build is taken from what is already installed under ~/.cache/ms-playwright (or
LINEAGE_CHROMIUM), so a Playwright upgrade does not force a new browser download.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from lineage.i18n import t
from lineage.web import BROWSER_UA

CACHE = Path.home() / ".cache" / "ms-playwright"


class BrowserError(RuntimeError):
    pass


def chromium() -> str | None:
    """Path of the newest installed Chromium, or None to let Playwright use its own."""
    if configured := os.environ.get("LINEAGE_CHROMIUM") or os.environ.get("NDYGEN_CHROMIUM"):
        return configured
    candidates = []
    for directory in CACHE.glob("chromium-*"):
        m = re.fullmatch(r"chromium-(\d+)", directory.name)
        executable = directory / "chrome-linux64" / "chrome"
        if m and executable.exists():
            candidates.append((int(m[1]), str(executable)))
    return max(candidates)[1] if candidates else None


@contextmanager
def page(width: int = 1600, height: int = 1200) -> Iterator:
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as exc:
        raise BrowserError(t("Playwright is missing: uv sync")) from exc
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(executable_path=chromium())
        except Error as exc:
            raise BrowserError(
                t(
                    "Chromium does not start ({error}); set LINEAGE_CHROMIUM or run 'uv run playwright install chromium'",
                    error=exc,
                )
            ) from exc
        try:
            context = browser.new_context(
                user_agent=BROWSER_UA, locale="nl-NL", viewport={"width": width, "height": height}
            )
            yield context.new_page()
        finally:
            browser.close()

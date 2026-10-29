"""Questions on the Geneanet forum: post a draft from the forum folder and read the replies.

Post only reading and search questions about people who died before 1900, as the project agreements allow.
Credentials live outside the repository, in ~/.config/lineage/geneanet.env (or the file
in LINEAGE_GENEANET_CONFIG); the browser session is kept in ~/.cache/lineage/geneanet-state.json.

A draft is a Markdown file with a header between '---' lines (forum, title, persons, crops, status)
and the message as body. After posting the header gets the thread link; replies are appended to the file.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from lineage import credentials, settings
from lineage.browser import BrowserError, chromium
from lineage.i18n import t
from lineage.web import BROWSER_UA

BASE = "https://nl.geneanet.org"
PALEOGRAPHY = 55260
STATUSES = ("draft", "posted", "closed")
LEGACY_STATUSES = {"concept": "draft", "geplaatst": "posted", "afgesloten": "closed"}
LEGACY_KEYS = {
    "titel": "title",
    "personen": "persons",
    "uitsneden": "crops",
    "draad": "thread",
    "geplaatst": "posted",
    "reacties": "replies",
}
STATE = Path.home() / ".cache" / "lineage" / "geneanet-state.json"
_REPLIES_HEADING = re.compile(r"\n## (?:Replies|Reacties)\n")


class ForumError(RuntimeError):
    pass


@dataclass
class Draft:
    path: Path
    header: dict[str, str]
    text: str
    replies: list[str] = field(default_factory=list)

    @property
    def crops(self) -> list[Path]:
        return [Path(x.strip()) for x in self.header.get("crops", "").split(",") if x.strip()]

    @property
    def reply_count(self) -> int:
        return int(self.header.get("replies", "0") or 0)


def read_draft(path: Path) -> Draft:
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ForumError(t("{path}: header between '---' lines is missing", path=path))
    header_text, _, rest = content[4:].partition("\n---\n")
    header: dict[str, str] = {}
    for line in header_text.splitlines():
        key, _, value = line.partition(":")
        key = key.strip()
        if key:
            header[LEGACY_KEYS.get(key, key)] = value.strip()
    for required in ("title", "status"):
        if not header.get(required):
            raise ForumError(t("{path}: '{key}' is missing in the header", path=path, key=required))
    header["status"] = LEGACY_STATUSES.get(header["status"], header["status"])
    if header["status"] not in STATUSES:
        raise ForumError(t("{path}: unknown status {status!r}", path=path, status=header["status"]))
    text, *tail = _REPLIES_HEADING.split(rest, 1)
    replies = tail[0] if tail else ""
    lines = text.strip().splitlines()
    # The draft repeats the title as its first line, for copying by hand; the forum takes it from the header.
    if lines and lines[0].strip() == header["title"]:
        lines = lines[1:]
    blocks = [b.strip() for b in re.split(r"\n(?=### )", replies.strip()) if b.strip()]
    return Draft(path, header, "\n".join(lines).strip(), blocks)


def write_draft(draft: Draft) -> None:
    header = "\n".join(f"{k}: {v}" for k, v in draft.header.items())
    content = f"---\n{header}\n---\n{draft.header['title']}\n\n{draft.text}\n"
    if draft.replies:
        content += "\n## Replies\n\n" + "\n\n".join(draft.replies) + "\n"
    draft.path.write_text(content, encoding="utf-8")


def bbcode(text: str) -> str:
    """Markdown-light to phpBB BBCode: quotes, links, and uncertain letters in brackets kept as text."""
    # "al[s]" or "Jacob[s]" would otherwise switch on strike-through: write uncertain letters in parentheses.
    text = re.sub(r"\[([A-Za-z.]{1,8})\]", r"(\1)", text)
    out: list[str] = []
    quote: list[str] = []
    for line in text.splitlines() + [""]:
        if line.startswith("> "):
            quote.append(line[2:])
            continue
        if quote:
            out.append("[quote]" + "\n".join(quote) + "[/quote]")
            quote = []
        out.append(line)
    return re.sub(r"(https?://\S+)", r"[url]\1[/url]", "\n".join(out).strip())


def config() -> dict[str, str]:
    return credentials.load(
        "geneanet.env",
        "LINEAGE_GENEANET_",
        ("LINEAGE_GENEANET_USER", "LINEAGE_GENEANET_PASSWORD"),
        ForumError,
        renamed={"GEBRUIKER": "USER", "WACHTWOORD": "PASSWORD"},
    )


@contextmanager
def session() -> Iterator:
    """A logged-in page; logs in again when the stored session has expired."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserError(t("Playwright is missing: uv sync")) from exc
    cfg = config()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium())
        try:
            context = browser.new_context(
                storage_state=str(STATE) if STATE.exists() else None,
                user_agent=BROWSER_UA,
                locale="nl-NL",
                viewport={"width": 1600, "height": 1400},
            )
            page = context.new_page()
            page.goto(f"{BASE}/forum/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            if cfg["LINEAGE_GENEANET_USER"] not in page.inner_text("body"):
                _log_in(page, cfg)
            STATE.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(STATE))
            os.chmod(STATE, 0o600)
            yield page
            context.storage_state(path=str(STATE))
        finally:
            browser.close()


def _log_in(page, cfg: dict[str, str]) -> None:
    page.goto(f"{BASE}/connexion/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    button = page.get_by_role("button", name=re.compile("accepteer", re.I))
    if button.count():
        button.first.click()
    page.fill("#_username", cfg["LINEAGE_GENEANET_USER"])
    page.fill("#_password", cfg["LINEAGE_GENEANET_PASSWORD"])
    page.check("#_remember_me")
    page.locator("#_password").press("Enter")
    page.wait_for_timeout(5000)
    page.goto(f"{BASE}/forum/", wait_until="domcontentloaded", timeout=60000)
    if cfg["LINEAGE_GENEANET_USER"] not in page.inner_text("body"):
        raise ForumError(t("logging in to Geneanet failed"))


def _topics(page, forum: int) -> dict[str, str]:
    page.goto(f"{BASE}/forum/viewforum.php?f={forum}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    found = {}
    for a in page.query_selector_all("a.topictitle"):
        topic = re.search(r"[?&]t=(\d+)", a.get_attribute("href") or "")
        if topic:
            found[(a.inner_text() or "").strip()] = f"{BASE}/forum/viewtopic.php?t={topic[1]}"
    return found


def post(draft: Draft, preview: bool = False) -> str | None:
    """Post the draft as a new topic; returns the thread URL (None for a preview)."""
    if draft.header["status"] != "draft" or draft.header.get("thread"):
        raise ForumError(
            t(
                "{name}: already posted ({thread})",
                name=draft.path.name,
                thread=draft.header.get("thread", draft.header["status"]),
            )
        )
    if missing := [str(p) for p in draft.crops if not p.is_file()]:
        raise ForumError(t("crops not found: {crops}", crops=", ".join(missing)))
    subject = re.sub(r"\[([A-Za-z.]{1,8})\]", r"(\1)", draft.header["title"])
    forum = int(draft.header.get("forum-id", PALEOGRAPHY))
    with session() as page:
        if not preview and subject in _topics(page, forum):
            raise ForumError(t("a topic '{subject}' already exists in the forum", subject=subject))
        page.goto(
            f"{BASE}/forum/posting.php?mode=post&f={forum}",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.wait_for_timeout(2000)
        page.fill("#subject", subject)
        page.fill("textarea[name=message]", bbcode(draft.text))
        if page.is_visible("#notify"):
            page.check("#notify")
        if draft.crops:
            page.set_input_files("input[type=file]", [str(p) for p in draft.crops])
            for _ in range(120):
                page.wait_for_timeout(1000)
                if page.locator("#file-list tr.attach-row[data-attach-id]").count() >= len(
                    draft.crops
                ):
                    break
            else:
                raise ForumError(t("attachments not uploaded within two minutes"))
        # phpBB refuses a form sent too quickly after opening; the post button itself is intercepted by a
        # script, so the form is submitted with the button as submitter.
        page.wait_for_timeout(5000)
        button = "preview" if preview else "post"
        with page.expect_navigation(timeout=60000):
            page.evaluate(
                "k => { const f = document.getElementById('postform');"
                " f.requestSubmit(f.querySelector('input[name=' + k + ']')); }",
                button,
            )
        page.wait_for_timeout(3000)
        error = page.query_selector("#postform .error, .errorbox")
        if error and (error.inner_text() or "").strip():
            raise ForumError(t("forum refuses: {reason}", reason=error.inner_text().strip()[:300]))
        if preview:
            return None
        url = _topics(page, forum).get(subject)
    if not url:
        raise ForumError(t("posted, but the topic is not in the list; check the forum yourself"))
    draft.header["status"] = "posted"
    draft.header["posted"] = dt.date.today().isoformat()
    draft.header["thread"] = url
    draft.header["replies"] = "0"
    write_draft(draft)
    return url


def read_replies(drafts: list[Draft]) -> list[tuple[Draft, list[str]]]:
    """New replies per posted draft, appended to the draft file."""
    posted = [d for d in drafts if d.header["status"] == "posted" and d.header.get("thread")]
    if not posted:
        return []
    found = []
    with session() as page:
        for draft in posted:
            messages = []
            url = draft.header["thread"]
            start = 0
            while True:
                page.goto(f"{url}&start={start}", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1500)
                posts = page.query_selector_all("div.post")
                for post_element in posts:
                    author = post_element.query_selector(".author")
                    content = post_element.query_selector(".content")
                    messages.append(
                        (
                            re.sub(r"\s+", " ", author.inner_text() if author else "").strip(),
                            (content.inner_text() if content else "").strip(),
                        )
                    )
                if len(posts) < 10 or not page.query_selector("a[rel=next]"):
                    break
                start += len(posts)
            new = messages[1 + draft.reply_count :]
            if new:
                blocks = [f"### {head}\n\n{text}" for head, text in new]
                draft.replies.extend(blocks)
                draft.header["replies"] = str(len(messages) - 1)
                write_draft(draft)
                found.append((draft, blocks))
    return found


def drafts(folder: Path | None = None) -> list[Draft]:
    folder = folder or settings.current().path("forum")
    return [read_draft(p) for p in sorted(folder.glob("*.md"))]

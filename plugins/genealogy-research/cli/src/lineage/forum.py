"""Questions on the Geneanet forum: drafts in the forum folder, posted and read by the user in a browser.

Geneanet's terms forbid robots, so nothing here logs in, posts or reads the forum. Post only reading and
search questions about people who died before 1900, as the project agreements allow.

A draft is a Markdown file with a header between '---' lines (forum, title, persons, crops, status)
and the message as body. After posting by hand the header gets the thread link; replies can be copied
under a '## Replies' heading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lineage.i18n import t

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


def preview(draft: Draft) -> str:
    """The topic as it is to be posted by hand: Geneanet's terms forbid posting with a script."""
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
    parts = [
        t("Post by hand: {url}", url=f"{BASE}/forum/posting.php?mode=post&f={forum}"),
        t("Subject: {subject}", subject=subject),
        "",
        bbcode(draft.text),
    ]
    if draft.crops:
        parts += ["", t("Attachments:")] + [f"  {p}" for p in draft.crops]
    parts += [
        "",
        t(
            "Afterwards set status: posted, posted: <date> and thread: <url> in the header of {name}.",
            name=draft.path.name,
        ),
    ]
    return "\n".join(parts)

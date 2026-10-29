"""Requests that only a person can make: a mail to an archive or institution for a source that no
search, index or scan can reach. One Markdown file per request in research/requests/, with a small
header (to, subject, persons, status) and the draft mail as body, so the user can send them in batches.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from lineage import settings
from lineage.i18n import t

STATUSES = ("draft", "on_hold", "sent", "answered", "closed")
OPEN = ("draft", "on_hold", "sent")
LEGACY_STATUSES = {
    "concept": "draft",
    "aangehouden": "on_hold",
    "verstuurd": "sent",
    "beantwoord": "answered",
    "afgesloten": "closed",
}
LEGACY_KEYS = {
    "aan": "to",
    "instelling": "institution",
    "onderwerp": "subject",
    "personen": "persons",
    "aangemaakt": "created",
    "afzender": "sender",
    "verstuurd": "sent",
    "antwoord-op": "in-reply-to",
    "beantwoord": "answered",
    "aangehouden": "on_hold",
    "afgesloten": "closed",
    "bijlagen": "attachments",
}
USER_SENDER = "user"
_HEADER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)
_BACKGROUND = re.compile(r"\n## (?:Background|Achtergrond)")


class RequestError(ValueError):
    pass


@dataclass
class Request:
    path: Path
    to: str
    institution: str
    subject: str
    persons: list[str]
    status: str
    created: str
    sent: str = ""
    text: str = ""
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.path.stem


def normalize_status(status: str) -> str:
    return LEGACY_STATUSES.get(status, status)


def read(path: Path) -> Request:
    m = _HEADER.match(path.read_text(encoding="utf-8"))
    if not m:
        raise RequestError(t("{path}: header between '---' lines is missing", path=path))
    fields = {}
    for line in m[1].splitlines():
        key, _, value = line.partition(":")
        key = LEGACY_KEYS.get(key.strip(), key.strip())
        if not key:
            continue
        if key in fields:
            raise RequestError(t("{path}: '{key}' appears twice in the header", path=path, key=key))
        fields[key] = value.strip()
    for required in ("to", "subject", "status"):
        if not fields.get(required):
            raise RequestError(t("{path}: '{key}' is missing", path=path, key=required))
    fields["status"] = normalize_status(fields["status"])
    if fields["status"] not in STATUSES:
        raise RequestError(t("{path}: unknown status {status!r}", path=path, status=fields["status"]))
    if fields.get("sender") == "andy":
        fields["sender"] = USER_SENDER
    return Request(
        path=path,
        to=fields["to"],
        institution=fields.get("institution", ""),
        subject=fields["subject"],
        persons=fields.get("persons", "").replace(",", " ").split(),
        status=fields["status"],
        created=fields.get("created", ""),
        sent=fields.get("sent", ""),
        text=m[2].strip(),
        fields=fields,
    )


def load_all(folder: Path | None = None) -> list[Request]:
    folder = folder or settings.current().path("requests")
    if not folder.exists():
        return []
    return sorted((read(p) for p in folder.glob("*.md")), key=lambda r: (r.created, r.name))


def errors(folder: Path | None = None) -> list[str]:
    """Every request that cannot be read, so `validate` can report them all instead of stopping at the first."""
    folder = folder or settings.current().path("requests")
    found = []
    for path in sorted(folder.glob("*.md")) if folder.exists() else []:
        try:
            read(path)
        except RequestError as exc:
            found.append(str(exc))
    return found


def find(name: str, folder: Path | None = None) -> Request:
    hits = [r for r in load_all(folder) if r.name == name or r.name.startswith(name)]
    if len(hits) != 1:
        raise RequestError(t("{count} requests match {name!r}", count=len(hits), name=name))
    return hits[0]


def mark(request: Request, status: str, today: dt.date | None = None) -> None:
    status = normalize_status(status)
    if status not in STATUSES:
        raise RequestError(t("unknown status {status!r}", status=status))
    date = (today or dt.date.today()).isoformat()
    text = request.path.read_text(encoding="utf-8")
    header, _, rest = text[4:].partition("\n---\n")
    lines = [
        line
        for line in header.splitlines()
        if LEGACY_KEYS.get(key := line.partition(":")[0].strip(), key) not in ("status", status)
    ]
    lines.append(f"status: {status}")
    if status != "draft":
        lines.append(f"{status}: {date}")
    request.path.write_text("---\n" + "\n".join(lines) + "\n---\n" + rest, encoding="utf-8")


def overview(requests: list[Request], with_text: bool = False) -> str:
    if not requests:
        return t("no requests")
    lines = []
    for r in requests:
        lines.append(f"[{r.status}] {r.name}  ({', '.join(r.persons) or '-'})")
        lines.append(t("    to: {to}{institution}", to=r.to, institution=f"  ({r.institution})" if r.institution else ""))
        lines.append(t("    subject: {subject}", subject=r.subject))
        if r.sent:
            lines.append(t("    sent: {date}", date=r.sent))
        if r.fields.get("sender") == USER_SENDER:
            lines.append(t("    sent by the user: a reply arrives in their own mailbox"))
        for reply in replies(r):
            lines.append(t("    reply: {path}", path=reply))
        if with_text:
            lines.append("")
            lines.extend("    " + line for line in mail_text(r).splitlines())
            lines.append("")
    return "\n".join(lines)


def replies(r: Request) -> list[Path]:
    """Replies saved by `lineage mail inbox`, named <date>-<request>-<n>.md."""
    folder = settings.current().path("replies")
    return sorted(folder.glob(f"*-{r.name}-*.md")) if folder.exists() else []


def mail_text(r: Request) -> str:
    """The mail itself: the body up to an optional '## Background' section meant for the user."""
    return _BACKGROUND.split(r.text, 1)[0].strip()

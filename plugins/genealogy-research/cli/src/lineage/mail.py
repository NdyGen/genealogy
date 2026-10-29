"""Sending approved requests (research/requests/) and collecting the replies, via the research
assistant's own mailbox. Credentials live outside the repository, in ~/.config/lineage/mail.env
(or the file in LINEAGE_MAIL_CONFIG), because sessions run under more than one Claude account.
"""

from __future__ import annotations

import datetime as dt
import email
import email.policy
import imaplib
import mimetypes
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr, parsedate_to_datetime
from pathlib import Path

from . import credentials, requests, settings
from .i18n import t

# Account notices from the mail provider are not research correspondence.
IGNORED_SENDERS = ("no-reply@accounts.google.com",)
# The Geneanet account (forum questions) uses this mailbox; its notifications are not replies to a request.
FORUM_DOMAIN = "geneanet.org"


class MailError(RuntimeError):
    pass


def config() -> dict[str, str]:
    return credentials.load(
        "mail.env",
        "LINEAGE_MAIL_",
        ("LINEAGE_MAIL_ADDRESS", "LINEAGE_MAIL_PASSWORD"),
        MailError,
        renamed={"ADRES": "ADDRESS", "WACHTWOORD": "PASSWORD"},
    )


def _host(value: str, default_port: int) -> tuple[str, int]:
    host, _, port = value.partition(":")
    return host, int(port or default_port)


def _smtp(cfg: dict[str, str]) -> smtplib.SMTP_SSL:
    host, port = _host(cfg.get("LINEAGE_MAIL_SMTP", "smtp.gmail.com:465"), 465)
    connection = smtplib.SMTP_SSL(host, port, timeout=60)
    try:
        connection.login(cfg["LINEAGE_MAIL_ADDRESS"], cfg["LINEAGE_MAIL_PASSWORD"])
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(
            t("SMTP login refused ({code}); Gmail needs an app password", code=exc.smtp_code)
        ) from exc
    return connection


def _imap(cfg: dict[str, str]) -> imaplib.IMAP4_SSL:
    host, port = _host(cfg.get("LINEAGE_MAIL_IMAP", "imap.gmail.com:993"), 993)
    connection = imaplib.IMAP4_SSL(host, port)
    try:
        connection.login(cfg["LINEAGE_MAIL_ADDRESS"], cfg["LINEAGE_MAIL_PASSWORD"])
    except imaplib.IMAP4.error as exc:
        raise MailError(
            t("IMAP login refused: {error}; Gmail needs an app password", error=exc)
        ) from exc
    return connection


def test() -> str:
    cfg = config()
    _smtp(cfg).quit()
    _imap(cfg).logout()
    return t("logged in as {address} (SMTP and IMAP)", address=cfg["LINEAGE_MAIL_ADDRESS"])


def build_message(r: requests.Request, cfg: dict[str, str]) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.current().sender_name, cfg["LINEAGE_MAIL_ADDRESS"]))
    msg["To"] = r.to
    msg["Subject"] = r.subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=cfg["LINEAGE_MAIL_ADDRESS"].split("@")[-1])
    if previous := r.fields.get("in-reply-to"):
        msg["In-Reply-To"] = previous
        msg["References"] = previous
    msg.set_content(requests.mail_text(r) + "\n")
    for path in attachment_paths(r):
        kind, _ = mimetypes.guess_type(path.name)
        main, _, sub = (kind or "application/octet-stream").partition("/")
        msg.add_attachment(path.read_bytes(), maintype=main, subtype=sub, filename=path.name)
    return msg


def attachment_paths(r: requests.Request) -> list[Path]:
    """The files in the header field `attachments:` (comma-separated, relative to the project root)."""
    root = settings.current().root
    paths = [root / d.strip() for d in r.fields.get("attachments", "").split(",") if d.strip()]
    if missing := [str(p) for p in paths if not p.is_file()]:
        raise MailError(
            t("{name}: attachment missing: {files}", name=r.name, files=", ".join(missing))
        )
    return paths


def _require_enabled() -> None:
    """Credentials belong to the user, not the project: without this, every project would empty the same
    mailbox into its own folder."""
    if not settings.current().mail_enabled:
        raise MailError(t("mail is not enabled for this project; set [mail] enabled = true in lineage.toml"))


def send(r: requests.Request, approved: bool) -> str:
    """Only after the user's explicit approval: a sent mail cannot be taken back.
    Mail to the user's own address ([mail] own_address) needs none."""
    _require_enabled()
    own = settings.current().own_address
    if not approved and not (own and r.to.strip().lower() == own):
        raise MailError(t("sending needs --approved, after the user has approved the draft"))
    if r.status not in ("draft", "on_hold"):
        raise MailError(
            t("{name} has status {status}; only a draft is sent", name=r.name, status=r.status)
        )
    cfg = config()
    msg = build_message(r, cfg)
    connection = _smtp(cfg)
    try:
        connection.send_message(msg)
    finally:
        connection.quit()
    requests.mark(r, "sent")
    _set_field(r.path, "message-id", msg["Message-ID"])
    return t("sent to {to}: {subject} ({id})", to=r.to, subject=r.subject, id=msg["Message-ID"])


def _set_field(path: Path, key: str, value: str) -> None:
    text = path.read_text(encoding="utf-8")
    header, _, rest = text[4:].partition("\n---\n")
    lines = [line for line in header.splitlines() if not line.startswith(f"{key}:")]
    lines.append(f"{key}: {value}")
    path.write_text("---\n" + "\n".join(lines) + "\n---\n" + rest, encoding="utf-8")


def _plain_text(msg: email.message.EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    return text.strip()


def save_attachments(msg: email.message.EmailMessage, target: Path) -> list[Path]:
    saved: list[Path] = []
    for part in msg.iter_attachments():
        name = Path(part.get_filename() or f"attachment-{len(saved) + 1}").name
        path = target / name
        n = 2
        while path in saved:
            path = target / f"{Path(name).stem}-{n}{Path(name).suffix}"
            n += 1
        target.mkdir(parents=True, exist_ok=True)
        path.write_bytes(part.get_payload(decode=True) or b"")
        saved.append(path)
    return saved


def link_reply(
    msg: email.message.EmailMessage, candidates: list[requests.Request]
) -> requests.Request | None:
    """A reply belongs to the request whose Message-ID it cites, else to the sent request from that address."""
    references = f"{msg.get('In-Reply-To', '')} {msg.get('References', '')}"
    for r in candidates:
        mid = r.fields.get("message-id")
        if mid and mid in references:
            return r
    sender = parseaddr(msg.get("From", ""))[1].lower()
    matches = [r for r in candidates if r.status == "sent" and r.to.lower() == sender]
    return matches[0] if len(matches) == 1 else None


def is_forum_notice(msg: email.message.Message) -> bool:
    domain = parseaddr(msg.get("From", ""))[1].lower().rpartition("@")[2]
    return domain == FORUM_DOMAIN or domain.endswith("." + FORUM_DOMAIN)


def all_mail_folder(listing: list[bytes]) -> str:
    """Gmail's All Mail (flag \\All) also holds mail the user archived after reading it in the browser."""
    for line in listing:
        text = line.decode()
        if "\\All" in text:
            return text.split(' "/" ', 1)[1]
    return "INBOX"


def known_ids(folder: Path) -> set[str]:
    ids = set()
    for path in folder.glob("*.md"):
        for line in path.read_text(encoding="utf-8").split("\n---\n", 1)[0].splitlines():
            if line.startswith("message-id: "):
                ids.add(line.removeprefix("message-id: ").strip())
    return ids


def inbox(folder: Path | None = None, forum_folder: Path | None = None) -> list[str]:
    """Mail not yet saved in the replies folder is saved there and marked read.

    Known mail is recognised by Message-ID, not by the read flag: the user may read this mailbox too.
    """
    _require_enabled()
    project = settings.current()
    folder = folder or project.path("replies")
    forum_folder = forum_folder or project.path("forum_notifications")
    cfg = config()
    connection = _imap(cfg)
    reported = []
    known = known_ids(folder) | known_ids(forum_folder)
    try:
        connection.select(all_mail_folder(connection.list()[1]), readonly=False)
        _, data = connection.search(None, "ALL")
        own = cfg["LINEAGE_MAIL_ADDRESS"].lower()
        candidates = requests.load_all()
        for number in data[0].split():
            _, head = connection.fetch(number, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM)])")
            headers = email.message_from_bytes(head[0][1])
            mid = headers.get("Message-ID", "").strip()
            if mid and mid in known:
                continue
            if parseaddr(headers.get("From", ""))[1].lower() == own:
                continue
            _, parts = connection.fetch(number, "(RFC822)")
            msg = email.message_from_bytes(parts[0][1], policy=email.policy.default)
            if parseaddr(msg.get("From", ""))[1].lower() in IGNORED_SENDERS:
                connection.store(number, "+FLAGS", "\\Seen")
                continue
            date = _date(msg)
            if is_forum_notice(msg):
                forum_folder.mkdir(parents=True, exist_ok=True)
                path = forum_folder / f"{date:%Y-%m-%d}-geneanet-{number.decode()}.md"
                path.write_text(
                    f"---\nfrom: {msg.get('From', '')}\nsubject: {msg.get('Subject', '')}\n"
                    f"date: {date:%Y-%m-%d %H:%M}\nmessage-id: {mid}\n---\n{_plain_text(msg)}\n",
                    encoding="utf-8",
                )
                connection.store(number, "+FLAGS", "\\Seen")
                reported.append(f"{_relative(path, project.root)}  ({msg.get('Subject', '')})")
                continue
            request = link_reply(msg, candidates)
            name = request.name if request else "unlinked"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{date:%Y-%m-%d}-{name}-{number.decode()}.md"
            files = save_attachments(msg, project.path("request_attachments") / path.stem)
            attachments_line = (
                f"attachments: {', '.join(_relative(f, project.root) for f in files)}\n"
                if files
                else ""
            )
            path.write_text(
                f"---\nfrom: {msg.get('From', '')}\nsubject: {msg.get('Subject', '')}\n"
                f"date: {date:%Y-%m-%d %H:%M}\nrequest: {name}\nmessage-id: {mid}\n{attachments_line}"
                f"---\n{_plain_text(msg)}\n",
                encoding="utf-8",
            )
            connection.store(number, "+FLAGS", "\\Seen")
            reported.append(
                f"{_relative(path, project.root)}  ({msg.get('From', '')}: {msg.get('Subject', '')})"
            )
    finally:
        connection.logout()
    return reported


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _date(msg: email.message.EmailMessage) -> dt.datetime:
    try:
        return parsedate_to_datetime(msg.get("Date", ""))
    except (TypeError, ValueError):
        return dt.datetime.now()

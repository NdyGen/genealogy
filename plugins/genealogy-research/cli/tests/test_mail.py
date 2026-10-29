import email
import email.policy

import pytest

from lineage import mail, requests
from tests.conftest import project

DRAFT = """---
to: info@archive.example.org
institution: Archive
subject: Question about a burial register
persons: I1
status: draft
created: 2026-10-02
---
Dear sir or madam,

My question.

Kind regards,

A. Researcher

## Background
Only for us.
"""


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "research" / "requests").mkdir(parents=True)
    (tmp_path / "research" / "requests" / "2026-10-02-burial-register.md").write_text(DRAFT)
    cfg = tmp_path / "mail.env"
    cfg.write_text("LINEAGE_MAIL_ADDRESS=assistant@example.org\nLINEAGE_MAIL_PASSWORD=secret\n")
    monkeypatch.setenv("LINEAGE_MAIL_CONFIG", str(cfg))
    project(tmp_path, mail_enabled=True, own_address="me@example.org", sender_name="Ann Doe")
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            sent.append(msg)

        def quit(self):
            pass

    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP)
    return tmp_path, sent


def test_sending_needs_explicit_approval(environment):
    _, sent = environment
    with pytest.raises(mail.MailError, match="approved"):
        mail.send(requests.find("2026-10-02-burial-register"), approved=False)
    assert sent == []


def test_mail_to_the_own_address_needs_no_approval(environment):
    tmp_path, sent = environment
    path = tmp_path / "research" / "requests" / "2026-10-16-own.md"
    path.write_text(DRAFT.replace("info@archive.example.org", "Me@Example.org"))
    mail.send(requests.find("2026-10-16-own"), approved=False)
    assert len(sent) == 1


def test_sent_mail_leaves_out_the_background_and_marks_the_request(environment):
    _, sent = environment
    mail.send(requests.find("2026-10-02-burial-register"), approved=True)
    msg = sent[0]
    assert msg["To"] == "info@archive.example.org" and "Ann Doe" in msg["From"]
    assert "Only for us" not in msg.get_content()
    a = requests.find("2026-10-02-burial-register")
    assert a.status == "sent" and a.fields["message-id"] == msg["Message-ID"]
    with pytest.raises(mail.MailError):
        mail.send(a, approved=True)


def test_reply_is_linked_by_message_id_or_sender(environment):
    mail.send(requests.find("2026-10-02-burial-register"), approved=True)
    a = requests.find("2026-10-02-burial-register")
    reply = email.message_from_string(
        f"From: Someone <someone@elsewhere.example.org>\nIn-Reply-To: {a.fields['message-id']}\nSubject: Re\n\nYes.",
        policy=email.policy.default,
    )
    assert mail.link_reply(reply, requests.load_all()).name == a.name
    from_archive = email.message_from_string(
        "From: Archive <info@archive.example.org>\nSubject: Your question\n\nNo.", policy=email.policy.default
    )
    assert mail.link_reply(from_archive, requests.load_all()).name == a.name


def test_attachments_are_saved_with_safe_names(tmp_path):
    msg = email.message.EmailMessage()
    msg["From"] = "Archive <info@archive.example.org>"
    msg["Subject"] = "Re: prayer card"
    msg.set_content("The card is attached.")
    msg.add_attachment(
        b"\xff\xd8image", maintype="image", subtype="jpeg", filename="../card front.jpg"
    )
    msg.add_attachment(
        b"\xff\xd8image2", maintype="image", subtype="jpeg", filename="card front.jpg"
    )
    saved = mail.save_attachments(msg, tmp_path / "reply")
    assert [p.name for p in saved] == ["card front.jpg", "card front-2.jpg"]
    assert all(p.parent == tmp_path / "reply" for p in saved)
    assert saved[0].read_bytes() == b"\xff\xd8image"


def test_mail_without_attachments_saves_nothing(tmp_path):
    msg = email.message_from_string(
        "From: a@example.org\nSubject: x\n\nText.", policy=email.policy.default
    )
    assert mail.save_attachments(msg, tmp_path / "reply") == []
    assert not (tmp_path / "reply").exists()


def test_saved_replies_are_known_by_message_id(tmp_path):
    (tmp_path / "a.md").write_text(
        "---\nvan: x\nmessage-id: <1@x>\n---\nmessage-id: <2@x> in the text\n"
    )
    (tmp_path / "b.md").write_text("---\nvan: y\n---\nWithout id.\n")
    assert mail.known_ids(tmp_path) == {"<1@x>"}


def test_all_mail_folder_is_found_by_its_flag():
    lijst = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
        b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"',
    ]
    assert mail.all_mail_folder(lijst) == '"[Gmail]/All Mail"'
    assert mail.all_mail_folder([b'(\\HasNoChildren) "/" "INBOX"']) == "INBOX"


def test_follow_up_is_sent_as_reply_in_the_same_thread(environment):
    root, sent = environment
    path = root / "research" / "requests" / "2026-10-02-burial-register.md"
    path.write_text(
        DRAFT.replace("status: draft\n", "status: draft\nin-reply-to: <earlier@example.org>\n")
    )
    mail.send(requests.find("2026-10-02-burial-register"), approved=True)
    assert sent[0]["In-Reply-To"] == "<earlier@example.org>"
    assert sent[0]["References"] == "<earlier@example.org>"


def test_files_in_the_header_go_along_as_attachments(environment):
    root, sent = environment
    (root / "scan.jpg").write_bytes(b"\xff\xd8jpeg")
    path = root / "research" / "requests" / "2026-10-02-burial-register.md"
    path.write_text(DRAFT.replace("status: draft\n", "status: draft\nattachments: scan.jpg\n"))
    mail.send(requests.find("2026-10-02-burial-register"), approved=True)
    (attachment,) = sent[0].iter_attachments()
    assert attachment.get_filename() == "scan.jpg" and attachment.get_content_type() == "image/jpeg"
    assert attachment.get_content() == b"\xff\xd8jpeg"


def test_missing_attachment_stops_the_mail(environment):
    root, sent = environment
    path = root / "research" / "requests" / "2026-10-02-burial-register.md"
    path.write_text(DRAFT.replace("status: draft\n", "status: draft\nattachments: gone.jpg\n"))
    with pytest.raises(mail.MailError, match="gone.jpg"):
        mail.send(requests.find("2026-10-02-burial-register"), approved=True)
    assert sent == []


def test_geneanet_notifications_are_forum_messages_not_replies():
    from email.message import EmailMessage

    notice = EmailMessage()
    notice["From"] = "Geneanet <notification@forum.geneanet.org>"
    assert mail.is_forum_notice(notice)
    notice.replace_header("From", "Geneanet <noreply@geneanet.org>")
    assert mail.is_forum_notice(notice)
    archive = EmailMessage()
    archive["From"] = "info@archive.example.org"
    assert not mail.is_forum_notice(archive)
    lookalike = EmailMessage()
    lookalike["From"] = "someone@notgeneanet.org"
    assert not mail.is_forum_notice(lookalike)


def test_credentials_fall_back_to_the_old_file_and_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LINEAGE_MAIL_CONFIG", raising=False)
    monkeypatch.delenv("NDYGEN_MAIL_CONFIG", raising=False)
    monkeypatch.delenv("LINEAGE_MAIL_ADDRESS", raising=False)
    old = tmp_path / ".config" / "ndygen"
    old.mkdir(parents=True)
    (old / "mail.env").write_text("NDYGEN_MAIL_ADRES=old@example.org\nNDYGEN_MAIL_WACHTWOORD=pw\nNDYGEN_MAIL_SMTP=smtp.example.org:25\n")
    cfg = mail.config()
    assert cfg["LINEAGE_MAIL_ADDRESS"] == "old@example.org"
    assert cfg["LINEAGE_MAIL_PASSWORD"] == "pw"
    assert cfg["LINEAGE_MAIL_SMTP"] == "smtp.example.org:25"


def test_missing_credentials_raise_a_mail_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LINEAGE_MAIL_CONFIG", str(tmp_path / "none.env"))
    monkeypatch.delenv("LINEAGE_MAIL_ADDRESS", raising=False)
    monkeypatch.delenv("NDYGEN_MAIL_ADRES", raising=False)
    with pytest.raises(mail.MailError, match="LINEAGE_MAIL_ADDRESS is missing"):
        mail.config()


def test_follow_up_with_the_dutch_header_key_is_a_reply(environment):
    root, sent = environment
    path = root / "research" / "requests" / "2026-10-02-burial-register.md"
    path.write_text(DRAFT.replace("status: draft\n", "status: concept\nantwoord-op: <earlier@example.org>\n"))
    mail.send(requests.find("2026-10-02-burial-register"), approved=True)
    assert sent[0]["In-Reply-To"] == "<earlier@example.org>"


def test_a_project_without_mail_enabled_neither_sends_nor_reads(environment):
    root, sent = environment
    project(root)
    with pytest.raises(mail.MailError, match="not enabled"):
        mail.send(requests.find("2026-10-02-burial-register"), approved=True)
    with pytest.raises(mail.MailError, match="not enabled"):
        mail.inbox()
    assert sent == []

"""`lineage doctor` and `lineage auth`: what the machine has, and the credential files of the optional services."""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from lineage import browser, credentials
from lineage.i18n import t


@dataclass(frozen=True)
class Service:
    file: str
    prefix: str
    secret: str
    keys: tuple[str, ...]


SERVICES = {
    "mail": Service("mail.env", "LINEAGE_MAIL_", "PASSWORD", ("ADDRESS", "PASSWORD")),
    "gramps": Service("gramps.env", "LINEAGE_GRAMPS_", "PASSWORD", ("USER", "PASSWORD")),
    "transkribus": Service(
        "transkribus.env", "LINEAGE_TRANSKRIBUS_", "PASSWORD", ("USER", "PASSWORD")
    ),
    "geneanet": Service("geneanet.env", "LINEAGE_GENEANET_", "PASSWORD", ("USER", "PASSWORD")),
}


def purpose(name: str) -> str:
    return {
        "mail": t("a mailbox for request letters to archives"),
        "gramps": t("your Gramps Web server"),
        "transkribus": t("handwriting recognition (costs your credits)"),
        "geneanet": t("questions on the Geneanet forum"),
    }[name]


def label(name: str, key: str) -> str:
    if (name, key) == ("mail", "PASSWORD"):
        return t("password (Gmail: an app password)")
    if (name, key) == ("transkribus", "USER"):
        return t("user name (e-mail)")
    return {"ADDRESS": t("mail address"), "USER": t("user name"), "PASSWORD": t("password")}[key]


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    required: bool
    detail: str


def _version(*command: str) -> str | None:
    if not shutil.which(command[0]):
        return None
    out = subprocess.run(command, capture_output=True, text=True, check=False)
    return (out.stdout or out.stderr).strip().splitlines()[0] if out.returncode == 0 else None


def _gi() -> bool:
    """The system Python, as gramps_tree uses it; inside uv run, python3 on PATH is lineage's own."""
    python = shutil.which("python3", path="/usr/bin")
    if not python:
        return False
    return (
        subprocess.run([python, "-c", "import gi"], capture_output=True, check=False).returncode
        == 0
    )


def checks() -> list[Check]:
    uv, git, hc, herdr, dot = (
        _version(c, "--version") for c in ("uv", "git", "hc", "herdr", "dot")
    )
    chromium = browser.chromium()
    gi = _gi()
    py = sys.version_info
    return [
        Check("python", py >= (3, 12), True, f"{py.major}.{py.minor}.{py.micro}"),
        Check(
            "uv",
            bool(uv),
            True,
            uv or t("missing: https://docs.astral.sh/uv/getting-started/installation/"),
        ),
        Check(
            "git",
            bool(git),
            True,
            git or t("missing: install git (research rounds are git branches)"),
        ),
        Check(
            "chromium",
            bool(chromium),
            False,
            chromium
            or t(
                "missing; only 'lineage scan' and the forum need it: lineage doctor --install-browser"
            ),
        ),
        Check("hc", bool(hc), False, hc or t("missing; only the hc runner (Herdr app) needs it")),
        Check("herdr", bool(herdr), False, herdr or t("missing; only the herdr runner needs it")),
        Check(
            "graphviz",
            bool(dot),
            False,
            dot or t("missing; 'lineage tree' then writes DOT without SVG"),
        ),
        Check(
            "python3-gi",
            gi,
            False,
            t("present")
            if gi
            else t("missing; only 'lineage gramps sync' needs it (apt install python3-gi)"),
        ),
    ]


def install_browser() -> int:
    return subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"], check=False
    ).returncode


def status(name: str) -> str:
    service = SERVICES[name]
    path = credentials.config_path(service.file, service.prefix)
    if not path.exists():
        return t("not set up ({path} missing; run: ! lineage auth {name})", path=path, name=name)
    try:
        values = credentials.load(
            service.file,
            service.prefix,
            tuple(service.prefix + key for key in service.keys),
            ValueError,
            renamed={"GEBRUIKER": "USER", "WACHTWOORD": "PASSWORD", "ADRES": "ADDRESS"},
        )
    except ValueError as exc:
        return t("incomplete: {error}", error=exc)
    mode = path.stat().st_mode & 0o777
    warning = (
        t("; WARNING: mode {mode:o}, should be 600 (chmod 600 {path})", mode=mode, path=path)
        if mode & 0o077
        else ""
    )
    user = values.get(service.prefix + service.keys[0], "")
    return t("set up in {path} ({user}){warning}", path=path, user=user, warning=warning)


def prompt(name: str, ask=input, ask_secret=getpass.getpass) -> Path:
    """Asks every field on the terminal (the secret without echo) and writes the file with mode 600.
    An empty answer keeps the value that is already in the file."""
    service = SERVICES[name]
    path = credentials.config_path(service.file, service.prefix)
    if path.parent == Path(credentials.LEGACY_CONFIG_DIR).expanduser():
        path = Path(credentials.CONFIG_DIR, service.file).expanduser()
    existing: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.lstrip().startswith("#"):
                existing[key.strip()] = value.strip()
    for key in service.keys:
        question = label(name, key)
        full = service.prefix + key
        known = existing.get(full, "")
        if key == service.secret:
            value = ask_secret(f"{question}{t(' (empty: keep)') if known else ''}: ")
        else:
            value = ask(f"{question}{f' [{known}]' if known else ''}: ").strip()
        if value:
            existing[full] = value
        elif not known:
            raise ValueError(t("{label} is required", label=question))
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("".join(f"{k}={v}\n" for k, v in existing.items()))
    path.chmod(0o600)
    return path

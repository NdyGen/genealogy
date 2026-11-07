"""Claude Code session transcripts (<config dir>/projects/<encoded cwd>/*.jsonl) read for usage and time.

Claude Code writes one line per content block, so an assistant message with three blocks appears three
times with the same message id and the same usage; usage is counted once per message id.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from lineage.limits import LIMIT

TOKEN_KINDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
SYNTHETIC = "<synthetic>"
# A gap longer than this between two lines of one session is waiting (a limit, a human), not work.
ACTIVE_GAP = dt.timedelta(minutes=10)
WEEKLY = re.compile(r"weekly limit", re.I)


def default_config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def project_dir(config_dir: Path, cwd: Path) -> Path:
    """Claude Code names a project's transcript folder after its working directory, every character that
    is not a letter or digit replaced by '-'."""
    return config_dir / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def parse_time(raw: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0

    @classmethod
    def from_api(cls, raw: dict) -> Usage:
        written = raw.get("cache_creation") or {}
        w5 = int(written.get("ephemeral_5m_input_tokens") or 0)
        w1 = int(written.get("ephemeral_1h_input_tokens") or 0)
        total_written = int(raw.get("cache_creation_input_tokens") or 0)
        if w5 + w1 < total_written:
            w5 += total_written - w5 - w1
        return cls(
            int(raw.get("input_tokens") or 0),
            int(raw.get("output_tokens") or 0),
            int(raw.get("cache_read_input_tokens") or 0),
            w5,
            w1,
        )

    def add(self, other: Usage, weight: float = 1.0) -> None:
        for kind in TOKEN_KINDS:
            setattr(self, kind, getattr(self, kind) + round(getattr(other, kind) * weight))

    @property
    def total(self) -> int:
        return sum(getattr(self, kind) for kind in TOKEN_KINDS)


@dataclass
class Message:
    id: str
    time: dt.datetime
    model: str
    usage: Usage
    tool_uses: set[str] = field(default_factory=set)
    commands: list[str] = field(default_factory=list)
    text: str = ""


@dataclass
class Session:
    path: Path
    config_dir: Path
    subagent: bool = False
    first_prompt: str = ""
    times: list[dt.datetime] = field(default_factory=list)
    messages: dict[str, Message] = field(default_factory=dict)

    def limit_hits(self, start: dt.datetime, end: dt.datetime) -> list[Message]:
        return [
            m
            for m in self.messages.values()
            if m.model == SYNTHETIC and start <= m.time <= end and LIMIT.search(m.text)
        ]


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def read(path: Path, config_dir: Path, subagent: bool = False) -> Session:
    session = Session(path, config_dir, subagent)
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            when = parse_time(entry.get("timestamp", ""))
            if when is None:
                continue
            session.times.append(when)
            message = entry.get("message")
            if not isinstance(message, dict):
                continue
            if entry.get("type") == "user" and not session.first_prompt:
                prompt = _text(message.get("content"))
                if prompt and not prompt.startswith("<"):
                    session.first_prompt = prompt[:300]
            if entry.get("type") != "assistant":
                continue
            key = message.get("id") or entry.get("uuid") or f"{path}:{len(session.messages)}"
            known = session.messages.get(key)
            if known is None:
                known = session.messages[key] = Message(
                    key,
                    when,
                    message.get("model") or "",
                    Usage.from_api(message.get("usage") or {}),
                )
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    known.tool_uses.add(block.get("id", ""))
                    command = (block.get("input") or {}).get("command")
                    if isinstance(command, str):
                        known.commands.append(command)
                elif block.get("type") == "text":
                    known.text += block.get("text", "")
    session.times.sort()
    return session


def sessions(folder: Path, config_dir: Path, since: dt.datetime | None = None) -> Iterator[Session]:
    """Every session in a project folder, sub-agents of the Agent tool (in a folder named after their parent
    session) included; files last written before since are skipped."""
    if not folder.is_dir():
        return
    for path in sorted(folder.rglob("*.jsonl")):
        if since is not None and dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC) < since:
            continue
        yield read(path, config_dir, path.parent != folder)


def active_time(
    sessions_times: Iterable[list[dt.datetime]], start: dt.datetime, end: dt.datetime
) -> dt.timedelta:
    """Wall-clock time in which at least one session worked: the union over sessions of the stretches
    between consecutive lines that lie at most ACTIVE_GAP apart."""
    spans: list[tuple[dt.datetime, dt.datetime]] = []
    for times in sessions_times:
        inside = [t for t in times if start <= t <= end]
        spans += [(a, b) for a, b in zip(inside, inside[1:], strict=False) if b - a <= ACTIVE_GAP]
    spans.sort()
    total = dt.timedelta()
    current: tuple[dt.datetime, dt.datetime] | None = None
    for a, b in spans:
        if current and a <= current[1]:
            current = (current[0], max(current[1], b))
            continue
        if current:
            total += current[1] - current[0]
        current = (a, b)
    if current:
        total += current[1] - current[0]
    return total

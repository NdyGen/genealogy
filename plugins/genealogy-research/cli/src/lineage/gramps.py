"""Gramps Web: the API client, a Gramps-ready copy of the GEDCOM, and the open questions and blog
posts as read from the repository. Building the tree on the server is in lineage.gramps_tree.
Credentials live outside the repository, in ~/.config/lineage/gramps.env (or the file in
LINEAGE_GRAMPS_CONFIG).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from lineage import credentials, settings
from lineage.i18n import t

# Stored on the server: keys in Gramps attributes that let a later sync find what an earlier sync created.
QUESTION_KEY = "ndygen-vraag"
STATUS_KEY = "ndygen-status"
BLOG_KEY = "ndygen-blog"


class GrampsError(RuntimeError):
    pass


def config() -> dict[str, str]:
    """Credentials; the server URL is [gramps] url in lineage.toml, or LINEAGE_GRAMPS_URL."""
    values = {"LINEAGE_GRAMPS_URL": settings.current().gramps_url}
    values.update(
        credentials.load(
            "gramps.env",
            "LINEAGE_GRAMPS_",
            ("LINEAGE_GRAMPS_USER", "LINEAGE_GRAMPS_PASSWORD"),
            GrampsError,
            renamed={"GEBRUIKER": "USER", "WACHTWOORD": "PASSWORD"},
        )
    )
    if not values["LINEAGE_GRAMPS_URL"]:
        raise GrampsError(t("no Gramps Web server: set [gramps] url in lineage.toml"))
    return values


Transport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, bytes]]


def _http(method: str, url: str, data: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except OSError as exc:
        raise GrampsError(t("{method} {url}: {error}", method=method, url=url, error=exc)) from exc


class Gramps:
    def __init__(self, cfg: dict[str, str] | None = None, transport: Transport = _http):
        self.cfg = cfg or config()
        self.base = self.cfg["LINEAGE_GRAMPS_URL"].rstrip("/")
        self._transport = transport
        self._token: str | None = None

    def _login(self) -> None:
        status, body = self._transport(
            "POST",
            f"{self.base}/api/token/",
            json.dumps(
                {
                    "username": self.cfg["LINEAGE_GRAMPS_USER"],
                    "password": self.cfg["LINEAGE_GRAMPS_PASSWORD"],
                }
            ).encode(),
            {"Content-Type": "application/json"},
        )
        if status != 200:
            raise GrampsError(
                t("login refused (HTTP {status}): {message}", status=status, message=_message(body))
            )
        self._token = json.loads(body)["access_token"]

    def api(
        self,
        method: str,
        path: str,
        json_body: object = None,
        data: bytes | None = None,
        query: dict[str, object] | None = None,
        raw: bool = False,
    ) -> object:
        if self._token is None:
            self._login()
        url = f"{self.base}/api/{path.lstrip('/')}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {}
        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        elif data is not None:
            headers["Content-Type"] = "application/octet-stream"
        for attempt in range(2):
            status, body = self._transport(
                method, url, data, {**headers, "Authorization": f"Bearer {self._token}"}
            )
            # Access tokens expire after 15 minutes; long syncs outlive them.
            if status == 401 and attempt == 0:
                self._login()
                continue
            break
        if status >= 400:
            raise GrampsError(
                t(
                    "{method} {path}: HTTP {status}: {message}",
                    method=method,
                    path=path,
                    status=status,
                    message=_message(body),
                )
            )
        if raw:
            return body
        result = json.loads(body) if body.strip() else None
        if status == 202 and isinstance(result, dict) and "task" in result:
            return self.wait(result["task"]["id"])
        return result

    def wait(self, task: str, interval: float = 3.0) -> object:
        while True:
            info = self.api("GET", f"tasks/{task}")
            assert isinstance(info, dict)
            if info["state"] == "SUCCESS":
                return info.get("result_object", info.get("result"))
            if info["state"] in ("FAILURE", "REVOKED"):
                raise GrampsError(
                    t("task {task} failed: {result}", task=task, result=info.get("result"))
                )
            time.sleep(interval)


def _message(body: bytes) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        return body.decode(errors="replace")[:300]
    if isinstance(data, dict):
        error = data.get("error") or data
        if isinstance(error, dict):
            return str(error.get("message", error))
        return str(error)
    return str(data)[:300]


def status(g: Gramps) -> list[str]:
    user = g.api("GET", "users/-/")
    meta = g.api("GET", "metadata/")
    assert isinstance(user, dict) and isinstance(meta, dict)
    roles = {5: "admin", 4: "owner", 3: "editor", 2: "contributor", 1: "member", 0: "guest"}
    lines = [
        f"{g.base}: Gramps Web API {meta.get('gramps_webapi', {}).get('version', '?')}",
        t(
            "logged in as {name} ({role})",
            name=user["name"],
            role=roles.get(user["role"], user["role"]),
        ),
    ]
    lines += [f"  {kind}: {count}" for kind, count in sorted(meta["object_counts"].items())]
    return lines


# --- GEDCOM ---------------------------------------------------------------------------------

# MyHeritage tags that Gramps does not know; Gramps would park every such line in a
# "Records not imported" note on the object, thousands of notes of noise.
DROPPED_TAGS = {
    "_UPD",
    "_FILESIZE",
    "_PHOTO_RIN",
    "_POSITION",
    "_PERSONALPHOTO",
    "_PARENTRIN",
    "_PARENTPHOTO",
    "_PRIM_CUTOUT",
    "_CUTOUT",
    "_RTLSAVE",
    "_PROJECT_GUID",
    "_EXPORTED_FROM_SITE_ID",
    "_TYPE",
    "_MEDI",
    "_PLACE",
}
# Stored on the server: the text of the note that replaces a religion line on an event.
RELIGION_NOTE = "Godsdienst: "


@dataclass
class _Node:
    xref: str
    tag: str
    value: str
    children: list[_Node] = field(default_factory=list)

    def lines(self, level: int) -> Iterable[str]:
        text = " ".join(d for d in (str(level), self.xref, self.tag) if d)
        yield f"{text} {self.value}" if self.value else text
        for child in self.children:
            yield from child.lines(level + 1)

    def child(self, tag: str) -> _Node | None:
        return next((c for c in self.children if c.tag == tag), None)


def _parse(lines: list[str]) -> list[_Node]:
    roots: list[_Node] = []
    stack: list[_Node] = []
    for line in lines:
        level_text, _, rest = line.partition(" ")
        xref = ""
        if rest.startswith("@"):
            xref, _, rest = rest.partition(" ")
        tag, _, value = rest.partition(" ")
        node = _Node(xref, tag, value)
        level = int(level_text)
        del stack[level:]
        (stack[-1].children if stack else roots).append(node)
        stack.append(node)
    return roots


ADDRESS_PARTS = {"ADR1", "ADR2", "ADR3", "CITY", "STAE", "POST", "CTRY"}


def _rewrite(node: _Node, root: bool = False) -> list[_Node]:
    """Rewrite one node into what Gramps understands; returns its replacement(s)."""
    if node.tag in DROPPED_TAGS:
        return []
    children: list[_Node] = []
    moved: list[_Node] = []
    for child in node.children:
        for new in _rewrite(child):
            # Gramps drops citations on notes; one level up they still cite the same record.
            if node.tag == "NOTE" and new.tag == "SOUR" and not root:
                moved.append(new)
            else:
                children.append(new)
    node.children = children
    if node.tag == "_FORMERNAME":
        node.tag = "_AKA"
    elif node.tag == "EVEN" and (kind := node.child("TYPE")) and kind.value.lower() == "other name":
        node.tag = "NAME"
        kind.value = "aka"
    elif node.tag == "ADDR" and node.value and not node.child("ADR1"):
        # With CITY and friends present Gramps throws the free-form street away.
        if any(c.tag in ADDRESS_PARTS for c in node.children):
            # Left in ADDR as well, Gramps would warn about every comma-separated part.
            node.children.insert(0, _Node("", "ADR1", node.value))
            node.value = ""
    elif node.tag == "DSCR" and (date := node.child("DATE")):
        node.value = f"{node.value} ({date.value})"
        node.children.remove(date)
    elif node.tag == "OBJE" and (date := node.child("_DATE")):
        title = node.child("TITL")
        if title is None:
            title = _Node("", "TITL", "")
            node.children.append(title)
        title.value = f"{title.value} ({date.value})".strip()
        node.children.remove(date)
    for child in list(node.children):
        if child.tag == "RELI" and node.tag in ("BIRT", "CHR", "BAPM", "BURI", "MARR", "DEAT"):
            node.children.remove(child)
            node.children.append(_Node("", "NOTE", f"{RELIGION_NOTE}{child.value}"))
    return [node, *moved]


def for_gramps(text: str) -> str:
    """A copy of the GEDCOM that Gramps imports without noise or loss. The research file itself
    keeps the MyHeritage form."""
    # splitlines() would also break on U+2028 and the like inside note text.
    lines = [r for r in re.split(r"\r?\n", text.lstrip("\ufeff")) if r]
    out = [r for node in _parse(lines) for new in _rewrite(node, True) for r in new.lines(0)]
    return "\r\n".join(out) + "\r\n"


# --- open questions as tasks ----------------------------------------------------------------

CHOICE, ONLINE, ON_SITE, LIVING = "choice", "online", "on_site", "living"
# The chapter headings of questions.md, in the language the file is written in.
KIND_BY_HEADING = {
    "Keuzes voor de gebruiker": CHOICE,
    "Choices for the user": CHOICE,
    "Uit te zoeken met online bronnen": ONLINE,
    "To research with online sources": ONLINE,
    "Alleen ter plaatse of met scan op volle resolutie": ON_SITE,
    "On site only or with a full-resolution scan": ON_SITE,
    "Levende personen of recent (niet opzoeken)": LIVING,
    "Living persons or recent (do not look up)": LIVING,
}
EXCLUDED_HEADINGS = ("Levende personen", "Living persons", "Opgelost", "Solved")
PRIORITY = {CHOICE: "1", ONLINE: "5", ON_SITE: "9", LIVING: "9"}
# Stored on the server: the footer of every task note, which the sync cuts off again to compare the question text.
FOOTER = "\n\n(onderzoek/vragen.md, "
# Stored on the server: the status values of Gramps Web's task view.
OPEN, IN_PROGRESS, BLOCKED, DONE = "Open", "In Progress", "Blocked", "Done"


@dataclass
class Question:
    text: str
    done: bool
    chapter: str
    group: str
    ids: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return KIND_BY_HEADING.get(self.chapter, "")

    @property
    def key(self) -> str:
        # Questions grow at the end ("Aanvulling ...", "Opgelost ..."); the start stays put.
        core = re.sub(r"\s+", " ", _plain_text(self.text))[:160].lower()
        return hashlib.sha1(core.encode()).hexdigest()[:12]

    @property
    def status(self) -> str:
        if self.done:
            return DONE
        return BLOCKED if self.kind == LIVING else OPEN

    @property
    def priority(self) -> str:
        return PRIORITY.get(self.kind, "5")

    @property
    def plain_text(self) -> str:
        return _plain_text(self.text)

    @property
    def title(self) -> str:
        text = re.sub(r"\s+", " ", _plain_text(self.text))
        if len(text) <= 120:
            return text
        return text[:120].rsplit(" ", 1)[0] + " …"

    @property
    def note(self) -> str:
        heading = f"{self.chapter} / {self.group}" if self.group else self.chapter
        return f"{_plain_text(self.text)}{FOOTER}{heading})"


def _plain_text(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*|`([^`]*)`", lambda m: m.group(1) or m.group(2), text).strip()


def read_questions(text: str) -> list[Question]:
    questions: list[Question] = []
    chapter = group = ""
    for line in text.splitlines():
        if line.startswith("## "):
            chapter, group = line[3:].strip(), ""
        elif line.startswith("### "):
            group = line[4:].strip()
        else:
            m = re.match(r"- \[([ xX])\] (.+)", line)
            if m and chapter:
                content = m.group(2)
                ids = list(dict.fromkeys(re.findall(r"\b([IF]\d+)\b", content)))
                questions.append(Question(content, m.group(1) != " ", chapter, group, ids))
    return questions


# --- blog -----------------------------------------------------------------------------------

# Stored on the server: the author of every blog post and life story.
AUTHOR = "Onderzoeksassistent"


@dataclass
class Image:
    path: str
    """Where the file lives on the server, relative to the media directory."""
    file: Path
    caption: str


@dataclass
class Blogpost:
    key: str
    title: str
    author: str
    text: str
    """Markdown; styled() turns it into Gramps' styled text."""
    images: list[Image] = field(default_factory=list)
    person: str = ""
    """The person a life story is about; the post's note hangs at that person as well."""


def _front_matter_value(header: dict[str, str], *names: str) -> str:
    return next((header[n] for n in names if header.get(n)), "")


def read_blogpost(path: Path) -> Blogpost:
    """Front matter (title, author; the Dutch keys titel and auteur also work) between --- lines,
    then the text in Markdown."""
    content = path.read_text(encoding="utf-8")
    header: dict[str, str] = {}
    m = re.match(r"---\n(.*?)\n---\n", content, re.S)
    if m:
        for line in m.group(1).splitlines():
            key, _, value = line.partition(":")
            header[key.strip()] = value.strip()
        content = content[m.end() :]
    title = _front_matter_value(header, "title", "titel")
    if not title:
        raise GrampsError(t("{path}: 'title' is missing in the front matter", path=path))
    images = []

    def placeholder(m: re.Match) -> str:
        file = (path.parent / m[2]).resolve()
        if not file.is_file():
            raise GrampsError(t("{path}: image {image} does not exist", path=path, image=m[2]))
        on_server = "blog/" + file.relative_to(path.parent.resolve()).as_posix()
        caption = _LINK.sub(r"\1 (\2)", m[3] or m[1]).strip()
        images.append(Image(on_server, file, caption))
        return IMAGE_PLACE.format(len(images))

    text = _IMAGE.sub(placeholder, content)
    author = _front_matter_value(header, "author", "auteur") or AUTHOR
    return Blogpost(path.stem, title, author, text.strip(), images)


# Gramps notes hold no images: in a blog post the picture goes to the gallery and its place in the
# text gets the caption as a link to it.
IMAGE_PLACE = "{{{{image {}}}}}"
_IMAGE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)[ \t]*(?:\n\*(.+)\*[ \t]*$)?", re.M)


def read_life_story(path: Path, media: Path) -> Blogpost:
    """reports/life-stories/<ID>.md as a blog post. Images become the post's media: Gramps
    Web shows the first above the post and the rest in a gallery. An image from the tree's own
    media (the directory `media`) is the same file as on the person's page; the others are kept
    under levensverhalen/."""
    content = path.read_text(encoding="utf-8")
    first, _, text = content.partition("\n")
    if not first.startswith("# "):
        raise GrampsError(t("{path}: the first line is not a title ('# ...')", path=path))
    images = []
    for m in _IMAGE.finditer(text):
        file = (path.parent / m[2]).resolve()
        if not file.is_file():
            raise GrampsError(t("{path}: image {image} does not exist", path=path, image=m[2]))
        if file.is_relative_to(media.resolve()):
            on_server = file.relative_to(media.resolve().parent).as_posix()
        else:
            on_server = "levensverhalen/" + file.relative_to(path.parent.resolve()).as_posix()
        caption = _LINK.sub(r"\1 (\2)", m[3] or m[1]).strip()
        images.append(Image(on_server, file, caption))
    text = re.sub(r"\n{3,}", "\n\n", _IMAGE.sub("", text))
    return Blogpost(
        f"levensverhaal-{path.stem}",
        first[2:].strip(),
        AUTHOR,
        text.strip(),
        images,
        path.stem,
    )


_URL = r"(?:[^()\s]|\([^()\s]*\))+"
_LINK = re.compile(rf"\[([^\]]+)\]\(({_URL})\)")
_INLINE = re.compile(
    r"\*\*(?P<bold>.+?)\*\*"
    r"|(?<![\w*])\*(?P<italic>[^*\n]+?)\*(?![\w*])"
    rf"|\[(?P<link_text>[^\]]+)\]\((?P<url>{_URL})\)"
    r"|`(?P<code>[^`]*)`"
    r"|\b(?P<id>I\d+)\b"
)
BOLD, ITALIC, FONT_SIZE, LINK = 0, 1, 4, 8
# Gramps Web shows blog text at 23px (other notes 17px); a heading must stand out in both.
HEADING_SIZE = 28


class _Styling:
    def __init__(self, persons: dict[str, str]):
        self.persons = persons
        self.text = ""
        self.tags: dict[tuple[int, object], list[list[int]]] = {}

    def tag(self, kind: int, value: object, start: int) -> None:
        if start < len(self.text):
            self.tags.setdefault((kind, value), []).append([start, len(self.text)])

    def line(self, md: str) -> None:
        pos = 0
        for m in _INLINE.finditer(md):
            self.text += md[pos : m.start()]
            pos = m.end()
            start = len(self.text)
            if m["bold"] is not None:
                self.line(m["bold"])
                self.tag(BOLD, None, start)
            elif m["italic"] is not None:
                self.line(m["italic"])
                self.tag(ITALIC, None, start)
            elif m["url"] is not None:
                self.line(m["link_text"])
                self.tag(LINK, m["url"], start)
            elif m["code"] is not None:
                self.text += m["code"]
            else:
                self.text += m["id"]
                if m["id"] in self.persons:
                    self.tag(LINK, f"gramps://Person/handle/{self.persons[m['id']]}", start)
        self.text += md[pos:]


def styled(md: str, persons: dict[str, str] | None = None) -> dict:
    """Markdown as a Gramps StyledText, which Gramps Web shows as HTML: headings in bold,
    bold, italics, links, and a person's ID as a link to that person (ID -> handle)."""
    styling = _Styling(persons or {})
    md = re.sub(r"^-{3,}[ \t]*$", "", md, flags=re.M)
    for i, line in enumerate(re.sub(r"\n{3,}", "\n\n", md.strip()).split("\n")):
        if i:
            styling.text += "\n"
        if heading := re.match(r"#{1,6}\s+(.*)", line):
            start = len(styling.text)
            styling.line(heading[1])
            styling.tag(BOLD, None, start)
            styling.tag(FONT_SIZE, HEADING_SIZE, start)
        else:
            styling.line(line)
    return {
        "_class": "StyledText",
        "string": styling.text,
        "tags": [
            {
                "_class": "StyledTextTag",
                "name": {"_class": "StyledTextTagType", "value": kind, "string": ""},
                "value": value,
                "ranges": ranges,
            }
            for (kind, value), ranges in styling.tags.items()
        ],
    }

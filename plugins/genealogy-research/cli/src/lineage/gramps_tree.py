"""The tree on Gramps Web as a deterministic projection of data/tree.ged, research/questions.md,
research/blog/ and the life stories in reports/life-stories/. Every object gets a handle derived
from what it is (person I1, the second event of I1, ...), so an unchanged object keeps its handle and Gramps Web's restore endpoint
only touches what really changed: short locks, stable links, nothing wiped and re-imported.

Objects the user creates in Gramps Web have Gramps' own handles; they are kept, and so are
the links from our objects to them.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from . import coordinates
from .gramps import (
    BLOG_KEY,
    FOOTER,
    IMAGE_PLACE,
    QUESTION_KEY,
    STATUS_KEY,
    Blogpost,
    Gramps,
    GrampsError,
    Question,
    for_gramps,
    read_questions,
    styled,
)
from .i18n import t

GRAMPS_VERSION = "6.0.8"
INLINE_IMAGE = "\ufffc"
# Stored on the server: tag names, and the texts that blog and life-story notes are built from.
TAG_TODO, TAG_BLOG, TAG_LIFE_STORY = "ToDo", "Blog", "Levensverhaal"
IMAGE_LABEL, IMAGE_TOP_LABEL, IMAGES_HEADING, IMAGE_FALLBACK = (
    "Afbeelding",
    "Afbeelding bovenaan",
    "Afbeeldingen",
    "afbeelding",
)
VENV = Path("~/.cache/lineage/gramps-venv").expanduser()
STATE = Path("~/.cache/lineage/gramps").expanduser()
LEGACY_STATE = Path("~/.cache/ndygen/gramps").expanduser()
HELPER = Path(__file__).with_name("gramps_read.py")
# Stored on the server: every handle we make starts with this. Gramps' own handles are hexadecimal; ours can never collide with them.
OWN_PREFIX = "ndg"

ANCHOR_PREFIX = {"Person": "I", "Family": "F", "Source": "S", "Media": "O", "Repository": "R"}
LETTER = {"Event": "E", "Citation": "C", "Note": "N", "Place": "P", "Tag": "T"}


def gramps_python() -> Path:
    """Gramps needs PyGObject, which lineage's own Python lacks; the system Python has it."""
    python = VENV / "bin" / "python"
    if python.exists():
        return python
    system = shutil.which("python3", path="/usr/bin") or "/usr/bin/python3"
    if subprocess.run([system, "-c", "import gi"], capture_output=True).returncode:
        raise GrampsError(t("{system} lacks PyGObject (package python3-gi)", system=system))
    steps = [
        ["uv", "venv", "-q", "-p", system, "--system-site-packages", str(VENV)],
        ["uv", "pip", "install", "-q", "-p", str(VENV), f"gramps=={GRAMPS_VERSION}"],
    ]
    for step in steps:
        result = subprocess.run(step, capture_output=True, text=True)
        if result.returncode:
            shutil.rmtree(VENV, ignore_errors=True)
            raise GrampsError(
                t("{step}: {error}", step=" ".join(step), error=result.stderr.strip()[-500:])
            )
    return python


def _helper(*args: str) -> None:
    result = subprocess.run(
        [str(gramps_python()), "-I", str(HELPER), *args], capture_output=True, text=True
    )
    if result.returncode:
        raise GrampsError(
            t("gramps_read {step}: {error}", step=args[0], error=result.stderr.strip()[-1500:])
        )


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(r) for r in f if r.strip()]


def _write_jsonl(objects: Iterable[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for obj in objects:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_gedcom(gedcom: Path) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        # The name stays: Gramps puts the GEDCOM's file name into what it creates on import.
        (work / "stamboom.ged").write_text(
            for_gramps(gedcom.read_text(encoding="utf-8")), encoding="utf-8", newline=""
        )
        if (gedcom.parent / "media").is_dir():
            # Gramps resolves FILE relative to the GEDCOM; without the files it would add a
            # "Records not imported" note for every photo.
            (work / "media").symlink_to((gedcom.parent / "media").resolve())
        _helper("read", str(work / "stamboom.ged"), str(work / "out.jsonl"))
        objects = _read_jsonl(work / "out.jsonl")
        for obj in objects:
            if obj["_class"] == "Media":
                # Gramps records where it found the file, the temporary directory; without a
                # TITL the description is that path as well.
                for attr in ("path", "desc"):
                    if obj[attr].startswith(str(work) + os.sep):
                        obj[attr] = os.path.relpath(obj[attr], work)
                file = gedcom.parent / obj["path"]
                obj["checksum"] = _md5(file) if file.is_file() else ""
    return objects


def normalize(objects: list[dict]) -> list[dict]:
    """Complete hand-made objects with Gramps' defaults, so that what comes back from the server
    is identical to what went up."""
    if not objects:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        _write_jsonl(objects, Path(tmp) / "in.jsonl")
        _helper("normalize", str(Path(tmp) / "in.jsonl"), str(Path(tmp) / "out.jsonl"))
        return _read_jsonl(Path(tmp) / "out.jsonl")


def _md5(path: Path) -> str:
    md5 = hashlib.md5()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            md5.update(block)
    return md5.hexdigest()


def own_handle(key: str) -> str:
    return OWN_PREFIX + hashlib.sha1(key.encode()).hexdigest()[:25]


def is_own(handle: str) -> bool:
    return handle.startswith(OWN_PREFIX)


def repo_id(class_name: str, gid: str) -> str:
    """Gramps' GEDCOM import pads numeric IDs (I1 -> I0001); undo that."""
    prefix = ANCHOR_PREFIX.get(class_name, "")
    rest = gid[len(prefix) :]
    if prefix and gid.startswith(prefix) and rest.isdigit():
        return f"{prefix}{int(rest)}"
    return gid


# --- deterministic handles ------------------------------------------------------------------


def _references(value: object, handles: dict[str, dict], top: bool = True) -> Iterator[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            if not (top and k == "handle"):
                yield from _references(v, handles, False)
    elif isinstance(value, list):
        for v in value:
            yield from _references(v, handles, False)
    elif isinstance(value, str) and value in handles:
        yield value


def _anchor_key(obj: dict) -> tuple[str, str] | None:
    class_name = obj["_class"]
    if class_name == "Media":
        # Photos are inline OBJE in the GEDCOM; their Gramps IDs are a running number that
        # shifts as soon as a photo is added earlier in the file. The file name does not.
        key = f"Media:{obj['path']}"
        return key, "O-" + hashlib.sha1(key.encode()).hexdigest()[:8]
    if class_name in ANCHOR_PREFIX:
        gid = repo_id(class_name, obj["gramps_id"])
        return f"{class_name}:{gid}", gid
    if class_name == "Place":
        # Gramps makes a place per street address, all with the town as title.
        address = json.dumps([obj["place_type"], obj["alt_loc"]], sort_keys=True)
        key = f"Place:{obj['title']}|{obj['name']['value']}|{address}"
        return key, "P-" + hashlib.sha1(key.encode()).hexdigest()[:8]
    if class_name == "Tag":
        return f"Tag:{obj['name']}", ""
    return None


def stable_handles(objects: list[dict]) -> list[dict]:
    """Give every object a handle and Gramps ID derived from its place in the tree: anchors
    (people, families, sources, media, repositories, places) by their own ID, everything else by
    the anchor it hangs from and its position there."""
    handles = {o["handle"]: o for o in objects}
    keys: dict[str, str] = {}
    ids: dict[str, str] = {}
    anchors = []
    for obj in objects:
        anchor = _anchor_key(obj)
        if anchor:
            keys[obj["handle"]], ids[obj["handle"]] = anchor
            anchors.append(obj)

    def visit(obj: dict, key: str, path: str) -> None:
        counter: Counter[str] = Counter()
        for ref in _references(obj, handles):
            if ref in keys:
                continue
            kind = handles[ref]
            letter = LETTER[kind["_class"]]
            counter[letter] += 1
            child_path = f"{path}-{letter}{counter[letter]}"
            keys[ref] = f"{key}/{kind['_class']}{counter[letter]}"
            ids[ref] = child_path
            visit(kind, keys[ref], child_path)

    for obj in sorted(anchors, key=lambda o: keys[o["handle"]]):
        visit(obj, keys[obj["handle"]], ids[obj["handle"]] or keys[obj["handle"]])
    for obj in objects:
        if obj["handle"] not in keys:
            content = json.dumps({k: v for k, v in obj.items() if k not in ("handle", "change")})
            keys[obj["handle"]] = f"Los:{hashlib.sha1(content.encode()).hexdigest()}"
            ids[obj["handle"]] = f"{LETTER.get(obj['_class'], 'X')}-los-{keys[obj['handle']][4:12]}"

    new = {h: own_handle(s) for h, s in keys.items()}

    def replace(value: object) -> object:
        if isinstance(value, dict):
            return {k: replace(v) for k, v in value.items()}
        if isinstance(value, list):
            return [replace(v) for v in value]
        if isinstance(value, str) and value in new:
            return new[value]
        return value

    out: dict[str, dict] = {}
    for obj in objects:
        copy_ = replace(obj)
        assert isinstance(copy_, dict)
        if "gramps_id" in copy_ and ids[obj["handle"]]:
            copy_["gramps_id"] = ids[obj["handle"]]
        earlier = out.get(copy_["handle"])
        if earlier is None:
            out[copy_["handle"]] = copy_
        elif _without_time(earlier) != _without_time(copy_):
            raise GrampsError(t("two different objects with key {key}", key=keys[obj["handle"]]))
    return list(out.values())


# --- tasks and blog -------------------------------------------------------------------------


def _styled_text(text: str) -> dict:
    return {"_class": "StyledText", "string": text, "tags": []}


def _attributes(pairs: Iterable[tuple[str, str]]) -> list[dict]:
    return [
        {
            "_class": "SrcAttribute",
            "type": {"_class": "SrcAttributeType", "value": 0, "string": t},
            "value": w,
        }
        for t, w in pairs
    ]


def _tag(name: str, existing: dict[str, str]) -> tuple[str, dict | None]:
    """A tag the user already made in Gramps Web (the task view creates 'ToDo') is reused."""
    if name in existing:
        return existing[name], None
    handle = own_handle(f"Tag:{name}")
    return handle, {
        "_class": "Tag",
        "handle": handle,
        "name": name,
        "color": "#000000000000",
        "priority": 0,
    }


def choose_questions(questions: list[Question]) -> dict[str, Question]:
    """One task per question: a question that was copied and extended (an answer or a follow-up
    appended) counts once, in its longest version."""
    chosen: dict[str, Question] = {}
    for v in questions:
        text = v.plain_text
        key = next(
            (
                s
                for s, earlier in chosen.items()
                if text.startswith(earlier.plain_text) or earlier.plain_text.startswith(text)
            ),
            v.key,
        )
        if key not in chosen or len(v.text) > len(chosen[key].text):
            chosen[key] = v
    return chosen


def match_existing_tasks(
    chosen: dict[str, Question], server: dict[str, dict]
) -> dict[str, Question]:
    """A question whose text changed keeps the task that is already on the server, with the user's status
    and comments, instead of getting a new one: an answer appended, or the opening rewritten (matched
    on the whole text, among questions about the same people)."""
    on_server: dict[str, str] = {}
    for obj in server.values():
        key = _attribute(obj, QUESTION_KEY) if obj.get("_class") == "Source" else None
        if key and is_own(obj["handle"]) and obj.get("note_list"):
            note = server.get(obj["note_list"][0], {}).get("text", {})
            on_server[key] = note.get("string", "").split(FOOTER)[0]
    out: dict[str, Question] = {}
    for key, v in chosen.items():
        if key not in on_server:
            key = next(
                (
                    s
                    for s, text in on_server.items()
                    if s not in chosen and s not in out and text and v.plain_text.startswith(text)
                ),
                key,
            )
        out[key] = v
    # A question whose opening was rewritten (a status put in front, a sentence turned around) gets a new
    # key too; without this its task would be deleted and made again, losing the user's status and comments.
    orphans = {s: t for s, t in on_server.items() if s not in out and t}
    new = [s for s in out if s not in on_server]
    pairs = []
    for s_new in new:
        text = out[s_new].plain_text
        ids = _ids(text)
        for s_old, oud in orphans.items():
            ids_old = _ids(oud)
            if ids and ids_old and not ids & ids_old:
                continue  # about other people: never the same question
            threshold = 0.5 if ids & ids_old else 0.75
            similarity = _similarity(oud, text, threshold)
            if similarity >= threshold:
                pairs.append((similarity, s_new, s_old))
    for _, s_new, s_old in sorted(pairs, reverse=True):
        if s_new in out and s_old not in out:
            out[s_old] = out.pop(s_new)
    return out


def _similarity(a: str, b: str, threshold: float = 0.0) -> float:
    # The whole question, not its opening: that is exactly the part that was rewritten.
    def short(t: str) -> str:
        return re.sub(r"\s+", " ", t).lower()[:2000]

    matcher = difflib.SequenceMatcher(None, short(a), short(b), autojunk=False)
    # The cheap upper bounds rule out almost every pair before the expensive comparison.
    if matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold:
        return 0.0
    return matcher.ratio()


def _ids(text: str) -> set[str]:
    return set(re.findall(r"\b[IF]\d+\b", text))


def read_coordinates(path: Path) -> dict[tuple[str, str], tuple[str, str]]:
    """(place as in the GEDCOM, address or "") -> (lat, long)."""
    return {
        k: (r["lat"], r["lon"]) for k, r in coordinates.read(path).items() if r["lat"] and r["lon"]
    }


def set_coordinates(
    objects: list[dict], known: dict[tuple[str, str], tuple[str, str]]
) -> list[str]:
    """An address without coordinates of its own gets those of its place, so it is still on
    the map. Returns the places that have none at all."""
    without = set()
    for obj in objects:
        if obj["_class"] != "Place":
            continue
        address = (obj.get("alt_loc") or [{}])[0].get("street", "")
        point = known.get((obj["title"], address)) or known.get((obj["title"], ""))
        if point:
            obj["lat"], obj["long"] = point
        else:
            without.add(obj["title"])
    return sorted(without)


@dataclass
class Report:
    tasks: Counter[str] = field(default_factory=Counter)
    manual_status: list[str] = field(default_factory=list)
    unknown_ids: set[str] = field(default_factory=set)
    duplicate_questions: int = 0
    changed_in_gramps: list[str] = field(default_factory=list)
    foreign: Counter[str] = field(default_factory=Counter)
    loose: int = 0
    without_coordinates: list[str] = field(default_factory=list)
    coordinates_table: str = ""
    summary: dict = field(default_factory=dict)
    media: str = ""
    # Kept edits keep the fingerprint from before the edit, so they are reported again next
    # time, until the GEDCOM has caught up.
    kept: dict[str, str] = field(default_factory=dict)

    def lines(self) -> list[str]:
        out = []
        if self.summary:
            for kind in ("to_add", "to_update", "to_delete"):
                count = {k: v for k, v in self.summary.get(kind, {}).items() if v}
                label = {
                    "to_add": t("new: {count}"),
                    "to_update": t("changed: {count}"),
                    "to_delete": t("removed: {count}"),
                }[kind]
                out.append(label.format(count=count or t("nothing")))
        out.append(
            t("tasks: {tasks}", tasks=", ".join(f"{n} {s}" for s, n in sorted(self.tasks.items())))
        )
        if self.duplicate_questions:
            out.append(
                t(
                    "duplicate in questions.md (longest version taken): {count}",
                    count=self.duplicate_questions,
                )
            )
        if self.unknown_ids:
            out.append(
                t(
                    "questions mention IDs that are not in the tree: {ids}",
                    ids=", ".join(sorted(self.unknown_ids)),
                )
            )
        if self.manual_status:
            out.append(t("status set by hand in Gramps Web, stays:"))
            out += [f"  {item}" for item in self.manual_status]
        if self.changed_in_gramps:
            out.append(
                t(
                    "changed in Gramps Web since last time, that version stays (copy it into the GEDCOM):"
                )
            )
            out += [f"  {item}" for item in self.changed_in_gramps]
        if self.foreign:
            out.append(
                t(
                    "own objects in Gramps Web, stay: {objects}",
                    objects=", ".join(f"{n} {k}" for k, n in sorted(self.foreign.items())),
                )
            )
        if self.loose:
            out.append(t("objects without a reference: {count}", count=self.loose))
        if self.without_coordinates:
            out.append(
                t(
                    "places without coordinates (add to {table}): {places}",
                    table=self.coordinates_table,
                    places="; ".join(self.without_coordinates),
                )
            )
        if self.media:
            out.append(self.media)
        return out


def task_objects(
    chosen: dict[str, Question],
    handles: dict[str, str],
    todo: str,
    server: dict[str, dict],
    report: Report,
) -> tuple[list[dict], dict[str, list[str]]]:
    """Tasks the way Gramps Web's task view makes them: a source tagged ToDo with Status and
    Priority attributes and a To Do note. Returns the objects and, per person or family handle,
    the notes to hang there."""
    objects: list[dict] = []
    links: dict[str, list[str]] = {}
    for key, v in sorted(chosen.items()):
        source_handle = own_handle(f"Vraag:{key}")
        note_handle = own_handle(f"VraagNotitie:{key}")
        status = v.status
        previous = server.get(source_handle)
        if previous:
            on_server = _attribute(previous, "Status")
            if on_server and on_server != _attribute(previous, STATUS_KEY):
                report.manual_status.append(f"{v.title} ({on_server})")
                gramps_status = on_server
            else:
                gramps_status = status
        else:
            if v.done:
                continue
            gramps_status = status
        report.tasks[gramps_status] += 1
        objects.append(
            {
                "_class": "Note",
                "handle": note_handle,
                "gramps_id": f"V-{key}-N",
                "type": {"_class": "NoteType", "value": 25, "string": ""},
                "text": _styled_text(v.note),
                "tag_list": [todo],
            }
        )
        objects.append(
            {
                "_class": "Source",
                "handle": source_handle,
                "gramps_id": f"V-{key}",
                "title": v.title,
                "note_list": [note_handle],
                "tag_list": [todo],
                "attribute_list": _attributes(
                    [
                        ("Priority", v.priority),
                        ("Status", gramps_status),
                        (QUESTION_KEY, key),
                        (
                            STATUS_KEY,
                            status
                            if gramps_status == status
                            else _attribute(previous or {}, STATUS_KEY) or status,
                        ),
                    ]
                ),
            }
        )
        for gid in v.ids:
            if gid in handles:
                links.setdefault(handles[gid], []).append(note_handle)
            else:
                report.unknown_ids.add(gid)
    return objects, links


def blog_objects(
    posts: list[Blogpost],
    tags: dict[str, str],
    persons: dict[str, str],
    media: dict[str, str],
) -> tuple[list[dict], dict[str, list[str]], dict[str, list[str]]]:
    """Blog posts the way Gramps Web shows them: a source tagged Blog with the text as its note
    and the images as its media. A life story is no blog post (a choice of the first project): only a
    note tagged with the life-story tag at its person, ending in links to its images, which join the
    person's own media. `media` maps checksums to media handles: Gramps Web stores a file once
    per checksum, so the same picture in two stories, or a photo of the tree itself, is one
    media object. Returns the objects and, per person handle, the notes and media to hang there."""
    objects: list[dict] = []
    notes: dict[str, list[str]] = {}
    images: dict[str, list[str]] = {}
    for post in posts:
        refs = []
        for i, image in enumerate(post.images, 1):
            checksum = _md5(image.file)
            handle = media.get(checksum)
            if handle is None:
                handle = own_handle(f"Media:{checksum}")
                media[checksum] = handle
                objects.append(
                    {
                        "_class": "Media",
                        "handle": handle,
                        "gramps_id": f"B-{post.key}-O{i}",
                        "path": image.path,
                        "mime": mimetypes.guess_type(image.path)[0] or "",
                        "desc": image.caption,
                        "checksum": checksum,
                    }
                )
            refs.append((handle, image.caption))
        note = own_handle(f"BlogNotitie:{post.key}")
        story = bool(post.person)
        text = post.text
        for i, (h, b) in enumerate(refs, 1):
            if story:
                spot = f"*▸ {IMAGE_LABEL}: [{b or IMAGE_FALLBACK}](gramps://Media/handle/{h})*"
            elif i == 1:
                # Gramps Web already shows the first picture above a blog post.
                spot = f"*▸ {IMAGE_TOP_LABEL}: [{b or IMAGE_FALLBACK}](gramps://Media/handle/{h})*"
            else:
                # A link whose whole text is U+FFFC is what Gramps Web shows as an inline picture.
                spot = f"[{INLINE_IMAGE}](gramps://Media/handle/{h})"
            text = text.replace(IMAGE_PLACE.format(i), spot)
        if story:
            text = f"# {post.title}\n\n{text}"
            if refs:
                text += f"\n\n## {IMAGES_HEADING}\n" + "\n".join(
                    f"- [{b or IMAGE_FALLBACK}](gramps://Media/handle/{h})" for h, b in refs
                )
        objects.append(
            {
                "_class": "Note",
                "handle": note,
                "gramps_id": f"B-{post.key}-N",
                "type": {"_class": "NoteType", "value": 1, "string": ""},
                "text": styled(text, persons),
                "tag_list": [tags[TAG_LIFE_STORY if story else TAG_BLOG]],
            }
        )
        if story:
            if post.person in persons:
                notes.setdefault(persons[post.person], []).append(note)
                images.setdefault(persons[post.person], []).extend(h for h, _ in refs)
            continue
        objects.append(
            {
                "_class": "Source",
                "handle": own_handle(f"Blog:{post.key}"),
                "gramps_id": f"B-{post.key}",
                "title": post.title,
                "author": post.author,
                "note_list": [note],
                "media_list": [{"_class": "MediaRef", "ref": h} for h, _ in refs],
                "tag_list": [tags["Blog"]],
                "attribute_list": _attributes([(BLOG_KEY, post.key)]),
            }
        )
    return objects, notes, images


def _attribute(obj: dict, kind: str) -> str | None:
    for a in obj.get("attribute_list", []):
        t = a.get("type")
        if (t.get("string") if isinstance(t, dict) else t) == kind:
            return a.get("value")
    return None


# --- merging with what is on the server ------------------------------------------------------


def _without_time(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: _without_time(v) for k, v in obj.items() if k != "change"}
    if isinstance(obj, list):
        return [_without_time(v) for v in obj]
    return obj


def _is_foreign(x: object) -> bool:
    if isinstance(x, str):
        return len(x) >= 20 and not is_own(x)
    return isinstance(x, dict) and isinstance(x.get("ref"), str) and not is_own(x["ref"])


def _without_foreign(obj: dict) -> dict:
    return {
        k: [x for x in v if not _is_foreign(x)] if isinstance(v, list) else v
        for k, v in obj.items()
    }


def gramps_equal(live: object, new: object) -> bool:
    """Gramps' own comparison in a restore (gramps.gen.merge.diff.diff_items): only the fields
    the live object has count, the change time not at all."""
    if isinstance(live, dict) and isinstance(new, dict):
        return all(k == "change" or gramps_equal(v, new.get(k)) for k, v in live.items())
    if isinstance(live, list) and isinstance(new, list):
        return len(live) == len(new) and all(map(gramps_equal, live, new))
    return live == new


def _overwritten(obj: dict, overwrite: frozenset[str]) -> bool:
    gid = obj.get("gramps_id", "")
    return gid.split("-")[0] in overwrite


def new_state(server: list[dict], report: Report) -> dict[str, str]:
    state = {o["handle"]: fingerprint(o) for o in server if is_own(o["handle"])}
    return {**state, **report.kept}


def fingerprint(obj: dict) -> str:
    """Of our own content only: a link the user adds to their own note is not a change to the person."""
    content = _without_time(_without_foreign(obj))
    return hashlib.sha1(json.dumps(content, sort_keys=True).encode()).hexdigest()


def _foreign_references(server_obj: dict, own_obj: dict) -> dict:
    """Keep the links the user made from our objects to their own (a note on a person, a tag)."""
    out = dict(own_obj)
    for k, v in server_obj.items():
        if not isinstance(v, list) or k not in out:
            continue
        extra = [x for x in v if _is_foreign(x)]
        if extra:
            out[k] = [*out[k], *[x for x in extra if x not in out[k]]]
    return out


def assemble(
    gedcom: Path,
    questions_text: str,
    posts: list[Blogpost],
    server: list[dict],
    previous_state: dict[str, str] | None = None,
    overwrite: frozenset[str] = frozenset(),
) -> tuple[list[dict], Report]:
    """`overwrite`: IDs (I731, with its events and citations I731-…) where our version wins over
    an edit in Gramps Web."""
    report = Report()
    server_by_handle = {o["handle"]: o for o in server}
    tree = stable_handles(read_gedcom(gedcom))
    table = coordinates.table_for(gedcom)
    report.coordinates_table = os.path.relpath(table)
    report.without_coordinates = set_coordinates(tree, read_coordinates(table))

    foreign_tags = {
        o["name"]: o["handle"] for o in server if o["_class"] == "Tag" and not is_own(o["handle"])
    }
    tags, new_tags = {}, []
    for name in (TAG_TODO, TAG_BLOG, TAG_LIFE_STORY):
        tags[name], new = _tag(name, foreign_tags)
        if new:
            new_tags.append(new)

    handles = {o["gramps_id"]: o["handle"] for o in tree if o["_class"] in ("Person", "Family")}
    questions = read_questions(questions_text)
    chosen = choose_questions(questions)
    report.duplicate_questions = len(questions) - len(chosen)
    chosen = match_existing_tasks(chosen, server_by_handle)
    tasks, links = task_objects(chosen, handles, tags[TAG_TODO], server_by_handle, report)
    persons = {o["gramps_id"]: o["handle"] for o in tree if o["_class"] == "Person"}
    media = {o["checksum"]: o["handle"] for o in tree if o["_class"] == "Media" and o["checksum"]}
    blog, stories, story_media = blog_objects(posts, tags, persons, media)
    for obj in tree:
        for k in (stories, links):
            if obj["handle"] in k:
                obj["note_list"] = [*obj["note_list"], *k[obj["handle"]]]
        if obj["handle"] in story_media:
            already = {r["ref"] for r in obj.get("media_list", [])}
            extra = [h for h in dict.fromkeys(story_media[obj["handle"]]) if h not in already]
            obj["media_list"] = [
                *obj.get("media_list", []),
                *({"_class": "MediaRef", "ref": h} for h in extra),
            ]
    with_story_media = normalize([o for o in tree if o["handle"] in story_media])
    tree = [*(o for o in tree if o["handle"] not in story_media), *with_story_media]

    own_objects = new_tags + tasks + blog
    objects = tree + normalize(own_objects)
    report.loose = sum(1 for o in objects if o.get("gramps_id", "").split("-")[1:2] == ["los"])

    out = []
    for obj in objects:
        on_server = server_by_handle.get(obj["handle"])
        if on_server is not None:
            earlier = (previous_state or {}).get(obj["handle"])
            edited = earlier not in (None, fingerprint(on_server))
            if edited and not gramps_equal(on_server, obj) and not _overwritten(obj, overwrite):
                report.changed_in_gramps.append(
                    f"{obj['_class']} {obj.get('gramps_id', obj['handle'])}"
                )
                assert earlier is not None
                report.kept[obj["handle"]] = earlier
                out.append(on_server)
                continue
            obj = _foreign_references(on_server, obj)
        out.append(obj)
    eigen = {o["handle"] for o in out}
    for obj in server:
        if not is_own(obj["handle"]) and obj["handle"] not in eigen:
            report.foreign[obj["_class"]] += 1
            out.append(obj)
    return out, report


# --- talking to the server ------------------------------------------------------------------


def export(g: Gramps) -> list[dict]:
    data = g.api(
        "GET", "exporters/jsonl/file", query={"reference": "true", "compress": "false"}, raw=True
    )
    assert isinstance(data, bytes)
    return [json.loads(r) for r in data.decode("utf-8").splitlines() if r.strip()]


def restore(g: Gramps, objects: list[dict], dry_run: bool, empty: bool = False) -> dict:
    """Restore applies the difference object by object; into an empty tree the plain import is
    far faster (one batch transaction) and ends in the same state."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "boom.jsonl"
        _write_jsonl(objects, path)
        if empty and not dry_run:
            g.api("POST", "importers/jsonl/file", data=path.read_bytes())
            return {"to_add": dict(Counter(_PLURAL[o["_class"]] for o in objects))}
        result = g.api(
            "POST",
            "importers/jsonl/file/restore",
            data=path.read_bytes(),
            query={"dry_run": "true" if dry_run else "false"},
        )
    assert isinstance(result, dict)
    return result


_PLURAL = {
    "Person": "people",
    "Family": "families",
    "Event": "events",
    "Place": "places",
    "Citation": "citations",
    "Source": "sources",
    "Repository": "repositories",
    "Media": "media",
    "Note": "notes",
    "Tag": "tags",
}


def upload_media(g: Gramps, files: dict[str, Path], objects: list[dict], server: list[dict]) -> str:
    """Only files the server cannot have: new media or a changed checksum. `files` maps a
    media path to the local file."""
    known = {(o["path"], o.get("checksum")) for o in server if o["_class"] == "Media"}
    paths = sorted(
        {
            o["path"]
            for o in objects
            if o["_class"] == "Media"
            and o.get("checksum")
            and (o["path"], o["checksum"]) not in known
        }
    )
    if not paths:
        return t("media: nothing new")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "media.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as z:
            for p in paths:
                z.write(files[p], p)
        result = g.api("POST", "media/archive/upload/zip", data=archive.read_bytes())
    return t("media: {count} files uploaded ({result})", count=len(paths), result=result)


def _state_name(g: Gramps) -> str:
    return g.base.split("://", 1)[-1].replace("/", "_").replace(":", "_") + ".json"


def _read_state(g: Gramps) -> dict[str, str] | None:
    """Without the saved fingerprints an edit made in Gramps Web is not recognized and our version
    overwrites it; so the state from before the rename counts until a new one is written."""
    for folder in (STATE, LEGACY_STATE):
        path = folder / _state_name(g)
        if path.exists():
            return json.loads(path.read_text())
    return None


def sync(
    g: Gramps,
    gedcom: Path,
    questions_text: str,
    posts: list[Blogpost],
    dry_run: bool,
    overwrite: frozenset[str] = frozenset(),
) -> Report:
    server = export(g)
    objects, report = assemble(gedcom, questions_text, posts, server, _read_state(g), overwrite)
    report.summary = restore(g, objects, dry_run, empty=not server)
    if not dry_run:
        files = {o["path"]: gedcom.parent / o["path"] for o in objects if o["_class"] == "Media"}
        files |= {a.path: a.file for post in posts for a in post.images}
        report.media = upload_media(g, files, objects, server)
        state = STATE / _state_name(g)
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(new_state(export(g), report)))
    return report

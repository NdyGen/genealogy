"""Runs under a Python with the Gramps library (see lineage.gramps_tree.gramps_python), not inside
lineage's own environment.

    read <file.ged> <out.jsonl>          the GEDCOM as Gramps objects, one JSON object per line
    normalize <in.jsonl> <out.jsonl>     partial objects completed with Gramps' defaults

Output goes to a file because Gramps prints plugin messages on stdout.
"""

import json
import sys

from gramps.gen.lib.json_utils import object_to_string, string_to_object


def read(path: str, out: str) -> None:
    from gramps.gen.db.utils import import_as_dict
    from gramps.gen.user import User

    db = import_as_dict(path, User())
    if db is None:
        sys.exit(f"Gramps could not import {path}")
    with open(out, "w", encoding="utf-8") as f:
        for kind in (
            "notes",
            "events",
            "people",
            "families",
            "repositories",
            "places",
            "sources",
            "citations",
            "media",
            "tags",
        ):
            for obj in getattr(db, f"iter_{kind}")():
                f.write(object_to_string(obj) + "\n")


def _defaults(class_name: str) -> dict | None:
    import gramps.gen.lib as lib

    maker = getattr(lib, class_name, None)
    return json.loads(object_to_string(maker())) if maker else None


def _fill_in(given, defaults=None):
    """Gramps' JSON reader does not fill in missing fields of nested parts (an attribute
    without 'private'); the server's would, and the copies would differ."""
    if isinstance(given, list):
        return [_fill_in(v) for v in given]
    if not isinstance(given, dict):
        return given
    if defaults is None and "_class" in given:
        defaults = _defaults(given["_class"])
    defaults = defaults if isinstance(defaults, dict) else {}
    return {
        **defaults,
        **{k: _fill_in(v, defaults.get(k)) for k, v in given.items()},
    }


def normalize(source: str, out: str) -> None:
    with open(source, encoding="utf-8") as f, open(out, "w", encoding="utf-8") as u:
        for line in f:
            if not line.strip():
                continue
            given = json.loads(line)
            obj = string_to_object(json.dumps(_fill_in(given)))
            u.write(object_to_string(obj) + "\n")


if __name__ == "__main__":
    if sys.argv[1:2] == ["read"]:
        read(sys.argv[2], sys.argv[3])
    elif sys.argv[1:2] == ["normalize"]:
        normalize(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)

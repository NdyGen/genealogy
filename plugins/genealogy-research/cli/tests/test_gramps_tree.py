import copy
import random

import pytest

from lineage import gramps, gramps_tree
from lineage.gramps_tree import fingerprint, is_own, own_handle


def _h():
    return f"{random.getrandbits(112):028x}"


def tree(extra_event: bool = False):
    """A person with an event (with a citation and a place), a citation of their own, and a
    source, the way Gramps' GEDCOM import hands them out: random handles, padded IDs."""
    h = {k: _h() for k in ("p", "e", "e2", "c1", "c2", "pl", "s", "q", "qe")}
    objects = [
        {
            "_class": "Person",
            "handle": h["p"],
            "gramps_id": "I0001",
            "citation_list": [h["c1"]],
            "note_list": [],
            "event_ref_list": [{"_class": "EventRef", "ref": h["e"]}],
        },
        {
            "_class": "Event",
            "handle": h["e"],
            "gramps_id": "E0000",
            "citation_list": [h["c2"]],
            "place": h["pl"],
        },
        {"_class": "Citation", "handle": h["c1"], "gramps_id": "C0000", "source_handle": h["s"]},
        {"_class": "Citation", "handle": h["c2"], "gramps_id": "C0001", "source_handle": h["s"]},
        {
            "_class": "Place",
            "handle": h["pl"],
            "gramps_id": "P0000",
            "title": "Exampleton",
            "name": {"value": "Exampleton"},
            "place_type": {"value": -1, "string": ""},
            "alt_loc": [],
        },
        {"_class": "Source", "handle": h["s"], "gramps_id": "S0007", "title": "Record"},
        {
            "_class": "Person",
            "handle": h["q"],
            "gramps_id": "I1275007",
            "event_ref_list": [{"_class": "EventRef", "ref": h["qe"]}],
            "note_list": [],
        },
        {"_class": "Event", "handle": h["qe"], "gramps_id": "E0002", "citation_list": []},
    ]
    if extra_event:
        objects[6]["event_ref_list"].insert(0, {"_class": "EventRef", "ref": h["e2"]})
        objects.append(
            {"_class": "Event", "handle": h["e2"], "gramps_id": "E0003", "citation_list": []}
        )
    random.shuffle(objects)
    return objects


def per_id(objects):
    return {o["gramps_id"]: o for o in objects if "gramps_id" in o}


def test_repo_id():
    assert gramps_tree.repo_id("Person", "I0001") == "I1"
    assert gramps_tree.repo_id("Family", "F0045") == "F45"
    assert gramps_tree.repo_id("Person", "I1275007") == "I1275007"
    assert gramps_tree.repo_id("Source", "OA02357558") == "OA02357558"
    assert gramps_tree.repo_id("Event", "E0001") == "E0001"


def test_stable_handles_follow_the_place_in_the_tree():
    out = per_id(gramps_tree.stable_handles(tree()))
    assert set(out) >= {"I1", "I1-C1", "I1-E1", "I1-E1-C1", "S7", "I1275007-E1"}
    person = out["I1"]
    assert person["handle"] == own_handle("Person:I1")
    assert person["event_ref_list"][0]["ref"] == out["I1-E1"]["handle"]
    assert out["I1-E1-C1"]["source_handle"] == out["S7"]["handle"]
    assert out["I1-E1"]["place"].startswith("ndg")
    assert all(is_own(o["handle"]) for o in out.values())


def test_stable_handles_are_repeatable():
    first = sorted(gramps_tree.stable_handles(tree()), key=lambda o: o["handle"])
    second = sorted(gramps_tree.stable_handles(tree()), key=lambda o: o["handle"])
    assert first == second


def test_new_event_only_touches_that_person():
    before = per_id(gramps_tree.stable_handles(tree()))
    after = per_id(gramps_tree.stable_handles(tree(extra_event=True)))
    for gid in ("I1", "I1-E1", "I1-E1-C1", "I1-C1", "S7"):
        assert before[gid] == after[gid]
    assert "I1275007-E2" in after


def test_photo_keeps_its_id_when_one_is_added_before_it():
    def with_photos(*paths):
        objects = tree()
        for i, path in enumerate(paths):
            objects.append(
                {"_class": "Media", "handle": _h(), "gramps_id": f"O{i:04d}", "path": path}
            )
        return {o["path"]: o for o in gramps_tree.stable_handles(objects) if o["_class"] == "Media"}

    before = with_photos("media/b.jpg")
    after = with_photos("media/a.jpg", "media/b.jpg")
    assert before["media/b.jpg"] == after["media/b.jpg"]


def test_equal_places_become_one_object():
    objects = tree()
    place = next(o for o in objects if o["_class"] == "Place")
    second = {**copy.deepcopy(place), "handle": _h(), "gramps_id": "P0001"}
    objects.append(second)
    event = next(o for o in objects if o["gramps_id"] == "E0002")
    event["place"] = second["handle"]
    out = gramps_tree.stable_handles(objects)
    places = [o for o in out if o["_class"] == "Place"]
    assert len(places) == 1
    assert per_id(out)["I1275007-E1"]["place"] == places[0]["handle"]


def test_place_with_another_address_stays_apart():
    objects = tree()
    place = next(o for o in objects if o["_class"] == "Place")
    objects.append({**copy.deepcopy(place), "handle": _h(), "alt_loc": [{"street": "Markt 1"}]})
    assert len([o for o in gramps_tree.stable_handles(objects) if o["_class"] == "Place"]) == 2


def test_collision_with_other_content_stops():
    objects = tree()
    objects.append({"_class": "Source", "handle": _h(), "gramps_id": "S0007", "title": "Other"})
    with pytest.raises(gramps.GrampsError, match="Source:S7"):
        gramps_tree.stable_handles(objects)


QUESTIONS = """## Uit te zoeken met online bronnen

- [ ] I1 Peter: doop niet gevonden
- [ ] I1 Peter: doop niet gevonden Vervolg: nog niet in Exampleton.
- [x] I9 Piet: overlijden gevonden
- [ ] I2 Jan en I404: onbekend
"""


def test_choose_questions_takes_the_longest_version():
    chosen = gramps_tree.choose_questions(gramps.read_questions(QUESTIONS))
    assert len(chosen) == 3
    assert any("Vervolg" in v.text for v in chosen.values())


def test_tasks_and_links():
    chosen = gramps_tree.choose_questions(gramps.read_questions(QUESTIONS))
    report = gramps_tree.Report()
    objects, links = gramps_tree.task_objects(
        chosen, {"I1": "hI1", "I2": "hI2"}, "todo", {}, report
    )
    sources = [o for o in objects if o["_class"] == "Source"]
    assert len(sources) == 2
    assert all(o["tag_list"] == ["todo"] for o in objects)
    note = next(o for o in objects if o["_class"] == "Note" and "Peter" in o["text"]["string"])
    assert note["type"]["value"] == 25
    assert links["hI1"] == [note["handle"]]
    assert report.unknown_ids == {"I404"}
    assert report.tasks == {"Open": 2}


def test_closed_question_with_existing_task_becomes_done():
    text = "## Opgelost\n\n- [x] I9 Piet: overlijden gevonden\n"
    chosen = gramps_tree.choose_questions(gramps.read_questions(text))
    key = next(iter(chosen))
    server = {
        own_handle(f"Vraag:{key}"): {
            "attribute_list": gramps_tree._attributes(
                [("Status", "Open"), (gramps.STATUS_KEY, "Open")]
            )
        }
    }
    objects, _ = gramps_tree.task_objects(chosen, {}, "todo", server, gramps_tree.Report())
    source = next(o for o in objects if o["_class"] == "Source")
    assert gramps_tree._attribute(source, "Status") == "Done"


def test_manual_status_stays():
    chosen = gramps_tree.choose_questions(gramps.read_questions(QUESTIONS))
    key = next(s for s, v in chosen.items() if "Peter" in v.text)
    server = {
        own_handle(f"Vraag:{key}"): {
            "attribute_list": gramps_tree._attributes(
                [("Status", "In Progress"), (gramps.STATUS_KEY, "Open")]
            )
        }
    }
    report = gramps_tree.Report()
    objects, _ = gramps_tree.task_objects(chosen, {}, "todo", server, report)
    source = next(o for o in objects if o["handle"] == own_handle(f"Vraag:{key}"))
    assert gramps_tree._attribute(source, "Status") == "In Progress"
    assert gramps_tree._attribute(source, gramps.STATUS_KEY) == "Open"
    assert len(report.manual_status) == 1


def test_server_identifiers_are_unchanged():
    chosen = gramps_tree.choose_questions(gramps.read_questions(QUESTIONS))
    key = next(s for s, v in chosen.items() if "Peter" in v.text)
    objects, _ = gramps_tree.task_objects(chosen, {}, "todo", {}, gramps_tree.Report())
    source = next(o for o in objects if o["handle"] == own_handle(f"Vraag:{key}"))
    assert source["gramps_id"] == f"V-{key}"
    assert gramps_tree._attribute(source, "ndygen-vraag") == key
    note = next(o for o in objects if o["handle"] == own_handle(f"VraagNotitie:{key}"))
    assert note["gramps_id"] == f"V-{key}-N"
    assert note["text"]["string"].endswith("\n\n(onderzoek/vragen.md, Uit te zoeken met online bronnen)")
    assert (gramps_tree.OWN_PREFIX, gramps_tree.TAG_TODO, gramps_tree.TAG_BLOG) == (
        "ndg",
        "ToDo",
        "Blog",
    )
    assert gramps_tree.TAG_LIFE_STORY == "Levensverhaal"


@pytest.fixture
def without_gramps(monkeypatch):
    """assemble without the Gramps library: the tree comes from tree()."""
    monkeypatch.setattr(gramps_tree, "read_gedcom", lambda _path: tree())
    monkeypatch.setattr(gramps_tree, "normalize", lambda objects: objects)


def test_assemble_keeps_what_andy_made(without_gramps, tmp_path):
    first, _ = gramps_tree.assemble(tmp_path / "x.ged", QUESTIONS, [], [])
    person = next(o for o in first if o["handle"] == own_handle("Person:I1"))
    andy = {"_class": "Note", "handle": "f" * 28, "gramps_id": "N0001", "text": "own"}
    server = copy.deepcopy(first) + [andy]
    server_person = next(o for o in server if o["handle"] == person["handle"])
    server_person["note_list"] = [*server_person["note_list"], andy["handle"]]

    second, report = gramps_tree.assemble(tmp_path / "x.ged", QUESTIONS, [], server)
    assert andy in second
    new_person = next(o for o in second if o["handle"] == person["handle"])
    assert andy["handle"] in new_person["note_list"]
    assert report.foreign == {"Note": 1}


def test_task_hangs_at_person(without_gramps, tmp_path):
    objects, _ = gramps_tree.assemble(tmp_path / "x.ged", QUESTIONS, [], [])
    person = next(o for o in objects if o["handle"] == own_handle("Person:I1"))
    notes = {o["handle"]: o for o in objects if o["_class"] == "Note"}
    assert [notes[h]["type"]["value"] for h in person["note_list"]] == [25]


def test_life_story_is_only_a_note_at_the_person(without_gramps, tmp_path):
    (tmp_path / "church.jpg").write_bytes(b"jpg")
    post = gramps.Blogpost(
        "levensverhaal-I1",
        "Jan (1800-1850)",
        gramps.AUTHOR,
        "Son of (I1).",
        [gramps.Image("levensverhalen/church.jpg", tmp_path / "church.jpg", "The church")],
        "I1",
    )
    objects, _ = gramps_tree.assemble(tmp_path / "x.ged", QUESTIONS, [post], [])
    by_handle = {o["handle"]: o for o in objects}
    assert own_handle("Blog:levensverhaal-I1") not in by_handle
    person = by_handle[own_handle("Person:I1")]
    note = by_handle[own_handle("BlogNotitie:levensverhaal-I1")]
    assert note["handle"] in person["note_list"]
    assert {by_handle[h]["name"] for h in note["tag_list"]} == {"Levensverhaal"}
    assert note["text"]["string"].startswith("Jan (1800-1850)")
    photo = next(
        o for o in objects if o["_class"] == "Media" and o["path"] == "levensverhalen/church.jpg"
    )
    assert photo["handle"] in [r["ref"] for r in person["media_list"]]
    links = [t["value"] for t in note["text"]["tags"] if t["value"]]
    assert f"gramps://Media/handle/{photo['handle']}" in links
    assert f"gramps://Person/handle/{own_handle('Person:I1')}" in links


def test_plain_blogpost_stays_a_source_with_tag_blog(without_gramps, tmp_path):
    post = gramps.Blogpost("2026-10-15-feud", "The feud", gramps.AUTHOR, "Text.", [], "")
    objects, _ = gramps_tree.assemble(tmp_path / "x.ged", QUESTIONS, [post], [])
    by_handle = {o["handle"]: o for o in objects}
    source = by_handle[own_handle("Blog:2026-10-15-feud")]
    assert {by_handle[h]["name"] for h in source["tag_list"]} == {"Blog"}
    assert gramps_tree._attribute(source, "ndygen-blog") == "2026-10-15-feud"


def test_edit_in_gramps_web_stays(without_gramps, tmp_path):
    first, _ = gramps_tree.assemble(tmp_path / "x.ged", QUESTIONS, [], [])
    previous = {o["handle"]: fingerprint(o) for o in first}
    server = copy.deepcopy(first)
    source = next(o for o in server if o["handle"] == own_handle("Source:S7"))
    source["title"] = "Record, improved by Ann"

    second, report = gramps_tree.assemble(tmp_path / "x.ged", QUESTIONS, [], server, previous)
    assert next(o for o in second if o["handle"] == source["handle"])["title"].endswith("Ann")
    assert report.changed_in_gramps == ["Source S7"]

    third, report = gramps_tree.assemble(
        tmp_path / "x.ged", QUESTIONS, [], second, gramps_tree.new_state(second, report)
    )
    assert report.changed_in_gramps == ["Source S7"]

    without_state, report = gramps_tree.assemble(tmp_path / "x.ged", QUESTIONS, [], server)
    assert next(o for o in without_state if o["handle"] == source["handle"])["title"] == "Record"


def test_overwrite_restores_our_version(without_gramps, tmp_path):
    first, _ = gramps_tree.assemble(tmp_path / "x.ged", QUESTIONS, [], [])
    previous = {o["handle"]: fingerprint(o) for o in first}
    server = copy.deepcopy(first)
    source = next(o for o in server if o["handle"] == own_handle("Source:S7"))
    source["title"] = "Record, improved by Ann"

    out, report = gramps_tree.assemble(
        tmp_path / "x.ged", QUESTIONS, [], server, previous, overwrite=frozenset({"S7"})
    )
    assert next(o for o in out if o["handle"] == source["handle"])["title"] == "Record"
    assert report.changed_in_gramps == []


def test_gramps_equal_only_looks_at_fields_on_the_server():
    live = {"a": [{"x": 1}], "change": 1}
    assert gramps_tree.gramps_equal(live, {"a": [{"x": 1, "private": False}], "change": 2})
    assert not gramps_tree.gramps_equal(live, {"a": [{"x": 2}]})
    assert not gramps_tree.gramps_equal(live, {"a": []})


def test_fingerprint_ignores_time_and_andys_own_links():
    obj = {"handle": "ndgx", "change": 1, "note_list": [own_handle("a")]}
    later = {**obj, "change": 2, "note_list": [own_handle("a"), "f" * 28]}
    assert fingerprint(obj) == fingerprint(later)


def test_state_from_before_the_rename_is_still_read(tmp_path, monkeypatch):
    class Stub:
        base = "http://gramps.example.org"

    legacy = tmp_path / "old"
    legacy.mkdir()
    (legacy / gramps_tree._state_name(Stub())).write_text('{"ndgx": "abc"}')
    monkeypatch.setattr(gramps_tree, "STATE", tmp_path / "new")
    monkeypatch.setattr(gramps_tree, "LEGACY_STATE", legacy)
    assert gramps_tree._read_state(Stub()) == {"ndgx": "abc"}
    (tmp_path / "new").mkdir()
    (tmp_path / "new" / gramps_tree._state_name(Stub())).write_text('{"ndgx": "def"}')
    assert gramps_tree._read_state(Stub()) == {"ndgx": "def"}


def test_extended_question_keeps_its_task():
    short = "## Personen\n\n- [ ] I9 Piet: overleden?\n"
    first, _ = gramps_tree.task_objects(
        gramps_tree.choose_questions(gramps.read_questions(short)), {}, "todo", {}, gramps_tree.Report()
    )
    server = {o["handle"]: o for o in first}
    long = "## Personen\n\n- [x] I9 Piet: overleden? Ja, Exampleton 1801 (record 12)\n"
    chosen = gramps_tree.match_existing_tasks(
        gramps_tree.choose_questions(gramps.read_questions(long)), server
    )
    second, _ = gramps_tree.task_objects(chosen, {}, "todo", server, gramps_tree.Report())
    assert {o["handle"] for o in second} == set(server)
    source = next(o for o in second if o["_class"] == "Source")
    assert gramps_tree._attribute(source, "Status") == "Done"


def test_address_gets_own_coordinates_or_those_of_the_place():
    def place(address):
        return {
            "_class": "Place",
            "title": "Exampleton, Province, Nederland",
            "alt_loc": [{"street": address}] if address else [],
        }

    objects = [place(""), place("School Street 7"), place("wijk A nr. 3")]
    objects.append({"_class": "Place", "title": "Samplecity", "alt_loc": []})
    without = gramps_tree.set_coordinates(
        objects,
        {
            ("Exampleton, Province, Nederland", ""): ("51.19", "5.99"),
            ("Exampleton, Province, Nederland", "School Street 7"): ("51.1943", "5.9871"),
        },
    )
    assert [(o.get("lat"), o.get("long")) for o in objects] == [
        ("51.19", "5.99"),
        ("51.1943", "5.9871"),
        ("51.19", "5.99"),
        (None, None),
    ]
    assert without == ["Samplecity"]


def test_same_image_in_two_stories_is_one_media_object(without_gramps, tmp_path):
    for name in ("a.jpg", "b.jpg"):
        (tmp_path / name).write_bytes(b"the same photo")
    posts = [
        gramps.Blogpost(
            f"levensverhaal-{name}",
            "Title",
            gramps.AUTHOR,
            "Text.",
            [gramps.Image(f"levensverhalen/{name}", tmp_path / name, "Photo")],
        )
        for name in ("a.jpg", "b.jpg")
    ]
    objects, _ = gramps_tree.assemble(tmp_path / "x.ged", QUESTIONS, posts, [])
    assert [o["path"] for o in objects if o["_class"] == "Media"] == ["levensverhalen/a.jpg"]
    sources = [o for o in objects if o["_class"] == "Source" and "media_list" in o]
    assert len({b["media_list"][0]["ref"] for b in sources}) == 1


def test_image_in_blogpost_is_a_link_at_its_place(without_gramps, tmp_path):
    blog = tmp_path / "blog"
    (blog / "images").mkdir(parents=True)
    (blog / "images" / "bridge.jpg").write_bytes(b"jpg")
    (blog / "2026-10-15-feud.md").write_text(
        "---\ntitle: The feud\n---\nBefore.\n\n![The bridge](images/bridge.jpg)\n*The bridge, 1930*\n\nAfter.\n"
    )
    post = gramps.read_blogpost(blog / "2026-10-15-feud.md")
    assert post.images[0].path == "blog/images/bridge.jpg"
    objects, _ = gramps_tree.assemble(tmp_path / "x.ged", QUESTIONS, [post], [])
    by_handle = {o["handle"]: o for o in objects}
    source = by_handle[own_handle("Blog:2026-10-15-feud")]
    photo = source["media_list"][0]["ref"]
    text = by_handle[source["note_list"][0]]["text"]
    assert "Afbeelding bovenaan: The bridge, 1930" in text["string"]
    assert (
        text["string"].index("Before.")
        < text["string"].index("Afbeelding")
        < text["string"].index("After.")
    )
    assert f"gramps://Media/handle/{photo}" in [t["value"] for t in text["tags"]]


def test_second_image_in_blogpost_is_inline(without_gramps, tmp_path):
    blog = tmp_path / "blog"
    (blog / "images").mkdir(parents=True)
    (blog / "images" / "bridge.jpg").write_bytes(b"jpg1")
    (blog / "images" / "church.jpg").write_bytes(b"jpg2")
    (blog / "2026-10-15-feud.md").write_text(
        "---\ntitle: The feud\n---\nBefore.\n\n![Bridge](images/bridge.jpg)\n*The bridge*\n\n"
        "Middle.\n\n![Church](images/church.jpg)\n*The church*\n\nAfter.\n"
    )
    post = gramps.read_blogpost(blog / "2026-10-15-feud.md")
    objects, _ = gramps_tree.assemble(tmp_path / "x.ged", QUESTIONS, [post], [])
    by_handle = {o["handle"]: o for o in objects}
    source = by_handle[own_handle("Blog:2026-10-15-feud")]
    church = source["media_list"][1]["ref"]
    text = by_handle[source["note_list"][0]]["text"]
    spot = text["string"].index(gramps_tree.INLINE_IMAGE)
    assert text["string"].index("Middle.") < spot < text["string"].index("After.")
    link = next(t for t in text["tags"] if t["value"] == f"gramps://Media/handle/{church}")
    assert link["ranges"] == [[spot, spot + 1]]


def test_rewritten_question_keeps_its_task():
    old = (
        "## Personen\n\n- [ ] I501817 candidate 6 (Adrian Sample): is there a record with his wife, "
        "daughter or relatives that connects him to I500001? Tax rolls 1622-1643 read.\n"
    )
    first, _ = gramps_tree.task_objects(
        gramps_tree.choose_questions(gramps.read_questions(old)), {}, "todo", {}, gramps_tree.Report()
    )
    server = {o["handle"]: o for o in first}
    new = (
        "## Personen\n\n- [ ] I501817 candidate 6 (Adrian Sample): as of 26-10-2026 probably the "
        "father, provisionally linked. Is there a record with his wife, daughter or relatives that connects "
        "him to I500001? Tax rolls 1622-1643 read.\n"
        "- [ ] I777 Klaas: another question about another family, nothing in common with the previous one.\n"
    )
    chosen = gramps_tree.match_existing_tasks(
        gramps_tree.choose_questions(gramps.read_questions(new)), server
    )
    second, _ = gramps_tree.task_objects(chosen, {}, "todo", server, gramps_tree.Report())
    handles = {o["handle"] for o in second}
    assert set(server) <= handles
    assert len(handles) == len(server) + 2  # only the really new question gets a new task

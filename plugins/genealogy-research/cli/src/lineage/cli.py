from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from lineage import (
    archive,
    book,
    browser,
    build,
    coordinates,
    doctor,
    edit,
    forum,
    gramps,
    gramps_tree,
    graph,
    guard,
    htr,
    kinship,
    limits,
    mail,
    merge,
    migrate,
    paternal,
    question_map,
    queue,
    rat,
    reports,
    requests,
    review,
    scaffold,
    scan,
    settings,
    stale,
    web,
)
from lineage.checks import Finding, Level, check
from lineage.gedcom import GedcomError, Tree, load
from lineage.i18n import t
from lineage.queue import possibly_living


def _project() -> settings.Config:
    return settings.current()


def _tree_file(args: argparse.Namespace) -> Path:
    return args.file or _project().path("gedcom")


def _fonds(value: str | None) -> str:
    fonds = value or _project().rat_fonds
    _project().require(fonds, "[rat] fonds")
    return fonds


def _person_id(tree: Tree, raw: str) -> str:
    pid = raw.strip().strip("@").upper()
    if pid not in tree.persons:
        raise SystemExit(t("person {pid} not found; use 'lineage search <name>'", pid=pid))
    return pid


def cmd_summary(tree: Tree, args: argparse.Namespace) -> int:
    print(reports.overview(tree))
    return 0


def _level_name(level: Level) -> str:
    return {Level.ERROR: t("error"), Level.WARNING: t("warning"), Level.INFO: t("info")}[level]


def cmd_validate(tree: Tree, args: argparse.Namespace) -> int:
    limit = Level[args.level.upper()]
    findings = [f for f in check(tree) if f.level <= limit]
    findings += [Finding(Level.ERROR, "requests", error) for error in requests.errors()]
    table = coordinates.table_for(args.file)
    places = {e.place for x in [*tree.persons.values(), *tree.families.values()] for e in x.events}
    findings += [
        Finding(
            Level.WARNING,
            "coordinates",
            t("no row in {table} for '{place}'", table=table.name, place=p),
        )
        for p in coordinates.missing_places(places - {""}, table)
    ]
    for finding in findings:
        subject = tree.persons.get(finding.subject)
        name = f" {subject.name}" if subject else ""
        print(f"{_level_name(finding.level).upper():<12} {finding.subject}{name}: {finding.message}")
    totals = {
        level: sum(1 for f in findings if f.level == level) for level in Level if level <= limit
    }
    print("\n" + ", ".join(f"{count} {_level_name(level)}" for level, count in totals.items()))
    return 1 if totals.get(Level.ERROR) else 0


def cmd_search(tree: Tree, args: argparse.Namespace) -> int:
    matches = reports.search(tree, " ".join(args.words))
    for person in matches:
        print(reports.label(person))
    return 0 if matches else 1


def cmd_person(tree: Tree, args: argparse.Namespace) -> int:
    print(reports.person_card(tree, _person_id(tree, args.id)))
    return 0


def cmd_ancestors(tree: Tree, args: argparse.Namespace) -> int:
    print(reports.ancestor_table(tree, _person_id(tree, args.id), args.generations))
    return 0


def cmd_descendants(tree: Tree, args: argparse.Namespace) -> int:
    print(reports.descendant_table(tree, _person_id(tree, args.id), args.generations))
    return 0


def cmd_tree(tree: Tree, args: argparse.Namespace) -> int:
    pid = _person_id(tree, args.id)
    select = graph.ancestors if args.direction == "ancestors" else graph.descendants
    dot = graph.to_dot(tree, *select(tree, pid, args.generations))

    target = args.out or _project().path("output") / f"{pid}-{args.direction}.dot"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dot, encoding="utf-8")
    print(t("written: {path}", path=target))

    if shutil.which("dot"):
        svg = target.with_suffix(".svg")
        subprocess.run(["dot", "-Tsvg", str(target), "-o", str(svg)], check=True)
        print(t("written: {path}", path=svg))
    else:
        print(t("install Graphviz (apt install graphviz) to render an SVG"))
    return 0


def cmd_archive_search(args: argparse.Namespace) -> int:
    total, hits = archive.search(
        " ".join(args.name), args.type, args.place, args.role, args.source, args.limit
    )
    print(t("{total} found, {shown} shown", total=total, shown=len(hits)))
    for hit in hits:
        print(f"{hit.ref}  {hit.date:<10} {hit.event:<12} {hit.place:<20} {hit.role}: {hit.person}")
    return 0 if hits else 1


def cmd_archive_show(args: argparse.Namespace) -> int:
    record = archive.show(args.ref)
    print(archive.describe(record))
    if args.gedcom:
        print("\n" + t("# source record (once per file)") + "\n" + record.gedcom_source())
        print("\n" + t("# citation") + "\n" + record.gedcom_citation())
    return 0


def _label(tree: Tree, pid: str) -> str:
    person = tree.persons.get(pid)
    return reports.label(person) if person else t("{pid} (no longer in the tree)", pid=pid)


def cmd_scan(args: argparse.Namespace) -> int:
    failures = 0
    for ref in args.refs:
        try:
            for path in scan.fetch(ref, args.dir, args.max):
                print(f"{ref}: {path}")
        except (
            scan.ScanError,
            web.WebError,
            browser.BrowserError,
            rat.RatError,
            archive.ArchiveError,
        ) as exc:
            failures += 1
            print(t("{ref}: FAILED: {error}", ref=ref, error=exc), file=sys.stderr)
    return 1 if failures else 0


def _htr_model(value: str) -> int:
    try:
        return htr.model_id(value)
    except htr.HtrError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def cmd_forum(args: argparse.Namespace) -> int:
    if args.forum_command == "post":
        draft = forum.read_draft(args.draft)
        url = forum.post(draft, preview=args.preview)
        print(t("preview shown, not posted") if url is None else t("posted: {url}", url=url))
        return 0
    found = forum.read_replies(forum.drafts(args.dir))
    for draft, blocks in found:
        print(
            t(
                "{name}: {count} new repl(ies) ({thread})",
                name=draft.path.name,
                count=len(blocks),
                thread=draft.header["thread"],
            )
        )
        for block in blocks:
            print("  " + block.replace("\n", "\n  "))
    if not found:
        print(t("no new replies"))
    return 0


def cmd_htr_count(args: argparse.Namespace) -> int:
    total, per_model = htr.count(args.since)
    names = {v: k for k, v in htr.MODELS.items()}
    if args.since:
        print(
            t(
                "{total} recognitions since {since} (log: {log})",
                total=total,
                since=args.since,
                log=htr.log_path(),
            )
        )
    else:
        print(t("{total} recognitions (log: {log})", total=total, log=htr.log_path()))
    for model, number in per_model.most_common():
        print(f"  {names.get(model, model)} ({model}): {number}")
    try:
        packages = htr.packages(htr.token(htr.config()))
    except htr.HtrError as exc:
        print(t("balance unknown: {error}", error=exc), file=sys.stderr)
        return 0
    print(t("balance: {credits:g} credits", credits=sum(p.balance for p in packages)))
    for p in packages:
        print(
            t(
                "  {label}: {credits:g} (expires {expires})",
                label=p.label,
                credits=p.balance,
                expires=p.expires,
            )
        )
    return 0


def cmd_htr(args: argparse.Namespace) -> int:
    if args.count:
        return cmd_htr_count(args)
    if not args.images:
        print(t("give scans, or --count"), file=sys.stderr)
        return 2
    images = [Path(b) for b in args.images]
    if missing := [str(b) for b in images if not b.is_file()]:
        print(t("not found: {names}", names=", ".join(missing)), file=sys.stderr)
        return 2
    new = htr.new_images(images, args.model)
    for image in images:
        if image not in new:
            print(
                t(
                    "{image}: already recognized: {path}",
                    image=image,
                    path=htr.outputs(image, args.model)[0],
                )
            )
    if len(new) > args.max:
        print(
            t(
                "{count} new scans, more than --max {max}; every scan costs credits",
                count=len(new),
                max=args.max,
            ),
            file=sys.stderr,
        )
        return 2
    if not new or args.dry_run:
        print(t("{count} new scans to recognize", count=len(new)))
        return 0
    cfg = htr.config()
    if (credit := htr.balance(htr.token(cfg))) <= 0:
        print(t("no Transkribus credits left (balance 0); see htr --count"), file=sys.stderr)
        return 2
    print(t("balance: {credits:g} credits", credits=credit))
    failures = 0
    for i, image in enumerate(new):
        try:
            # An access token lives only a few minutes; a long batch needs a fresh one per scan.
            txt, _ = htr.recognize(image, args.model, cfg, htr.token(cfg))
            print(f"{image}: {txt}")
        except htr.HtrError as exc:
            failures += 1
            print(t("{ref}: FAILED: {error}", ref=image, error=exc), file=sys.stderr)
            # Without credits Transkribus fails each job at once and gives no reason.
            if htr.balance(htr.token(cfg)) <= 0:
                print(
                    t("out of credits; {count} scans not submitted", count=len(new) - i - 1),
                    file=sys.stderr,
                )
                return 1
    return 1 if failures else 0


def cmd_rat_search(args: argparse.Namespace) -> int:
    fonds = _fonds(args.fonds)
    total, items = rat.search(" ".join(args.terms), fonds, args.limit)
    print(t("{total} inventory items in RAT {fonds} (titles only)", total=total, fonds=fonds))
    for s in items:
        print(
            t(
                "  inv. {inventory:>5}  {dating:<12} {scans:>4} scans  {title}",
                inventory=s.inventory,
                dating=s.dating,
                scans=s.scan_count,
                title=s.title,
            )
        )
    return 0


def cmd_rat_item(args: argparse.Namespace) -> int:
    s = rat.item(args.inventory, _fonds(args.fonds))
    print(s.citation())
    print(t("dating: {dating}; {count} scans", dating=s.dating or "?", count=len(s.scans)))
    if args.scans:
        for scan in s.scans:
            print(f"  {scan.number:4d}  {scan.name}  {scan.url}")
    return 0


def cmd_rat_download(args: argparse.Namespace) -> int:
    s = rat.item(args.inventory, _fonds(args.fonds))
    numbers = rat.parse_numbers(args.scans) if args.scans else [x.number for x in s.scans]
    for path in rat.download(s, numbers, args.dir or _project().path("output") / "scans"):
        print(path)
    return 0


def _git_common_dir() -> Path:
    return Path(
        subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )


def cmd_guard(args: argparse.Namespace) -> int:
    common = _git_common_dir()
    root = common.parent
    guard.run(
        root,
        common,
        args.interval,
        args.once,
        args.dry_run,
        args.coordinator,
    )
    return 0


def cmd_rat_throttle(args: argparse.Namespace) -> int:
    if args.release:
        rat.release()
    if args.test:
        print(rat.probe())
    state = rat.throttle_state()
    until = state.get("locked_until", 0)
    if until > time.time():
        print(
            t(
                "locked out until {time}: {reason}",
                time=time.strftime("%d-%m %H:%M", time.localtime(until)),
                reason=state.get("reason", "?"),
            )
        )
    else:
        print(
            t(
                "active; at least {seconds:g} s between requests (all processes together)",
                seconds=rat.INTERVAL,
            )
        )
    if state.get("last"):
        print(
            t(
                "last request: {time}",
                time=time.strftime("%d-%m %H:%M:%S", time.localtime(state["last"])),
            )
        )
    return 0


def cmd_rat_crop(args: argparse.Namespace) -> int:
    out = args.out or args.image.with_name(
        f"{args.image.stem}_{'_'.join(f'{k:.2f}' for k in args.frame)}.jpg"
    )
    print(rat.crop(args.image, tuple(args.frame), out, args.scale))
    return 0


def cmd_queue_show(tree: Tree, args: argparse.Namespace) -> int:
    items = queue.load(args.queue)
    in_line = queue.direct_line(tree) | set(queue.stem_rank(tree))
    shown = [i for i in items.values() if args.all or i.status in ("open", "in_progress")]
    side_branches = [i for i in shown if i.status == "open" and i.id not in in_line]
    if not (args.all or args.side_branches):
        shown = [i for i in shown if i not in side_branches]
    for item in sorted(shown, key=lambda i: i.sort_key):
        extra = t(" ids {block}", block=item.id_block) if item.status == "in_progress" else ""
        print(f"{item.status:<12} r{item.round} p{item.priority}  {_label(tree, item.id)}{extra}")
        if item.reason:
            print(f"{'':>20}{item.reason}" + (t(" (via {via})", via=item.via) if item.via else ""))
    counts = {s: sum(1 for i in items.values() if i.status == s) for s in queue.STATUSES}
    print("\n" + ", ".join(f"{n} {s}" for s, n in counts.items()))
    if side_branches and not (args.all or args.side_branches):
        print(
            t(
                "of which {count} open in side branches, not shown (--side-branches)",
                count=len(side_branches),
            )
        )
    return 0


def cmd_queue_add(tree: Tree, args: argparse.Namespace) -> int:
    items = queue.load(args.queue)
    for raw in args.ids:
        pid = raw.strip().strip("@").upper()
        item, new = queue.add(items, tree, pid, args.via, args.reason, args.priority, args.round)
        state = t("added") if new else t("already present ({status})", status=item.status)
        if new and item.status == "skipped":
            state = t("skipped: possibly living")
        print(f"{pid}: {state}")
    queue.save(items, args.queue)
    return 0


def cmd_queue_next(tree: Tree, args: argparse.Namespace) -> int:
    line = None if args.side_branches else queue.direct_line(tree)
    item = queue.next_open(queue.load(args.queue), tree, line)
    if item is None:
        print(t("no open items") if args.side_branches else t("no open items in the direct line"))
        return 1
    print(item.id)
    return 0


def cmd_queue_start(tree: Tree, args: argparse.Namespace) -> int:
    items = queue.load(args.queue)
    item = queue.start(items, tree, args.id.strip("@").upper(), args.force, args.follow_up)
    queue.save(items, args.queue)
    print(t("{id} in progress, ID block I/F/S {block}", id=item.id, block=item.id_block))
    return 0


def cmd_queue_done(tree: Tree, args: argparse.Namespace) -> int:
    items = queue.load(args.queue)
    pid = args.id.strip("@").upper()
    queue.finish(items, pid, args.report)
    if not args.no_note:
        merge.mark_researched_file(args.file, pid, args.date, args.report)
    queue.save(items, args.queue)
    return 0


def cmd_queue_skip(tree: Tree, args: argparse.Namespace) -> int:
    items = queue.load(args.queue)
    pid = args.id.strip("@").upper()
    if pid not in items:
        raise SystemExit(t("{pid} is not in the queue", pid=pid))
    items[pid].status = "skipped"
    items[pid].reason = args.reason
    queue.save(items, args.queue)
    return 0


def cmd_queue_normalize(tree: Tree, args: argparse.Namespace) -> int:
    queue.save(queue.load(args.queue), args.queue)
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    pid = args.id.strip("@").upper()
    try:
        outcome = review.review_branch(_project().root, pid)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(outcome.text())
    return 1 if outcome.errors else 0


def cmd_stale(tree: Tree, args: argparse.Namespace) -> int:
    if args.checked:
        for pid in args.id:
            stale.mark_checked(_project().root, _person_id(tree, pid))
        return 0
    stale_items = stale.stale_stories(tree, with_parents=args.direct_line)
    if args.id:
        stale_items = [s for s in stale_items if s.pid in {_person_id(tree, i) for i in args.id}]
    print(stale.report(tree, stale_items, short=args.short))
    return 0


def cmd_requests(tree: Tree, args: argparse.Namespace) -> int:
    if args.mark:
        name, status = args.mark
        requests.mark(requests.find(name), status)
        return 0
    found = requests.load_all()
    if args.person:
        found = [a for a in found if args.person in a.persons]
    if not args.all:
        found = [a for a in found if a.status in (("draft",) if args.text else requests.OPEN)]
    print(requests.overview(found, with_text=args.text))
    return 0


def cmd_mail(args: argparse.Namespace) -> int:
    if args.mail_command == "test":
        print(mail.test())
    elif args.mail_command == "send":
        print(mail.send(requests.find(args.name), approved=args.approved))
    else:
        lines = mail.inbox()
        print("\n".join(lines) if lines else t("no new mail"))
    return 0


def cmd_coordinates(args: argparse.Namespace) -> int:
    if args.coordinates_command == "index":
        coordinates.build_index()
        return 0
    if args.coordinates_command == "search":
        if args.address:
            point = coordinates.find_address(args.place, args.address, args.year)
            candidates = [point] if point else []
        else:
            candidates = coordinates.find_place(args.place)
        for point in candidates:
            print("\t".join(point.row(args.place, args.address or "")))
        if len(candidates) > 1:
            print(
                t(
                    "{count} candidates: choose by context; more than 15 km apart is not unambiguous",
                    count=len(candidates),
                )
            )
        if not candidates:
            print(t("not found") + (t(" (stays on the place)") if args.address else ""))
        return 0 if candidates else 1
    tree_file = _tree_file(args)
    path = coordinates.table_for(tree_file)
    objects = gramps_tree.read_gedcom(tree_file)
    places = [o for o in objects if o["_class"] == "Place"]
    table = coordinates.read(path)
    result = coordinates.fill(places, coordinates.years_per_place(objects), table)
    for row in result.added:
        print(t("new") + "\t" + "\t".join(row))
    for title, candidates in result.doubtful:
        print(
            f"{t('doubtful')}\t{title}: "
            + "; ".join(f"{k.lat:.4f},{k.lon:.4f} ({k.origin})" for k in candidates[:4])
        )
    for title in result.not_found:
        print(f"{t('not found')}\t{title}")
    if not args.dry_run:
        coordinates.write(table, path)
    count = len(result.added)
    by_hand = len(result.doubtful) + len(result.not_found)
    if args.dry_run:
        print(
            t(
                "{count} rows found; {by_hand} places by hand (row with lat/lon, or without lat/lon with the reason in the remark)",
                count=count,
                by_hand=by_hand,
            )
        )
    else:
        print(
            t(
                "{count} rows added; {by_hand} places by hand (row with lat/lon, or without lat/lon with the reason in the remark)",
                count=count,
                by_hand=by_hand,
            )
        )
    return 0


def cmd_gramps(args: argparse.Namespace) -> int:
    g = gramps.Gramps()
    if args.gramps_command == "status":
        lines = gramps.status(g)
    else:
        project = _project()
        posts = [gramps.read_blogpost(p) for p in sorted(project.path("blog").glob("*.md"))]
        tree_file = _tree_file(args)
        tree = load(tree_file)
        skipped = []
        for p in sorted(project.path("life_stories").glob("I*.md")):
            person = tree.persons.get(p.stem)
            if person is None or possibly_living(person, tree):
                skipped.append(p.stem)
            else:
                posts.append(gramps.read_life_story(p, tree_file.parent / "media"))
        questions = project.path("questions").read_text(encoding="utf-8")
        result = gramps_tree.sync(
            g,
            tree_file,
            questions,
            posts,
            dry_run=args.dry_run,
            overwrite=frozenset(args.overwrite),
        )
        lines = result.lines()
        if skipped:
            lines.append(
                t(
                    "life stories not posted (not in the tree or possibly living): {ids}",
                    ids=", ".join(skipped),
                )
            )
    print("\n".join(lines))
    return 0


def cmd_book(tree: Tree, args: argparse.Namespace) -> int:
    pid = _person_id(tree, args.id)
    text = book.build(tree, pid, oldest_first=not args.youngest_first)
    out = args.out or _project().path("books") / f"{pid}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(out)
    return 0


def cmd_kinship(tree: Tree, args: argparse.Namespace) -> int:
    pid = _person_id(tree, args.id)
    if args.to:
        refs = args.to
    else:
        project = _project()
        project.require(project.targets, "targets")
        refs = [target.id for target in project.targets]
        if missing := [r for r in refs if r not in tree.persons]:
            raise SystemExit(
                t(
                    "target person {ids} is not in the tree; fix 'targets' in {file} or give --to",
                    ids=", ".join(missing),
                    file=project.file,
                )
            )
    for ref in refs:
        ref_id = _person_id(tree, ref)
        text = kinship.describe(tree, pid, ref_id)
        print(f"{tree.persons[ref_id].name} ({ref_id}): {text or t('no kinship found')}")
    return 0


def _paternal_start(tree: Tree) -> str:
    """[paternal_line] start, else the first target person who is a man in the tree."""
    project = _project()
    men = [x.id for x in project.targets if (p := tree.persons.get(x.id)) and p.sex == "M"]
    start = project.paternal_start or (men[0] if men else "")
    project.require(start, "[paternal_line] start")
    return start


def cmd_paternal(tree: Tree, args: argparse.Namespace) -> int:
    ids = paternal.line(tree, _person_id(tree, args.start or _paternal_start(tree)))
    if not args.notify:
        for gen, pid in enumerate(ids):
            print(f"{gen}\t{pid}\t{tree.persons[pid].name}")
        return 0
    state_file = args.state or _git_common_dir() / "dr-paternal"
    if not args.state and not state_file.exists() and (legacy := state_file.with_name("dr-vaderlijn")).exists():
        state_file.write_text(legacy.read_text())
    old = paternal.read_state(state_file)
    if old is None:
        print(
            t(
                "paternal line recorded: {count} generations, oldest {oldest}",
                count=len(ids),
                oldest=ids[-1],
            )
        )
    elif ids == old:
        print(t("paternal line unchanged: oldest {oldest}", oldest=ids[-1]))
    elif paternal.new_generations(old, ids):
        project = _project()
        recipient = project.paternal_notify or project.own_address
        project.require(recipient, "[paternal_line] notify")
        path = paternal.draft(tree, old, ids, recipient)
        print(t("paternal line extended: draft {path}", path=path))
        try:
            print(mail.send(requests.read(path), approved=False))
        except mail.MailError as e:
            print(t("sending failed: {error}", error=e))
    else:
        print(
            t(
                "paternal line changed without extension: oldest was {old}, now {new}",
                old=old[-1],
                new=ids[-1],
            )
        )
    paternal.write_state(state_file, ids)
    return 0


def cmd_question_map(tree: Tree, args: argparse.Namespace) -> int:
    project = _project()
    questions = args.questions or project.path("questions")
    out = args.out or project.path("question_map_page")
    data = question_map.build(
        tree,
        questions.read_text(encoding="utf-8"),
        _person_id(tree, args.start or project.root_person),
    )
    history = question_map.update_history(
        args.history or project.path("question_history"), data["totals"]
    )
    question_map.write(data, history, out, project.name)
    totals = data["totals"]
    print(
        t(
            "{out}: {open} open questions, {gaps} missing parents, {points} data points",
            out=out,
            open=totals["open"],
            gaps=totals["gaps"],
            points=len(history),
        )
    )
    return 0


def _pairs(values: list[str] | None, option: str) -> list[tuple[str, str]]:
    pairs = []
    for value in values or []:
        key, sep, rest = value.partition("=")
        if not sep or not key.strip() or not rest.strip():
            raise SystemExit(
                t("{option} needs NAME=VALUE, got {value!r}", option=option, value=value)
            )
        pairs.append((key.strip(), rest.strip()))
    return pairs


def _load_quietly(path: Path) -> Tree | None:
    try:
        return load(path)
    except (FileNotFoundError, GedcomError):
        return None


def cmd_init(args: argparse.Namespace) -> int:
    root = Path.cwd().resolve()
    existing = settings.find(root) if args.update else None
    if args.update and existing is None:
        raise settings.ConfigError(
            t("no {file} in {root} or above to update", file=settings.FILE, root=root)
        )
    base = settings.load(existing.parent) if existing else settings.Config(root=root)
    c = _settings_from_args(base, args)
    if args.new_tree and not c.path("gedcom").exists():
        build.new_tree(c.path("gedcom"))
        print(t("new tree: {path}", path=c.rel("gedcom")))
    tree = _load_quietly(c.path("gedcom"))
    for path in scaffold.write(c, tree, args.allow or [], overwrite_config=args.update):
        print(t("written: {path}", path=path.relative_to(c.root)))
    for problem in scaffold.check(c, tree):
        print(t("check: {problem}", problem=problem), file=sys.stderr)
    return 0


def _settings_from_args(base: settings.Config, args: argparse.Namespace) -> settings.Config:
    stems = []
    for name, value in _pairs(args.stem, "--stem"):
        pid, _, flag = value.partition(":")
        stems.append(settings.Stem(name, pid.upper(), flag == "men-first"))
    accounts = dict(base.accounts)
    for name, config_dir in _pairs(args.account, "--account"):
        accounts[name] = {} if config_dir == "-" else {"config_dir": config_dir}
    c = scaffold.merged(
        base,
        name=args.name,
        language=args.language,
        gedcom=args.gedcom,
        targets=tuple(
            settings.Target(label, pid.upper()) for label, pid in _pairs(args.target, "--target")
        ),
        line_root=(args.line_root or "").upper(),
        stems=tuple(stems),
        runner=args.runner,
        paths={**base.paths, **dict(_pairs(args.path, "--path"))},
        paternal_start=(args.paternal_start or "").upper(),
        paternal_notify=args.paternal_notify,
        mail_enabled=args.mail or None,
        own_address=(args.own_address or "").lower(),
        sender_name=args.sender_name,
        gramps_url=args.gramps_url,
        rat_fonds=args.rat_fonds,
        accounts=accounts,
    )
    settings.parse(settings.dump(c), c.root / settings.FILE)
    return c


def cmd_migrate(args: argparse.Namespace) -> int:
    root = Path.cwd().resolve()
    base = _settings_from_args(settings.Config(root=root, language="nl"), args)
    settings.use(base)
    p = migrate.plan(root, base)
    for line in p.lines(root):
        print(line)
    for problem in scaffold.check(p.config, _load_quietly(p.config.path("gedcom"))):
        print(t("check: {problem}", problem=problem), file=sys.stderr)
    if not args.apply:
        print(t("nothing changed; run again with --apply"))
        return 0
    migrate.apply(p)
    print(t("migrated; check with 'git diff' and commit {file}", file=settings.FILE))
    return 0


VALUE_KEYS = ("language", "runner", "name", "line_root", "mail_enabled")


def resolve_runner(project: settings.Config) -> str:
    runner = os.environ.get("DR_RUNNER") or project.runner
    if runner != "auto":
        return runner
    return "herdr" if os.environ.get("HERDR_ENV") == "1" and shutil.which("herdr") else "inline"


def cmd_limits_parse(args: argparse.Namespace) -> int:
    reset = limits.limit_reset(sys.stdin.read(), dt.datetime.now())
    if reset is None:
        return 1
    print(reset)
    return 0


def _built(path: Path, change) -> str:
    """Applies change to the tree's lines, and keeps the file as it was if the result does not read back."""
    if not path.exists():
        raise SystemExit(t("{path} does not exist; start one with 'lineage init --new-tree'", path=path))
    lines = edit.read(path)
    result = change(lines)
    before = path.read_bytes()
    edit.write(path, lines)
    try:
        load(path)
    except GedcomError as exc:
        path.write_bytes(before)
        raise SystemExit(t("the change would break the tree, nothing written: {error}", error=exc)) from exc
    return result


def cmd_add(args: argparse.Namespace) -> int:
    path = _tree_file(args)
    try:
        if args.add_command == "person":
            events = [
                build.Event(tag, date or "", place or "")
                for tag, date, place in (
                    ("BIRT", args.born, args.born_place),
                    ("CHR", args.baptized, args.baptized_place),
                    ("DEAT", args.died, args.died_place),
                    ("BURI", args.buried, args.buried_place),
                )
                if date or place
            ]
            if args.deceased and not any(e.tag in ("DEAT", "BURI") for e in events):
                events.append(build.Event("DEAT"))
            pid = _built(path, lambda lines: build.add_person(
                lines, args.given or "", args.surname or "", args.sex, events,
                args.occupation or "", args.note or "", args.source or "", args.page or "",
            ))
            print(reports.label(load(path).persons[pid]))
        elif args.add_command == "family":
            married = build.Event("MARR", args.married or "", args.married_place or "") if (
                args.married or args.married_place
            ) else None
            fid = _built(path, lambda lines: build.add_family(
                lines, [p.upper() for p in args.partner], [c.upper() for c in args.child or []],
                married, args.source or "", args.page or "",
            ))
            print(fid)
        else:
            family, children = args.family.upper(), [c.upper() for c in args.ids]
            _built(path, lambda lines: [build.add_child(lines, family, c) for c in children])
            print(t("{family}: {count} child(ren) linked", family=args.family.upper(), count=len(args.ids)))
    except (build.BuildError, edit.EditError) as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    project = _project()
    if args.config_command == "path":
        print(project.rel(args.key) if args.relative else project.path(args.key))
        return 0
    if args.config_command == "paths":
        for key in ("gedcom", *settings.PATHS):
            print(f"{key}={project.rel(key).as_posix()}")
        return 0
    if args.config_command == "value":
        value = getattr(project, args.key)
        print(str(value).lower() if isinstance(value, bool) else value)
        return 0
    if args.config_command == "runner":
        print(resolve_runner(project))
        return 0
    if args.config_command == "accounts":
        for name, values in project.accounts.items() or {"default": {}}.items():
            print(f"{name}\t{values.get('config_dir', '')}")
        return 0
    if args.config_command == "check":
        problems = scaffold.check(project, _load_quietly(project.path("gedcom")))
        if project.file is None:
            problems.insert(
                0, t("no {file} in {root} or above", file=settings.FILE, root=project.root)
            )
        for problem in problems:
            print(problem)
        print(t("settings OK") if not problems else t("{count} problem(s)", count=len(problems)))
        return 1 if problems else 0
    print(
        f"# {project.file or t('no {file}: defaults for {root}', file=settings.FILE, root=project.root)}"
    )
    print(settings.dump(project), end="")
    print("\n" + t("# resolved paths"))
    for key in ("gedcom", *settings.PATHS):
        print(f"# {key} = {project.rel(key)}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    if args.install_browser:
        return doctor.install_browser()
    results = doctor.checks()
    for c in results:
        mark = t("ok") if c.ok else (t("MISSING") if c.required else t("optional"))
        print(f"{mark:<9} {c.name:<11} {c.detail}")
    for name in doctor.SERVICES:
        print(f"{t('service'):<9} {name:<11} {doctor.status(name)}")
    return 1 if any(c.required and not c.ok for c in results) else 0


def cmd_auth(args: argparse.Namespace) -> int:
    if args.service == "check":
        for name in doctor.SERVICES:
            print(f"{name:<11} {doctor.purpose(name)}: {doctor.status(name)}")
        return 0
    if not sys.stdin.isatty():
        print(
            t("run this yourself in a terminal: lineage auth {service}", service=args.service),
            file=sys.stderr,
        )
        return 2
    try:
        path = doctor.prompt(args.service)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(t("written: {path} (mode 600)", path=path))
    return 0


def _setting_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", help="project title, e.g. 'Smith family research'")
    parser.add_argument("--language", choices=settings.LANGUAGES, help="output language")
    parser.add_argument("--gedcom", help="the research tree, relative to this folder")
    parser.add_argument(
        "--target", action="append", metavar="LABEL=ID", help="target person (repeat)"
    )
    parser.add_argument("--line-root", help="person whose ancestors form the direct line")
    parser.add_argument(
        "--stem",
        action="append",
        metavar="NAME=ID[:men-first]",
        help="paternal line, in order (repeat)",
    )
    parser.add_argument("--runner", choices=settings.RUNNERS)
    parser.add_argument(
        "--path", action="append", metavar="KEY=PATH", help="other folder or file name"
    )
    parser.add_argument("--paternal-start", help="start of the paternal line to watch")
    parser.add_argument("--paternal-notify", help="address for the paternal line notice")
    parser.add_argument(
        "--mail", action="store_true", help="this project sends requests and reads replies (lineage auth mail)"
    )
    parser.add_argument("--own-address", help="the user's own mail address (needs no approval)")
    parser.add_argument("--sender-name", help="name above request letters")
    parser.add_argument("--gramps-url", help="Gramps Web server")
    parser.add_argument("--rat-fonds", help="default Regionaal Archief Tilburg fonds")
    parser.add_argument(
        "--account",
        action="append",
        metavar="NAME=CONFIG_DIR",
        help="Claude account ('-' for the default dir)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lineage", description="Genealogy research on GEDCOM trees"
    )
    parser.add_argument("--file", type=Path, help="GEDCOM file (default: gedcom in lineage.toml)")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser(
        "init", help=f"write {settings.FILE} and the empty research files in this folder"
    )
    init.add_argument("--update", action="store_true", help=f"change the existing {settings.FILE}")
    init.add_argument(
        "--new-tree", action="store_true", help="start an empty GEDCOM when there is none yet (lineage add ...)"
    )
    _setting_options(init)
    init.add_argument(
        "--allow",
        action="append",
        metavar="TEXT",
        help="privacy exception for research/project.md (repeat)",
    )
    init.set_defaults(offline=cmd_init)

    add = commands.add_parser(
        "add", help="build the tree by hand: persons, families and children, each fact with its source"
    )
    add_commands = add.add_subparsers(dest="add_command", required=True)
    add_person = add_commands.add_parser("person", help="add a person; prints the new ID")
    add_person.add_argument("--given", help="given names")
    add_person.add_argument("--surname", help="surname (for a married woman: her birth name)")
    add_person.add_argument("--sex", default="U", help="M, F or U")
    for event, word in (("born", "birth"), ("baptized", "baptism"), ("died", "death"), ("buried", "burial")):
        add_person.add_argument(f"--{event}", metavar="DATE", help=f"{word} date: 12-3-1950, 1950, about 1890, ...")
        add_person.add_argument(f"--{event}-place", metavar="PLACE", help="'Town, Province, Country'")
    add_person.add_argument("--deceased", action="store_true", help="died, date and place unknown")
    add_person.add_argument("--occupation")
    add_person.add_argument("--note")
    add_person.add_argument(
        "--source", help="where the facts come from, e.g. 'Told by Anna Jansen (aunt), 2026' or 'Family booklet'"
    )
    add_person.add_argument("--page", help="detail within the source (page, record number)")
    add_person.set_defaults(offline=cmd_add)
    add_family = add_commands.add_parser("family", help="add a couple (or one parent) with children")
    add_family.add_argument("--partner", action="append", required=True, metavar="ID", help="one or two")
    add_family.add_argument("--child", action="append", metavar="ID")
    add_family.add_argument("--married", metavar="DATE")
    add_family.add_argument("--married-place", metavar="PLACE")
    add_family.add_argument("--source")
    add_family.add_argument("--page")
    add_family.set_defaults(offline=cmd_add)
    add_child = add_commands.add_parser("child", help="add children to an existing family")
    add_child.add_argument("family")
    add_child.add_argument("ids", nargs="+")
    add_child.set_defaults(offline=cmd_add)

    migrate_parser = commands.add_parser(
        "migrate",
        help="turn a project of the Dutch predecessor (ndygen) into a lineage project; shows the plan first",
    )
    migrate_parser.add_argument("--apply", action="store_true", help="carry out the plan")
    _setting_options(migrate_parser)
    migrate_parser.set_defaults(offline=cmd_migrate)

    config_parser = commands.add_parser("config", help=f"the settings in {settings.FILE}")
    config_commands = config_parser.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("show", help="settings and resolved paths").set_defaults(
        offline=cmd_config
    )
    config_commands.add_parser(
        "check", help="are the target persons, line root and stems in the tree"
    ).set_defaults(offline=cmd_config)
    config_path = config_commands.add_parser("path", help="absolute path of a file or folder")
    config_path.add_argument("key", choices=["gedcom", *settings.PATHS])
    config_path.add_argument("--relative", action="store_true", help="path below the project root")
    config_path.set_defaults(offline=cmd_config)
    config_commands.add_parser(
        "paths", help="every file and folder as key=path below the project root"
    ).set_defaults(offline=cmd_config)
    config_value = config_commands.add_parser("value", help="one scalar setting")
    config_value.add_argument("key", choices=VALUE_KEYS)
    config_value.set_defaults(offline=cmd_config)
    config_commands.add_parser(
        "runner", help="the runner to use: DR_RUNNER, lineage.toml, else auto-detected"
    ).set_defaults(offline=cmd_config)
    config_commands.add_parser(
        "accounts", help="one line per account: name and config dir, tab separated"
    ).set_defaults(offline=cmd_config)

    limits_parser = commands.add_parser("limits", help="usage-limit messages of Claude Code")
    limits_commands = limits_parser.add_subparsers(dest="limits_command", required=True)
    limits_commands.add_parser(
        "parse", help="screen text on stdin: print the reset as epoch, exit 1 without a limit"
    ).set_defaults(offline=cmd_limits_parse)

    doctor_parser = commands.add_parser("doctor", help="required and optional software, services")
    doctor_parser.add_argument(
        "--install-browser", action="store_true", help="download Chromium for scan and forum"
    )
    doctor_parser.set_defaults(offline=cmd_doctor)

    auth = commands.add_parser(
        "auth",
        help="enter credentials for a service (type it yourself; the password is not echoed)",
    )
    auth.add_argument("service", choices=[*doctor.SERVICES, "check"])
    auth.set_defaults(offline=cmd_auth)

    commands.add_parser("summary", help="counts, source coverage and surnames").set_defaults(
        run=cmd_summary
    )

    validate = commands.add_parser("validate", help="check for errors and implausibilities")
    validate.add_argument(
        "--level", choices=[level.name.lower() for level in Level], default="warning"
    )
    validate.set_defaults(run=cmd_validate)

    search = commands.add_parser("search", help="find persons by name")
    search.add_argument("words", nargs="+")
    search.set_defaults(run=cmd_search)

    person = commands.add_parser("person", help="everything about one person")
    person.add_argument("id")
    person.set_defaults(run=cmd_person)

    ancestors = commands.add_parser("ancestors", help="ancestors, numbered")
    ancestors.add_argument("id")
    ancestors.add_argument("--generations", type=int, default=5)
    ancestors.set_defaults(run=cmd_ancestors)

    descendants = commands.add_parser("descendants", help="descendants")
    descendants.add_argument("id")
    descendants.add_argument("--generations", type=int, default=4)
    descendants.set_defaults(run=cmd_descendants)

    tree = commands.add_parser("tree", help="family tree diagram as Graphviz DOT/SVG")
    tree.add_argument("id")
    tree.add_argument("--direction", choices=["ancestors", "descendants"], default="ancestors")
    tree.add_argument("--generations", type=int, default=4)
    tree.add_argument("--out", type=Path)
    tree.set_defaults(run=cmd_tree)

    review_parser = commands.add_parser(
        "review",
        help="mechanical review of a finished deep-research branch (dr/<ID>) against main",
    )
    review_parser.add_argument("id")
    review_parser.set_defaults(offline=cmd_review)

    stale_parser = commands.add_parser(
        "stale",
        help="life stories whose record (or family, children) changed after the story",
    )
    stale_parser.add_argument("id", nargs="*", help="only these persons")
    stale_parser.add_argument("--short", action="store_true", help="IDs only")
    stale_parser.add_argument(
        "--checked",
        action="store_true",
        help="record that these persons' stories were reviewed and needed no change",
    )
    stale_parser.add_argument(
        "--direct-line",
        action="store_true",
        help="in the direct line (line_root) also count changes in the parents' family",
    )
    stale_parser.set_defaults(run=cmd_stale)

    requests_parser = commands.add_parser(
        "requests",
        help="mails to archives that only a human can send (the requests folder)",
    )
    requests_parser.add_argument("--all", action="store_true", help="also answered and closed")
    requests_parser.add_argument(
        "--person", help="only requests about this person (ID), with their replies"
    )
    requests_parser.add_argument(
        "--text", action="store_true", help="the drafts to send, with the full mail text"
    )
    requests_parser.add_argument(
        "--mark",
        nargs=2,
        metavar=("NAME", "STATUS"),
        help="set the status: on_hold, sent, answered or closed (with today's date)",
    )
    requests_parser.set_defaults(run=cmd_requests)

    mail_parser = commands.add_parser(
        "mail", help="send requests after the user's approval, and fetch replies"
    )
    mail_commands = mail_parser.add_subparsers(dest="mail_command", required=True)
    mail_commands.add_parser("test", help="check that SMTP and IMAP logins work").set_defaults(
        offline=cmd_mail
    )
    mail_send = mail_commands.add_parser("send", help="send a draft request")
    mail_send.add_argument("name", help="name (or start) of the file in the requests folder")
    mail_send.add_argument(
        "--approved", action="store_true", help="the user has approved this draft"
    )
    mail_send.set_defaults(offline=cmd_mail)
    mail_commands.add_parser(
        "inbox",
        help="save new mail in <requests>/replies/ and mark it as read",
    ).set_defaults(offline=cmd_mail)

    gramps_parser = commands.add_parser(
        "gramps", help="Gramps Web: the tree, open questions as tasks, blog"
    )
    gramps_commands = gramps_parser.add_subparsers(dest="gramps_command", required=True)
    gramps_commands.add_parser("status", help="login, role and counts").set_defaults(
        offline=cmd_gramps
    )
    gramps_sync = gramps_commands.add_parser(
        "sync",
        help="make Gramps Web match the tree, the open questions, the blog and the life stories "
        "(only what differs)",
    )
    gramps_sync.add_argument("--dry-run", action="store_true", help="only count what would change")
    gramps_sync.add_argument(
        "--overwrite",
        nargs="+",
        default=[],
        metavar="ID",
        help="our version wins for these IDs (with their events and sources), "
        "even after a change in Gramps Web",
    )
    gramps_sync.set_defaults(offline=cmd_gramps)

    coordinates_parser = commands.add_parser(
        "coordinates",
        help=f"coordinates for places and addresses ({coordinates.TABLE.name} next to the tree), "
        "offline from GeoNames and OSM",
    )
    coordinates_commands = coordinates_parser.add_subparsers(
        dest="coordinates_command", required=True
    )
    coordinates_commands.add_parser(
        "index", help="download GeoNames and OpenStreetMap and build the local index (once)"
    ).set_defaults(offline=cmd_coordinates)
    coordinates_search = coordinates_commands.add_parser(
        "search", help="candidates for a place or an address"
    )
    coordinates_search.add_argument(
        "place", help="as in the GEDCOM, e.g. 'Springfield, Noord-Brabant, Nederland'"
    )
    coordinates_search.add_argument("--address", help="as in ADDR/ADR1, e.g. 'Kerkstraat 12'")
    coordinates_search.add_argument(
        "--year", type=int, help="year of the address; exact only from 1940"
    )
    coordinates_search.set_defaults(offline=cmd_coordinates)
    coordinates_fill = coordinates_commands.add_parser(
        "fill", help="add rows for everything that has no coordinates yet"
    )
    coordinates_fill.add_argument("--dry-run", action="store_true", help="only show")
    coordinates_fill.set_defaults(offline=cmd_coordinates)

    book_parser = commands.add_parser(
        "book", help="book of life stories along the paternal line of father and mother"
    )
    book_parser.add_argument("id")
    book_parser.add_argument("--out", type=Path, help="output file (default <books>/<ID>.md)")
    book_parser.add_argument(
        "--youngest-first", action="store_true", help="within each part from the parent upwards"
    )
    book_parser.set_defaults(run=cmd_book)

    kinship_parser = commands.add_parser(
        "kinship", help="kinship with the target persons in lineage.toml"
    )
    kinship_parser.add_argument("id")
    kinship_parser.add_argument("--to", nargs="+", help="other persons than the targets")
    kinship_parser.set_defaults(run=cmd_kinship)

    paternal_parser = commands.add_parser(
        "paternal",
        help="the paternal line; with --notify a mail draft to the user when it grows longer",
    )
    paternal_parser.add_argument(
        "--from",
        dest="start",
        help="default [paternal_line] start, else the first male target person",
    )
    paternal_parser.add_argument(
        "--notify", action="store_true", help="compare with the previous state"
    )
    paternal_parser.add_argument("--state", type=Path, help="default <git-common-dir>/dr-paternal")
    paternal_parser.set_defaults(run=cmd_paternal)

    map_parser = commands.add_parser(
        "question-map",
        help="heatmap of open questions per generation and line (page for the artifact)",
    )
    map_parser.add_argument("--from", dest="start", help="default line_root")
    map_parser.add_argument("--questions", type=Path)
    map_parser.add_argument("--history", type=Path)
    map_parser.add_argument("--out", type=Path)
    map_parser.set_defaults(run=cmd_question_map)

    queue_parser = commands.add_parser("queue", help="deep-research queue, per person")
    queue_parser.add_argument("--queue", type=Path, help="default: the queue in lineage.toml")
    queue_commands = queue_parser.add_subparsers(dest="queue_command", required=True)
    queue_show = queue_commands.add_parser("show", help="open and running items")
    queue_show.add_argument(
        "--all", action="store_true", help="also done, skipped and side branches"
    )
    queue_show.add_argument(
        "--side-branches", action="store_true", help="also open items outside the direct line"
    )
    queue_show.set_defaults(run=cmd_queue_show)
    queue_add = queue_commands.add_parser("add", help="add persons (existing ones stay)")
    queue_add.add_argument("ids", nargs="+")
    queue_add.add_argument(
        "--via", default="", help="ID of the person whose research produced this"
    )
    queue_add.add_argument("--reason", default="")
    queue_add.add_argument("--priority", type=int, default=5, help="1 = first")
    queue_add.add_argument("--round", type=int, default=1)
    queue_add.set_defaults(run=cmd_queue_add)
    queue_next = queue_commands.add_parser(
        "next", help="next open ancestor of line_root that does not clash with running work"
    )
    queue_next.add_argument(
        "--side-branches", action="store_true", help="also persons outside the direct line"
    )
    queue_next.set_defaults(run=cmd_queue_next)
    queue_start = queue_commands.add_parser(
        "start", help="mark as in progress and assign an ID block"
    )
    queue_start.add_argument("id")
    queue_start.add_argument("--force", action="store_true", help="even with a shared family")
    queue_start.add_argument(
        "--follow-up", action="store_true", help="follow-up round for a person who is already done"
    )
    queue_start.set_defaults(run=cmd_queue_start)
    queue_done = queue_commands.add_parser("done", help="mark as done")
    queue_done.add_argument("id")
    queue_done.add_argument("--report", required=True)
    queue_done.add_argument(
        "--date",
        type=dt.date.fromisoformat,
        default=dt.date.today(),
        help="date of the research (yyyy-mm-dd), default today",
    )
    queue_done.add_argument(
        "--no-note",
        action="store_true",
        help="do not add the 'Deep research <date>' note (update round of the life story only)",
    )
    queue_done.set_defaults(run=cmd_queue_done)
    queue_skip = queue_commands.add_parser("skip", help="do not research")
    queue_skip.add_argument("id")
    queue_skip.add_argument("--reason", required=True)
    queue_skip.set_defaults(run=cmd_queue_skip)
    queue_commands.add_parser(
        "normalize", help="merge duplicate rows after a git merge and sort"
    ).set_defaults(run=cmd_queue_normalize)

    archive_parser = commands.add_parser("archive", help="search and view records on Open Archives")
    archive_commands = archive_parser.add_subparsers(dest="archive_command", required=True)
    archive_search = archive_commands.add_parser(
        "search",
        help="search by name; year range ('1850-1860') and '&' between two persons allowed",
    )
    archive_search.add_argument("name", nargs="+")
    archive_search.add_argument("--type", default="", help="event, e.g. Huwelijk, Doop, Overlijden")
    archive_search.add_argument("--place", default="")
    archive_search.add_argument("--role", default="", help="e.g. Bruid, Kind, Overledene, Vader")
    archive_search.add_argument("--source", default="", help="source type, e.g. 'BS Geboorte'")
    archive_search.add_argument("--limit", type=int, default=20)
    archive_search.set_defaults(offline=cmd_archive_search)
    archive_show = archive_commands.add_parser("show", help="full record, e.g. bhi:2a9ebb9a-...")
    archive_show.add_argument("ref")
    archive_show.add_argument(
        "--gedcom", action="store_true", help="show the source record and citation"
    )
    archive_show.set_defaults(offline=cmd_archive_show)

    rat_parser = commands.add_parser(
        "rat", help="Regionaal Archief Tilburg: inventory items, download scans, crops"
    )
    rat_commands = rat_parser.add_subparsers(dest="rat_command", required=True)
    fonds_help = "RAT fonds, e.g. 929 Schepenbank Dongen, 962 's-Gravenmoer (default [rat] fonds)"
    rat_search = rat_commands.add_parser("search", help="search the titles of inventory items")
    rat_search.add_argument("terms", nargs="+")
    rat_search.add_argument("--fonds", help=fonds_help)
    rat_search.add_argument("--limit", type=int, default=25)
    rat_search.set_defaults(offline=cmd_rat_search)
    rat_item = rat_commands.add_parser(
        "item", help="title, dating and scans of an inventory number"
    )
    rat_item.add_argument("inventory")
    rat_item.add_argument("--fonds", help=fonds_help)
    rat_item.add_argument("--scans", action="store_true", help="also the list of scans and URLs")
    rat_item.set_defaults(offline=cmd_rat_item)
    rat_download = rat_commands.add_parser(
        "download", help="scans to <dir>/<fonds>-<inv>/<nr>.jpg; existing ones are skipped"
    )
    rat_download.add_argument("inventory")
    rat_download.add_argument("--fonds", help=fonds_help)
    rat_download.add_argument("--scans", default="", help="e.g. '98' or '1-25,40'; default all")
    rat_download.add_argument("--dir", type=Path, help="default <output>/scans")
    rat_download.set_defaults(offline=cmd_rat_download)
    rat_throttle = rat_commands.add_parser(
        "throttle", help="shared throttle on RAT traffic: state, probe request, release a lockout"
    )
    rat_throttle.add_argument(
        "--test", action="store_true", help="one probe request, also during a lockout"
    )
    rat_throttle.add_argument("--release", action="store_true", help="release the lockout by hand")
    rat_throttle.set_defaults(offline=cmd_rat_throttle)
    rat_crop = rat_commands.add_parser(
        "crop", help="grey, contrast-enhanced crop; frame as fractions of the page"
    )
    rat_crop.add_argument("image", type=Path)
    rat_crop.add_argument("frame", type=float, nargs=4, metavar=("X0", "Y0", "X1", "Y1"))
    rat_crop.add_argument("--out", type=Path)
    rat_crop.add_argument("--scale", type=float, default=1.0)
    rat_crop.set_defaults(offline=cmd_rat_crop)

    guard_parser = commands.add_parser(
        "guard",
        help="keeps running deep-research rounds going across usage limits (own Herdr tab)",
    )
    guard_parser.add_argument("--interval", type=int, default=120, help="seconds between rounds")
    guard_parser.add_argument("--once", action="store_true", help="one round, then stop")
    guard_parser.add_argument(
        "--dry-run", action="store_true", help="show decisions, start or record nothing"
    )
    guard_parser.add_argument(
        "--coordinator",
        action="store_true",
        help="also watch a coordinator session and start it if needed (lineage round start-coordinator)",
    )
    guard_parser.set_defaults(offline=cmd_guard)

    scan_parser = commands.add_parser(
        "scan",
        help="fetch the scan of an Open Archives record (or viewer URL) at full resolution, with provenance",
    )
    scan_parser.add_argument(
        "refs", nargs="+", help="e.g. rmd:7E5A85EB-..., bhi:2a22de12-..., or a URL"
    )
    scan_parser.add_argument(
        "--dir", type=Path, help="target folder (default: scans in lineage.toml)"
    )
    scan_parser.add_argument(
        "--max",
        type=int,
        default=scan.MAX_SET,
        help="at most this many scans when a record has no scan of its own but a whole record page",
    )
    scan_parser.set_defaults(offline=cmd_scan)

    htr_parser = commands.add_parser(
        "htr",
        help="text recognition through Transkribus (costs credits); text and PAGE XML in <scan folder>/htr/",
    )
    htr_parser.add_argument(
        "images", nargs="*", type=Path, help="scans (jpg/png/tif, at most 20 MB)"
    )
    htr_parser.add_argument(
        "--model",
        type=_htr_model,
        default=htr.DUTCHESS_I,
        help=f"Transkribus model: {htr.MODEL_HELP}; a model other than the default "
        "writes to <scan>.<model>.txt",
    )
    htr_parser.add_argument(
        "--count",
        action="store_true",
        help="show the number of recognitions and the credit balance",
    )
    htr_parser.add_argument(
        "--since",
        type=dt.date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="with --count: from this date",
    )
    htr_parser.add_argument(
        "--max",
        type=int,
        default=htr.MAX_IMAGES,
        help="refuse when there are more new scans than this (credits)",
    )
    htr_parser.add_argument("--dry-run", action="store_true", help="only count what is new")
    htr_parser.set_defaults(offline=cmd_htr)

    forum_parser = commands.add_parser(
        "forum",
        help="read questions on the Geneanet forum (died before 1900): post a draft, read replies",
    )
    forum_commands = forum_parser.add_subparsers(dest="forum_command", required=True)
    forum_post = forum_commands.add_parser(
        "post", help="post a draft from the forum folder as a new topic"
    )
    forum_post.add_argument("draft", type=Path)
    forum_post.add_argument(
        "--preview", action="store_true", help="only show the preview, do not post"
    )
    forum_post.set_defaults(offline=cmd_forum)
    forum_read = forum_commands.add_parser(
        "read", help="fetch new replies and add them to the draft file"
    )
    forum_read.add_argument("--dir", type=Path, help="default: forum in lineage.toml")
    forum_read.set_defaults(offline=cmd_forum)
    return parser


def _file_first(argv: list[str]) -> list[str]:
    """`--file` is an option of lineage itself, but people and agents also put it after the command."""
    for i, arg in enumerate(argv):
        if arg == "--file" and i + 1 < len(argv):
            return [arg, argv[i + 1], *argv[:i], *argv[i + 2 :]]
        if arg.startswith("--file="):
            return [arg, *argv[:i], *argv[i + 1 :]]
    return argv


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(_file_first(sys.argv[1:] if argv is None else argv))
    try:
        return _run(args)
    except settings.ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2


def _run(args: argparse.Namespace) -> int:
    if hasattr(args, "offline"):
        try:
            return args.offline(args)
        except (
            archive.ArchiveError,
            rat.RatError,
            mail.MailError,
            requests.RequestError,
            forum.ForumError,
            browser.BrowserError,
            gramps.GrampsError,
            htr.HtrError,
        ) as exc:
            print(exc, file=sys.stderr)
            return 2
    args.file = _tree_file(args)
    try:
        tree = load(args.file)
    except FileNotFoundError:
        print(t("file not found: {file}", file=args.file), file=sys.stderr)
        return 2
    except GedcomError as exc:
        print(t("invalid GEDCOM file: {error}", error=exc), file=sys.stderr)
        return 2
    try:
        return args.run(tree, args)
    except queue.QueueError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

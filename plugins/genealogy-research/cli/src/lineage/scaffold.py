"""`lineage init`: lineage.toml and the empty research files of a new project. Existing files stay as they are."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from lineage import queue, settings
from lineage.gedcom import Tree
from lineage.i18n import t

QUESTION_HEADINGS = {
    "en": (
        "Choices for the user",
        "To research with online sources",
        "On site only or with a full-resolution scan",
        "Living persons or recent (do not look up)",
        "Solved",
    ),
    "nl": (
        "Keuzes voor de gebruiker",
        "Uit te zoeken met online bronnen",
        "Alleen ter plaatse of met scan op volle resolutie",
        "Levende personen of recent (niet opzoeken)",
        "Opgelost",
    ),
}


def project_text(c: settings.Config, tree: Tree | None, exceptions: list[str]) -> str:
    def label(pid: str) -> str:
        person = tree.persons.get(pid) if tree else None
        return f"{person.name} ({pid})" if person else pid

    targets = "\n".join(f"- {target.label}: {label(target.id)}" for target in c.targets) or t(
        "- (none yet)"
    )
    if c.line_root:
        targets += "\n" + t("- Direct line: the ancestors of {person}.", person=label(c.line_root))
    allowed = "".join(t("- Exception: {text}", text=e) + "\n" for e in exceptions)
    return t(
        """# Project agreements for genealogy research

The research skills read this file first. What is written here overrides a general example in a skill.

## Privacy

- The tree contains living persons. Publish nothing and send no data about living persons to external
  services.
{exceptions}
## Target persons

{targets}
""",
        exceptions=allowed,
        targets=targets,
    )


def questions_text(language: str) -> str:
    headings = QUESTION_HEADINGS.get(language, QUESTION_HEADINGS["en"])
    body = "".join(f"\n## {h}\n" for h in headings)
    return (
        t("# Open questions")
        + "\n\n"
        + t("Format: `- [ ] I123 Name: question (what was tried)`")
        + "\n"
        + body
    )


def check(c: settings.Config, tree: Tree | None) -> list[str]:
    """Problems with the settings: persons that are not in the tree, a missing tree."""
    problems = []
    if tree is None:
        problems.append(t("tree not found: {path}", path=c.rel("gedcom")))
        return problems
    ids = [("targets", t.id) for t in c.targets] + [("stems", s.id) for s in c.stems]
    ids += [
        (k, v)
        for k, v in (("line_root", c.line_root), ("paternal_line start", c.paternal_start))
        if v
    ]
    for key, pid in ids:
        if pid not in tree.persons:
            problems.append(t("{key}: {pid} is not in the tree", key=key, pid=pid))
    if not c.targets:
        problems.append(t("no target persons ('targets')"))
    return problems


def write(
    c: settings.Config, tree: Tree | None, exceptions: list[str], overwrite_config: bool = False
) -> list[Path]:
    """Writes lineage.toml and the research files that do not exist yet; returns what was written."""
    written = []
    file = c.root / settings.FILE
    if file.exists() and not overwrite_config:
        raise settings.ConfigError(t("{file} exists; use --update to change it", file=file))
    file.write_text(settings.dump(c), encoding="utf-8")
    written.append(file)
    for key in ("research", "requests", "person_reports", "life_stories"):
        c.path(key).mkdir(parents=True, exist_ok=True)
    files = {
        "queue": None,
        "log": t("# Research log") + "\n",
        "questions": questions_text(c.language),
        "project": project_text(c, tree, exceptions),
    }
    for key, text in files.items():
        path = c.path(key)
        if path.exists():
            continue
        if text is None:
            queue.save({}, path)
        else:
            path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def merged(base: settings.Config, **changes) -> settings.Config:
    """base with every change that was given (None and empty mean: keep)."""
    return replace(base, **{k: v for k, v in changes.items() if v not in (None, (), {}, "")})

"""Describe how a person is related to a reference person, in English genealogical terms."""

from __future__ import annotations

from collections import deque

from lineage.gedcom import Person, Tree
from lineage.i18n import language, t

# Beyond twelve generations a numbered phrase is clearer than a pile of "great-".
ANCESTOR_TERMS = {
    "en": ["", "{}", "grand{}", *("great-" * (n - 2) + "grand{}" for n in range(3, 13))],
    "nl": [
        "", "{}", "groot{}", "overgroot{}", "betovergroot{}", "oud{}", "oudgroot{}", "oudovergroot{}",
        "oudbetovergroot{}", "stam{}", "stamgroot{}", "stamovergroot{}", "stambetovergroot{}",
    ],
}  # fmt: skip
DESCENDANT_TERMS = {
    "en": {1: "{}", 2: "grand{}", 3: "great-grand{}"},
    "nl": {1: "{}", 2: "klein{}", 3: "achterklein{}"},
}


def _parent_word(person: Person) -> str:
    return {"M": t("father"), "F": t("mother")}.get(person.sex) or t("parent")


def _child_word(person: Person) -> str:
    return {"M": t("son"), "F": t("daughter")}.get(person.sex) or t("child")


def _sibling_word(person: Person) -> str:
    return {"M": t("brother"), "F": t("sister")}.get(person.sex) or t("sibling")


def ancestor_term(person: Person, generation: int) -> str:
    word = _parent_word(person)
    terms = ANCESTOR_TERMS.get(language(), ANCESTOR_TERMS["en"])
    if generation < len(terms):
        return terms[generation].format(word)
    if language() == "nl":
        return f"voor{word} in de {generation}e generatie"
    return t("ancestor in generation {generation}", generation=generation)


def descendant_term(person: Person, depth: int) -> str:
    base = DESCENDANT_TERMS.get(language(), DESCENDANT_TERMS["en"])
    if depth in base:
        return base[depth].format(_child_word(person) if depth == 1 else t("child"))
    return t("descendant in generation {depth}", depth=depth)


def _parents(tree: Tree, pid: str) -> list[str]:
    return [p.id for p in tree.parents(pid) if p]


def ancestors(tree: Tree, root: str) -> dict[str, int]:
    """Every ancestor of root (and root itself) with its smallest generation distance."""
    found = {root: 0}
    queue = deque([root])
    while queue:
        pid = queue.popleft()
        for parent in _parents(tree, pid):
            if parent not in found:
                found[parent] = found[pid] + 1
                queue.append(parent)
    return found


def _path_down(tree: Tree, ancestor: str, target: str) -> list[str]:
    """Ancestor -> ... -> target via children, shortest path."""
    queue = deque([[ancestor]])
    seen = {ancestor}
    while queue:
        path = queue.popleft()
        if path[-1] == target:
            return path
        for family in tree.spouse_families(path[-1]):
            for child in tree.children(family):
                if child.id not in seen:
                    seen.add(child.id)
                    queue.append([*path, child.id])
    return []


def _self() -> str:
    return t("the person themselves")


def _blood(tree: Tree, pid: str, ref: str) -> str | None:
    if pid == ref:
        return _self()
    ref_up = ancestors(tree, ref)
    person = tree.persons[pid]
    if pid in ref_up:
        return ancestor_term(person, ref_up[pid])
    pid_up = ancestors(tree, pid)
    if ref in pid_up:
        return descendant_term(person, pid_up[ref])
    common = [a for a in pid_up if a in ref_up]
    if not common:
        return None
    best = min(common, key=lambda a: (ref_up[a] + pid_up[a], ref_up[a]))
    up_ref = ref_up[best]
    path_ref = _path_down(tree, best, ref)
    path_pid = _path_down(tree, best, pid)
    if len(path_ref) < 2 or len(path_pid) < 2:
        return None
    ref_side = tree.persons[path_ref[1]]
    pid_side = tree.persons[path_pid[1]]
    if up_ref == 1:
        anchor = t("you")
    else:
        anchor = t("your {term} {name}", term=ancestor_term(ref_side, up_ref - 1), name=ref_side.name)
    text = t("{sibling} of {anchor}", sibling=_sibling_word(pid_side), anchor=anchor)
    for step in path_pid[2:]:
        text = t("{child} of the {text}", child=_child_word(tree.persons[step]), text=text)
    return text


def describe(tree: Tree, pid: str, ref: str) -> str | None:
    """Relationship of pid to ref, or None when there is no link by blood or marriage."""
    blood = _blood(tree, pid, ref)
    if blood:
        return blood
    for family in tree.spouse_families(pid):
        partner = tree.partner(family, pid)
        if partner:
            via = _blood(tree, partner.id, ref)
            if via and via != _self():
                word = {"M": t("husband"), "F": t("wife")}.get(tree.persons[pid].sex) or t("partner")
                return t("{word} of {partner}, {via}", word=word, partner=partner.name, via=via)
            if via == _self():
                return t("partner")
    return None

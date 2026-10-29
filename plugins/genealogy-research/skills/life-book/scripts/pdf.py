"""Turn a life book (Markdown from `lineage book`) into a PDF with title page, contents and page numbers.

Usage (from the project):
    uv run --with markdown-it-py --with typst python <plugin>/skills/life-book/scripts/pdf.py <books folder>/I1.md

Typst (the Python package bundles the compiler and fonts) needs no system libraries.
Writes <book>.pdf next to the Markdown file; with --typ the Typst source is kept too.
The book may be in English or Dutch: `lineage book` writes the project language and this script
recognises the headings of either.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import typst
from markdown_it import MarkdownIt
from markdown_it.token import Token

_MD = MarkdownIt("commonmark").enable("table")
_SPECIAL = re.compile(r"([\\#$*_`<>@\[\]~=/])")
_ANCHOR = re.compile(r'<a id="([^"]+)"></a>')

PREAMBLE = r"""
#set document(title: "%(title)s")
#set text(font: ("Libertinus Serif", "New Computer Modern"), size: 10.5pt, lang: "%(lang)s", hyphenate: true)
#set par(justify: true, leading: 0.68em, spacing: 0.95em)
#set page(paper: "a4", margin: (x: 22mm, top: 22mm, bottom: 24mm),
  footer: context { if counter(page).get().first() > 1 [ #align(center, text(size: 8.5pt, fill: luma(110), counter(page).display())) ] })
#show heading.where(level: 1): it => { pagebreak(weak: true); v(70mm); align(center, text(size: 24pt, weight: "regular", it.body)); pagebreak(weak: true) }
#show heading.where(level: 2): it => { pagebreak(weak: true); block(below: 1.1em, text(size: 19pt, weight: "regular", it.body)) }
#show heading.where(level: 3): it => block(above: 1.3em, below: 0.6em, text(size: 12.5pt, weight: "semibold", it.body))
#show heading.where(level: 4): it => block(above: 1.1em, below: 0.5em, text(size: 11pt, weight: "semibold", it.body))
#show quote.where(block: true): it => block(inset: (left: 1em), stroke: (left: 1.5pt + rgb("#3f5f7a")), it.body)
#show link: it => it
#show raw: set text(size: 8.5pt)

#page(footer: none)[
  #v(1fr)
  #align(center)[
    #text(size: 28pt)[%(title)s]
    #v(1.5em)
    #block(width: 120mm)[#set par(justify: false); #text(size: 11pt, fill: luma(80))[%(intro)s]]
  ]
  #v(1.2fr)
]

#block(below: 1.2em, text(size: 19pt)[%(contents)s])
#outline(title: none, depth: 2, indent: 1.2em)
"""


LANGUAGES = {
    "en": {"contents": "Contents", "line_to": "Line to "},
    "nl": {"contents": "Inhoud", "line_to": "Lijn naar "},
}


def detect_language(md_text: str) -> str:
    """The language `lineage book` wrote the book in, from its contents heading."""
    for code, words in LANGUAGES.items():
        if f"\n## {words['contents']}\n" in md_text:
            return code
    raise ValueError("not a life book: no contents heading ('## Contents' or '## Inhoud')")


def _esc(text: str) -> str:
    # "-?", "--" and "..." are Typst shorthands (soft hyphen, dashes, ellipsis); keep them literal.
    text = _SPECIAL.sub(r"\\\1", text)
    return re.sub(r"-(?=[-?])", r"\\-", text).replace("...", "\\.\\.\\.")


def _str(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


class Converter:
    def __init__(self, labels: set[str]) -> None:
        self.labels = labels

    def inline(self, tokens: list[Token]) -> str:
        out: list[str] = []
        link_stack: list[str] = []
        for tok in tokens:
            t = tok.type
            if t == "text":
                out.append(_esc(tok.content))
            elif t in ("softbreak", "hardbreak"):
                out.append(" " if t == "softbreak" else " \\\n")
            elif t == "em_open":
                out.append("#emph[")
            elif t == "strong_open":
                out.append("#strong[")
            elif t in ("em_close", "strong_close"):
                out.append("]")
            elif t == "code_inline":
                out.append(f'#raw("{_str(tok.content)}")')
            elif t == "link_open":
                href = tok.attrs.get("href", "")
                if href.startswith("#"):
                    target = href[1:]
                    if target in self.labels:
                        out.append(f"#link(<{target}>)[")
                        link_stack.append("]")
                    else:
                        link_stack.append("")
                else:
                    out.append(f'#link("{_str(href)}")[')
                    link_stack.append("]")
            elif t == "link_close":
                out.append(link_stack.pop() if link_stack else "")
            elif t == "image":
                src = tok.attrs.get("src", "")
                out.append(f'#image("{_str(src)}")')
            elif t == "html_inline":
                continue
        return "".join(out)

    def blocks(self, tokens: list[Token]) -> str:
        out: list[str] = []
        i = 0
        list_stack: list[str] = []
        while i < len(tokens):
            tok = tokens[i]
            t = tok.type
            if t == "heading_open":
                level = int(tok.tag[1])
                content = self.inline(tokens[i + 1].children or [])
                out.append(f"\n{'=' * level} {content}\n")
                i += 3
                continue
            if t == "paragraph_open":
                inline = tokens[i + 1].children or []
                content = self.inline(inline)
                images = [c for c in inline if c.type == "image"]
                if images and len([c for c in inline if c.type not in ("image", "softbreak")]) == 0:
                    caption = self._caption(tokens, i + 3)
                    out.append(
                        f"\n#figure({content.replace('#image', 'image', 1)}"
                        + (f", caption: [{caption[0]}]" if caption else "")
                        + ")\n"
                    )
                    i += 3 + (caption[1] if caption else 0)
                    continue
                out.append(("  " * len(list_stack)) + content + "\n" if list_stack else f"\n{content}\n")
                i += 3
                continue
            if t in ("bullet_list_open", "ordered_list_open"):
                list_stack.append("-" if t == "bullet_list_open" else "+")
            elif t in ("bullet_list_close", "ordered_list_close"):
                list_stack.pop()
                out.append("\n")
            elif t == "list_item_open":
                out.append(f"{'  ' * (len(list_stack) - 1)}{list_stack[-1]} ")
                if tokens[i + 1].type == "paragraph_open":
                    out.append(self.inline(tokens[i + 2].children or []) + "\n")
                    i += 4
                    continue
            elif t == "blockquote_open":
                depth, j = 1, i + 1
                while depth:
                    depth += {"blockquote_open": 1, "blockquote_close": -1}.get(tokens[j].type, 0)
                    j += 1
                out.append(f"\n#quote(block: true)[{self.blocks(tokens[i + 1 : j - 1]).strip()}]\n")
                i = j
                continue
            elif t == "table_open":
                j = i
                while tokens[j].type != "table_close":
                    j += 1
                out.append(self._table(tokens[i:j]))
                i = j + 1
                continue
            elif t == "hr":
                out.append("\n#line(length: 100%, stroke: 0.4pt + luma(180))\n")
            elif t in ("code_block", "fence"):
                out.append(f'\n#raw("{_str(tok.content)}", block: true)\n')
            i += 1
        return "".join(out)

    def _caption(self, tokens: list[Token], i: int) -> tuple[str, int] | None:
        """An image paragraph followed by a paragraph that is only italic text is its caption."""
        if i + 1 < len(tokens) and tokens[i].type == "paragraph_open":
            kids = tokens[i + 1].children or []
            if kids and kids[0].type == "em_open" and kids[-1].type == "em_close":
                return self.inline(kids[1:-1]), 3
        return None

    def _table(self, tokens: list[Token]) -> str:
        rows: list[list[str]] = []
        for k, tok in enumerate(tokens):
            if tok.type == "tr_open":
                rows.append([])
            elif tok.type == "inline" and rows:
                rows[-1].append(f"[{self.inline(tok.children or [])}]")
        cols = max((len(r) for r in rows), default=1)
        cells = ", ".join(c for r in rows for c in r + ["[]"] * (cols - len(r)))
        return f"\n#text(size: 9pt, table(columns: {cols}, stroke: 0.4pt + luma(190), inset: 4pt, {cells}))\n"


def to_typst(md_text: str) -> str:
    lang = detect_language(md_text)
    words = LANGUAGES[lang]
    title_line, rest = md_text.split("\n", 1)
    title = title_line.removeprefix("# ").strip()
    intro, rest = rest.split(f"## {words['contents']}", 1)
    _, body = rest.split("\n# ", 1)
    body = "# " + body
    labels = set(_ANCHOR.findall(body))
    conv = Converter(labels)
    intro_typ = conv.inline(_MD.parseInline(intro.strip())[0].children or []) if intro.strip() else ""
    out = [PREAMBLE % {"title": _str(title), "intro": intro_typ, "lang": lang, "contents": words["contents"]}]
    # Every chapter starts with its anchor; the heading right after it carries the label.
    for chunk in re.split(r"(?=<a id=\")", body):
        anchor = _ANCHOR.match(chunk)
        text = _ANCHOR.sub("", chunk, count=1).strip("\n")
        marker = f"\n### {words['line_to']}"
        story, sep, support = text.partition(marker)
        typ = conv.blocks(_MD.parse(story))
        if anchor:
            typ = re.sub(r"^\n== (.*)\n", lambda m: f"\n== {m[1]} <{anchor[1]}>\n", typ, count=1)
        out.append(typ)
        if sep:
            # The support of the last chapter of a part runs into the next part's heading; keep that outside.
            support, nxt, after = support.partition("\n# ")
            support_typ = conv.blocks(_MD.parse(marker.lstrip("\n") + support))
            out.append(
                "\n#block(above: 1.6em, stroke: (top: 0.5pt + luma(170)), inset: (top: 0.6em))[\n"
                "#set text(size: 9pt)\n#set par(justify: false)\n" + support_typ + "\n]\n"
            )
            if nxt:
                out.append(conv.blocks(_MD.parse("# " + after)))
    return "".join(out)


def _project_root(source: Path) -> Path:
    """Typst may only read below its root; the book refers to images in sibling folders."""
    for folder in source.parents:
        if (folder / "lineage.toml").exists() or (folder / ".git").exists():
            return folder
    return source.parent


def main(path: str, keep_typ: bool = False) -> Path:
    source = Path(path).resolve()
    root = _project_root(source)
    typ = source.with_suffix(".typ")
    typ.write_text(to_typst(source.read_text(encoding="utf-8")), encoding="utf-8")
    out = source.with_suffix(".pdf")
    try:
        typst.compile(str(typ), output=str(out), root=str(root))
    finally:
        if not keep_typ:
            typ.unlink(missing_ok=True)
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        sys.exit("usage: pdf.py <book.md> [--typ]\n" + (__doc__ or ""))
    print(main(sys.argv[1], keep_typ="--typ" in sys.argv[2:]))

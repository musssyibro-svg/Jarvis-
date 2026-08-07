#!/usr/bin/env python3
"""
tools/codemap.py — a structural index of the codebase, built from the AST.

WHY THIS EXISTS, AND WHY IT ISN'T A FOURTH SEARCH TOOL.

This repo already has three ways to look at code, and they answer different
questions. Adding a fourth that overlaps would be worse than having none,
because they'd disagree:

    Serena (MCP)        "where is X defined, and who calls it?"   — semantic,
                        via a language server. Resolves through the lazy
                        `from services import x` imports used all over Jarvis.
    Semgrep (.semgrep)  "does this PATTERN appear anywhere?"      — syntactic,
                        for enforcing the rules in CLAUDE.md.
    ripgrep             "where does this string appear?"          — literal.

None of them answers the first question anyone actually has, human or model:
**what is in here, and where do I start?**

`JARVIS_FULL_SOURCE.txt` was the previous answer. It is 1.4 MB of concatenated
source. It is a complete answer and a useless one — nobody, and no context
window, reads it to orient. This produces one page instead: every module, its
purpose in one line taken from its own docstring, and its public surface.

WHY TREE-SITTER RATHER THAN `ast`:
Python's stdlib `ast` handles the backend perfectly. It cannot read the React
frontend at all, and .jsx needs a real parser (a regex for `export default
function` gets it wrong the moment a component is defined as a const arrow).
tree-sitter parses Python, JS, TS and JSX with one API, so this is one script
rather than two that drift apart.

Run:  python tools/codemap.py
Writes: docs/CODEMAP.md
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "CODEMAP.md"

# Directories that are not source. `verification/` IS listed — those scripts
# are part of how this project is checked, and leaving them off the map is how
# people forget they exist.
SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", "dist", "build", ".venv", "venv",
    "browser-profile", "screenshots", ".serena", ".ruff_cache", ".pytest_cache",
    "scratchpad",
}

LANG_FOR_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".mjs": "javascript",
}

# What each top-level area is for. Written by hand because a docstring can say
# what a MODULE does but nothing in the code says what a FOLDER is for, and
# that's the level at which someone new is lost.
AREAS = {
    "backend/agents": "The things that act. One orchestrator owns the state "
                      "machine; the rest are workers it drives.",
    "backend/services": "The things that decide, remember and explain. No I/O "
                        "with the user; called by agents and routes.",
    "backend/routes": "HTTP surface. Thin — routes translate, they don't think.",
    "backend/providers": "The ONLY place a vendor SDK is imported. Enforced by "
                         ".semgrep/jarvis.yml.",
    "backend/models": "SQLite schema and connection handling.",
    "backend/platforms": "One module per freelance site. Scraping lives here.",
    "backend/adapters": "Glue between the chat surface and the agents.",
    "backend/core": "Cross-cutting primitives (the browser lock).",
    "backend/tests": "Offline unit tests. Every case is a bug that reached the "
                     "user once.",
    "frontend/src": "The React console. A CLIENT of the backend, never a place "
                    "where logic lives.",
    "frontend/src/pages": "One file per screen.",
    "tools": "Developer commands. Not shipped as part of the running system.",
    "verification": "Manual scripts that need a LIVE backend. Not pytest — see "
                    "pyproject.toml for why.",
}


def _parsers():
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        sys.exit(
            "This needs tree-sitter:\n"
            "    pip install tree-sitter tree-sitter-language-pack\n"
            "Jarvis itself runs fine without it — this is a developer tool."
        )
    cache: dict[str, object] = {}

    def get(lang: str):
        if lang not in cache:
            cache[lang] = get_parser(lang)
        return cache[lang]

    return get


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _strip_filename_prefix(line: str) -> str:
    """
    Most docstrings here open `services/foo.py — what it does`. The filename is
    already the heading; repeating it wastes the one line we have for meaning.
    A line that is ONLY a filename yields nothing, so the next line is tried.
    """
    import re as _re
    m = _re.match(r"^\s*(?:backend/|frontend/|tools/)?[\w./+-]+\.(?:py|jsx?|tsx?)\s*"
                  r"(?:[—–\-:]{1,2})\s*(.+)$", line)
    if m:
        return m.group(1).strip()
    if _re.fullmatch(r"[\w./+-]+\.(?:py|jsx?|tsx?)", line.strip()):
        return ""
    return line


def _first_docstring_line(src: bytes, lang: str) -> str:
    """
    The module's own one-line summary.

    Module docstrings are where the reasoning lives in this project (CLAUDE.md
    says so), so the first sentence of one is a better description than
    anything this script could infer.
    """
    text = src.decode("utf-8", "replace")
    if lang == "python":
        for quote in ('"""', "'''"):
            if text.lstrip().startswith(quote):
                body = text.lstrip()[3:]
                end = body.find(quote)
                doc = body[:end] if end != -1 else body
                for line in doc.splitlines():
                    line = _strip_filename_prefix(line.strip())
                    if line:
                        return line
                return ""
    else:
        for line in text.splitlines():
            s = line.strip()
            if s.startswith(("* ", "// ")) and len(s) > 6:
                s = _strip_filename_prefix(s.lstrip("*/ ").strip())
                if s:
                    return s
            if s.startswith("/**") or s.startswith("/*") or s.startswith("//"):
                continue
            if s:
                break
    return ""


PY_PUBLIC = {"function_definition", "class_definition"}
JS_PUBLIC = {"function_declaration", "class_declaration", "lexical_declaration"}


def _symbols(tree, src: bytes, lang: str) -> list[tuple[str, str, int]]:
    """(kind, name, line) for the module's public surface, top level only.

    Top level only is deliberate: a map that lists every nested helper is as
    unreadable as the source it replaces.
    """
    out: list[tuple[str, str, int]] = []
    for node in tree.root_node.children:
        n = node
        # `export default function X` / `export const X = ...`
        if n.type in ("export_statement",):
            inner = [c for c in n.children if c.type not in ("export", "default")]
            n = inner[-1] if inner else n

        if lang == "python" and n.type in PY_PUBLIC:
            name_node = n.child_by_field_name("name")
            if not name_node:
                continue
            name = _text(name_node, src)
            if name.startswith("_"):
                continue        # private by convention
            kind = "class" if n.type == "class_definition" else "def"
            out.append((kind, name, n.start_point[0] + 1))

        elif lang != "python" and n.type in JS_PUBLIC:
            if n.type == "lexical_declaration":
                for d in n.children:
                    if d.type != "variable_declarator":
                        continue
                    nn = d.child_by_field_name("name")
                    val = d.child_by_field_name("value")
                    if not nn:
                        continue
                    name = _text(nn, src)
                    # Only arrow functions — a const colour table is not a symbol
                    # anyone navigates to.
                    if val is not None and val.type in ("arrow_function", "function_expression"):
                        out.append(("fn", name, n.start_point[0] + 1))
            else:
                nn = n.child_by_field_name("name")
                if nn:
                    kind = "class" if n.type == "class_declaration" else "fn"
                    out.append((kind, _text(nn, src), n.start_point[0] + 1))
    return out


def build() -> str:
    get_parser = _parsers()
    files: list[Path] = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or p.suffix not in LANG_FOR_SUFFIX:
            continue
        if SKIP_DIRS & set(p.parts):
            continue
        files.append(p)

    by_area: dict[str, list[tuple[Path, str, list]]] = {}
    total_symbols = 0
    for p in files:
        lang = LANG_FOR_SUFFIX[p.suffix]
        src = p.read_bytes()
        try:
            tree = get_parser(lang).parse(src)
        except Exception as e:                       # a parse failure is data
            by_area.setdefault(str(p.parent.relative_to(ROOT)), []).append(
                (p, f"(could not parse: {e})", []))
            continue
        syms = _symbols(tree, src, lang)
        total_symbols += len(syms)
        area = str(p.parent.relative_to(ROOT))
        by_area.setdefault(area, []).append((p, _first_docstring_line(src, lang), syms))

    lines: list[str] = [
        "# Code map",
        "",
        "Every module, what it is for, and what it exposes. Generated from the",
        "AST — regenerate with `python tools/codemap.py` after adding or",
        "removing a module.",
        "",
        "This is the file to read FIRST. `JARVIS_FULL_SOURCE.txt` is the",
        "complete source and is 1.4 MB; it answers a different question.",
        "",
        f"{len(files)} source files · {total_symbols} public symbols",
        "",
        "Descriptions come from each module's own docstring. A module with no",
        "description here has no docstring — in this project that is a gap, not",
        "a style choice: CLAUDE.md says the reasoning lives in the docstring.",
        "",
    ]

    for area in sorted(by_area):
        entries = by_area[area]
        lines.append(f"## `{area}/`")
        if area in AREAS:
            lines.append("")
            lines.append(f"> {AREAS[area]}")
        lines.append("")
        for p, desc, syms in sorted(entries, key=lambda e: e[0].name):
            rel = p.relative_to(ROOT)
            lines.append(f"**`{p.name}`**{' — ' + desc if desc else ''}")
            if syms:
                shown = ", ".join(f"`{n}`" for _, n, _ in syms[:14])
                more = f" _(+{len(syms) - 14} more)_" if len(syms) > 14 else ""
                lines.append(f"  <br>{shown}{more}")
            lines.append(f"  <br>`{rel}`")
            lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = build()
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} — {len(text) // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

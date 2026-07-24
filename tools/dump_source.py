#!/usr/bin/env python3
"""
tools/dump_source.py — regenerate JARVIS_FULL_SOURCE.txt (the single-file source).

Run after any code change so the copy on GitHub stays current:
    python tools/dump_source.py

Writes JARVIS_FULL_SOURCE.txt at the repo root: a table of contents followed by
every source/config file in fenced code blocks with path headers. Excludes
node_modules, build output, the database, secrets, and binaries.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "JARVIS_FULL_SOURCE.txt")

SKIP_DIRS = {".git", "node_modules", "dist", "build", "__pycache__", "browser-profile",
             "screenshots", "scratchpad", ".vscode", ".idea", "venv", ".venv",
             "verification", "tessdata"}
INCLUDE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".json",
               ".txt", ".md", ".bat", ".sh", ".yml", ".yaml", ".sql"}
INCLUDE_NAMES = {"requirements.txt", "package.json", "vite.config.js", "start.bat",
                 "START_JARVIS.bat", ".gitignore", "config.js"}
SKIP_NAMES = {"jarvis.db", "vault.key", "package-lock.json", "jarvis.db-shm",
              "jarvis.db-wal", ".env", "JARVIS_FULL_SOURCE.txt"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff",
            ".woff2", ".ttf", ".map", ".pyc", ".db"}


def collect():
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_NAMES:
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in SKIP_EXT:
                continue
            if not (ext in INCLUDE_EXT or fn in INCLUDE_NAMES):
                continue
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > 600_000:
                    continue
            except OSError:
                continue
            files.append((os.path.relpath(full, ROOT), full))

    def key(item):
        rel = item[0]
        if rel.endswith(".md"): return (0, rel)
        if rel.startswith("backend/"): return (1, rel)
        if rel.startswith("frontend/"): return (2, rel)
        return (3, rel)
    files.sort(key=key)
    return files


def main():
    files = collect()
    with open(OUT, "w", encoding="utf-8") as out:
        out.write("=" * 80 + "\n")
        out.write("JARVIS OS — FULL SOURCE DUMP (single file for AI review)\n")
        out.write("Repo: musssyibro-svg/Jarvis-  Branch: claude/jarvis-automation-rebuild-37xvhr\n")
        out.write(f"Files included: {len(files)} (source + config; excludes node_modules, "
                  "db, secrets, binaries, build output)\n")
        out.write("Regenerate with: python tools/dump_source.py\n")
        out.write("=" * 80 + "\n\n")
        out.write("TABLE OF CONTENTS\n" + "-" * 40 + "\n")
        for i, (rel, _) in enumerate(files, 1):
            out.write(f"{i:3d}. {rel}\n")
        out.write("\n\n")
        for i, (rel, full) in enumerate(files, 1):
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception as e:
                content = f"[could not read: {e}]"
            lang = os.path.splitext(rel)[1].lstrip(".")
            out.write("\n" + "#" * 80 + "\n")
            out.write(f"# FILE {i}/{len(files)}: {rel}\n")
            out.write("#" * 80 + "\n")
            out.write(f"```{lang}\n{content}")
            if not content.endswith("\n"):
                out.write("\n")
            out.write("```\n")
    size = os.path.getsize(OUT)
    print(f"Wrote {OUT} — {len(files)} files, {size/1024:.0f} KB")


if __name__ == "__main__":
    main()

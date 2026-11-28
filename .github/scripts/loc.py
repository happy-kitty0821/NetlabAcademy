#!/usr/bin/env python3
"""
Count lines of code per language and publish them in README.md.

    python .github/scripts/loc.py                 # print the table
    python .github/scripts/loc.py --update README.md
    python .github/scripts/loc.py --summary "$GITHUB_STEP_SUMMARY"

Only files tracked by git are counted, so virtual environments,
node_modules and build output never are.  Generated files (lockfiles,
Django migrations) and tooling folders are skipped (see EXCLUDE).

Each line is classified like cloc does it: blank, comment (line or block
comments, Python docstrings) or code.  It needs nothing but Python 3.9+
and git, so the numbers are the same locally and in GitHub Actions.

README.md gets the table between ``<!-- LOC:START -->`` and
``<!-- LOC:END -->`` and a total badge between ``<!-- LOC-BADGE:START -->``
and ``<!-- LOC-BADGE:END -->``.  The file is only rewritten when the
counts change.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# extension -> (language, line comment markers, block comment (open, close) pairs)
HASH = ("#",)
SLASH = ("//",)
C_BLOCK = (("/*", "*/"),)
HTML_BLOCK = (("<!--", "-->"),)
LANGUAGES: dict[str, tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]]] = {
    ".py":   ("Python", HASH, (('"""', '"""'), ("'''", "'''"))),
    ".ts":   ("TypeScript", SLASH, C_BLOCK),
    ".tsx":  ("TSX", SLASH, C_BLOCK),
    ".js":   ("JavaScript", SLASH, C_BLOCK),
    ".mjs":  ("JavaScript", SLASH, C_BLOCK),
    ".cjs":  ("JavaScript", SLASH, C_BLOCK),
    ".jsx":  ("JavaScript", SLASH, C_BLOCK),
    ".css":  ("CSS", (), C_BLOCK),
    ".scss": ("SCSS", SLASH, C_BLOCK),
    ".html": ("HTML", (), HTML_BLOCK),
    ".md":   ("Markdown", (), HTML_BLOCK),
    ".json": ("JSON", (), ()),
    ".yml":  ("YAML", HASH, ()),
    ".yaml": ("YAML", HASH, ()),
    ".toml": ("TOML", HASH, ()),
    ".ini":  ("INI", (";", "#"), ()),
    ".cfg":  ("INI", (";", "#"), ()),
    ".sh":   ("Shell", HASH, ()),
    ".ps1":  ("PowerShell", HASH, (("<#", "#>"),)),
    ".bat":  ("Batchfile", ("REM ", "rem ", "::"), ()),
    ".sql":  ("SQL", ("--",), C_BLOCK),
}

# Tracked files that are generated or are tooling, not project code.  The
# README holds the table itself, so counting it would change the result.
EXCLUDE = [
    "README.md",
    "*package-lock.json",
    "*yarn.lock",
    "*pnpm-lock.yaml",
    "*/migrations/*",
    ".agents/*",
    ".kiro/*",
    ".claude/*",
]

START, END = "<!-- LOC:START -->", "<!-- LOC:END -->"
BADGE_START, BADGE_END = "<!-- LOC-BADGE:START -->", "<!-- LOC-BADGE:END -->"
BAR_WIDTH = 20


@dataclass
class Count:
    files: int = 0
    code: int = 0
    comment: int = 0
    blank: int = 0

    @property
    def total(self) -> int:
        return self.code + self.comment + self.blank


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True,
                         capture_output=True).stdout.decode("utf-8")
    files = []
    for name in filter(None, out.split("\0")):
        if any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE):
            continue
        path = root / name
        if path.suffix.lower() in LANGUAGES and path.is_file():
            files.append(path)
    return files


def count_file(path: Path, line_markers: tuple[str, ...],
               blocks: tuple[tuple[str, str], ...]) -> Count:
    c = Count(files=1)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return Count()
    closer: str | None = None          # inside a block comment until this
    in_string: str | None = None       # inside a multi-line string literal (code)
    quotes = [o for o, e in blocks if o == e]   # Python's triple quotes
    for raw in text.splitlines():
        line = raw.strip()
        if closer is not None:
            c.comment += 1
            if closer in line:
                closer = None
            continue
        if in_string is not None:
            c.code += 1
            if line.count(in_string) % 2 == 1:
                in_string = None
            continue
        if not line:
            c.blank += 1
            continue
        if line_markers and line.startswith(line_markers):
            c.comment += 1
            continue
        opened = next(((o, e) for o, e in blocks if line.startswith(o)), None)
        if opened:
            o, e = opened
            c.comment += 1
            # A block that does not close on this line continues below.
            if e not in line[len(o):]:
                closer = e
            continue
        c.code += 1
        # A code line that opens a triple-quoted string without closing it
        # (x = """...) continues as code, not as a docstring.
        for q in quotes:
            if line.count(q) % 2 == 1:
                in_string = q
                break
    return c


def count_repo(root: Path) -> dict[str, Count]:
    totals: dict[str, Count] = {}
    for path in tracked_files(root):
        lang, markers, blocks = LANGUAGES[path.suffix.lower()]
        c = count_file(path, markers, blocks)
        t = totals.setdefault(lang, Count())
        t.files += c.files
        t.code += c.code
        t.comment += c.comment
        t.blank += c.blank
    return dict(sorted(totals.items(), key=lambda kv: (-kv[1].code, kv[0])))


def short(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def table(counts: dict[str, Count]) -> str:
    total = Count()
    for c in counts.values():
        total.files += c.files
        total.code += c.code
        total.comment += c.comment
        total.blank += c.blank
    rows = [
        "| Language | Files | Code | Comments | Blank | Share of code |",
        "| :-- | --: | --: | --: | --: | :-- |",
    ]
    for lang, c in counts.items():
        share = c.code / total.code if total.code else 0.0
        filled = round(share * BAR_WIDTH)
        bar = "█" * filled + "░" * (BAR_WIDTH - filled)
        rows.append(f"| {lang} | {c.files:,} | {c.code:,} | {c.comment:,} | {c.blank:,} "
                    f"| `{bar}` {share * 100:.1f}% |")
    rows.append(f"| **Total** | **{total.files:,}** | **{total.code:,}** | "
                f"**{total.comment:,}** | **{total.blank:,}** | |")
    return "\n".join(rows)


def badge(counts: dict[str, Count]) -> str:
    code = sum(c.code for c in counts.values())
    label = short(code).replace("-", "--")
    return (f"![Lines of code](https://img.shields.io/badge/lines_of_code-{label}-0969da"
            f"?style=flat-square)")


def replace_between(text: str, start: str, end: str, body: str) -> str:
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit(f"README is missing the {start} ... {end} markers")
    return pattern.sub(lambda _: f"{start}\n{body}\n{end}", text, count=1)


def update_readme(readme: Path, counts: dict[str, Count]) -> bool:
    old = readme.read_text(encoding="utf-8")
    body = table(counts)
    current = re.search(re.escape(START) + r"\n(.*?)\n" + re.escape(END), old, re.S)
    # Unchanged counts: leave the file (and its date) alone.
    if current and current.group(1).split("\n<sub>")[0] == body:
        return False
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    note = (f"<sub>Counted by <code>.github/scripts/loc.py</code> on every push to "
            f"<code>main</code> (git-tracked files; lockfiles, migrations and this README "
            f"excluded). "
            f"Last updated {stamp}.</sub>")
    new = replace_between(old, START, END, f"{body}\n{note}")
    new = replace_between(new, BADGE_START, BADGE_END, badge(counts))
    if new == old:
        return False
    readme.write_text(new, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--update", metavar="README", help="rewrite the LOC section of this file")
    parser.add_argument("--summary", metavar="FILE", help="append the table to this file "
                        "(e.g. $GITHUB_STEP_SUMMARY)")
    args = parser.parse_args()

    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True,
                               capture_output=True, text=True).stdout.strip())
    counts = count_repo(root)
    print(table(counts))

    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write("## Lines of code\n\n" + table(counts) + "\n")
    if args.update:
        changed = update_readme(Path(args.update), counts)
        print(f"\n{args.update}: {'updated' if changed else 'unchanged'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Verify every relative link in the repo's Markdown files points at a real file.

The docs promise "every claim points at code; if the link breaks, the doc is
wrong". This is the check that keeps that promise honest: it walks every
tracked ``*.md`` file, collects the ``[text](target)`` links that are relative
paths (not http(s), mailto, or a bare ``#anchor``), resolves each against the
file's own directory, and fails if the target does not exist. Fenced code
blocks and inline code spans are skipped: a link *shown as an example* is not
a link.

    tool/checklinks.py            # whole repo (files from `git ls-files`)
    tool/checklinks.py docs/*.md  # just these files

Exit 0 when every link resolves, 1 with one line per broken link otherwise.
Anchors (``file.md#section``) are checked for the file only.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# [text](target) and [text](target "title"); inline code spans are stripped first
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_SKIP_PREFIXES = ("http://", "https://", "mailto:", "#", "data:")


def markdown_files(argv):
    if argv:
        return [Path(a).resolve() for a in argv]
    out = subprocess.run(["git", "ls-files", "*.md", "**/*.md"], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    return sorted({(REPO / line).resolve() for line in out.splitlines() if line})


_FENCE = re.compile(r"^\s*(```|~~~)")


def links_in(text):
    in_fence = False
    for line_no, line in enumerate(text.splitlines(), start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in _LINK.finditer(_INLINE_CODE.sub("", line)):
            yield line_no, match.group(1)


def check(path):
    broken = []
    for line_no, target in links_in(path.read_text(encoding="utf-8")):
        if target.startswith(_SKIP_PREFIXES):
            continue
        file_part = target.split("#", 1)[0]
        if not file_part:
            continue
        resolved = (path.parent / file_part).resolve()
        if not resolved.exists():
            broken.append((line_no, target))
    return broken


def main(argv):
    failures = 0
    for path in markdown_files(argv):
        for line_no, target in check(path):
            failures += 1
            rel = path.relative_to(REPO) if path.is_relative_to(REPO) else path
            print(f"{rel}:{line_no}: broken link -> {target}")
    if failures:
        print(f"\n{failures} broken link(s).", file=sys.stderr)
        return 1
    print("all markdown links resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

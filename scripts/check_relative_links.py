#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_relative_links.py -- every relative link in the published tree must resolve.

Why this exists
---------------
A draft of `FINAL-METRICS-600K-2026-09-18.md` linked to
`../../deliverables/engineering-assurance/nccl-channels-8-...md`. That file is a real,
correctly named internal deliverable -- it simply lives in the project workspace, not in
this repository. The link therefore rendered as a dead reference **in the published
document**, and nothing in the build would ever have said so: markdown link rot is silent
by construction.

Fixing that one link is not the fix. The fix is to enumerate every relative link, which is
what this script does -- the same rule the errata applies to hashes and to statistics
("a finding about a class is not a finding until the class is enumerated") applies to
references.

Usage
-----
    python3 scripts/check_relative_links.py [root]     # default: repo root

Checks, for every `.md` file:
  * relative links and images resolve to an existing path (fragment stripped)
  * a link into a directory resolves if the directory exists
  * absolute http(s) links are listed but not fetched (no network in CI)
  * reports the resolved target so a failure can be diagnosed without re-running

Exit code 0 if every relative link resolves, 1 otherwise.
"""
import os
import re
import sys

SKIP_DIRS = {".git", "__pycache__", ".workbuddy", "node_modules", ".venv"}
# Text of the form [label](target "title") -- title is optional.
LINK = re.compile(r"!?\[[^\]]*\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
FENCE = re.compile(r"^\s*(```|~~~)")


def iter_md(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".md"):
                yield os.path.join(dirpath, fn)


def strip_code(text):
    """Drop fenced blocks and inline code so example links are not checked."""
    out, in_fence, fence_marker = [], False, None
    for line in text.split("\n"):
        m = FENCE.match(line)
        if m:
            marker = m.group(1)
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence, fence_marker = False, None
            out.append("")
            continue
        out.append("" if in_fence else line)
    joined = "\n".join(out)
    return re.sub(r"`[^`]*`", "", joined)


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    broken, external, checked = [], [], 0
    for path in sorted(iter_md(root)):
        rel_to_root = os.path.relpath(path, root)
        with open(path, encoding="utf-8") as fh:
            body = strip_code(fh.read())
        for m in LINK.finditer(body):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                external.append((rel_to_root, target))
                continue
            if target.startswith("#"):
                continue
            clean = target.split("#", 1)[0]
            if not clean:
                continue
            checked += 1
            resolved = os.path.normpath(os.path.join(os.path.dirname(path), clean))
            if not os.path.exists(resolved):
                broken.append((rel_to_root, target, os.path.relpath(resolved, root)))

    print("markdown files scanned : %d" % sum(1 for _ in iter_md(root)))
    print("relative links checked : %d" % checked)
    print("external links ignored : %d" % len(external))
    if broken:
        print("\nBROKEN (%d):" % len(broken))
        for src, target, resolved in broken:
            print("  %s" % src)
            print("      %s  ->  %s   [does not exist]" % (target, resolved))
        return 1
    print("\nPASS -- every relative link resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main())

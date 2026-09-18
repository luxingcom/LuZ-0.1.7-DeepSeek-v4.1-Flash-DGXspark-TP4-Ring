#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_report_tables.py -- verify the report's tables match the generated ones.

FINAL-METRICS-600K claims:

    "§2-§7 的表格由 benchmarks/render_report_tables.py 从原始归档机械产出后粘贴，
     可重跑该命令逐字节复核。"

A claim like that is only worth making if something checks it. This does: it re-renders
the tables from the archive with the same renderer, extracts each table block from both
the generated output and the report, and compares them **row by row**, reporting the
first difference with both sides shown.

Why not just diff the files
---------------------------
The report is prose + tables; the generated file is tables only, and the report
legitimately reflows some captions. So a whole-file diff would report noise and the real
drift would hide in it. The comparison is therefore per table, keyed on the renderer's
own `<!-- generated from ... -->` marker, and it compares the **data rows** (lines
starting with `|` that are not the header or the alignment row) plus the header line.

Usage
-----
    python3 scripts/check_report_tables.py <archive-dir> <report.md>

Exit 0 if every table present in both matches, 1 otherwise. Tables that exist in only
one of the two are reported (that is usually a stage that has not landed yet, which is
why the report is allowed to say so).
"""
import os
import re
import subprocess
import sys

MARKER = re.compile(r"^<!--\s*generated from (.+?)\s*-->")
TABLE_ROW = re.compile(r"^\|")


def parse(text):
    """-> {source: [rows]} where rows are the header + data lines of each table."""
    tables = {}
    current = None
    for line in text.split("\n"):
        m = MARKER.match(line)
        if m:
            current = m.group(1)
            tables[current] = []
            continue
        if current is None:
            continue
        if line.startswith("## ") or line.startswith("### "):
            current = None
            continue
        if TABLE_ROW.match(line):
            tables[current].append(line.rstrip())
        elif tables[current] and line.strip() == "":
            # a blank line closes the row block, but a caption may follow; keep collecting
            # only if another `|` row appears before the next marker
            continue
    # drop alignment rows: keep header (first) and data rows (those with a digit-ish cell)
    out = {}
    for src, rows in tables.items():
        kept = []
        for i, r in enumerate(rows):
            cells = [c.strip() for c in r.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue  # alignment row
            kept.append(r)
        out[src] = kept
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    archive, report = sys.argv[1], sys.argv[2]
    renderer = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "benchmarks", "render_report_tables.py")
    if not os.path.exists(renderer):
        print("renderer not found: %s" % renderer)
        return 2

    proc = subprocess.run([sys.executable, renderer, archive],
                          capture_output=True, text=True)
    generated = parse(proc.stdout)
    with open(report, encoding="utf-8") as fh:
        published = parse(fh.read())

    fails = []
    print("tables in archive : %d" % len(generated))
    print("tables in report  : %d" % len(published))
    for src, grows in generated.items():
        if src not in published:
            print("  [skip] %-34s not yet in the report (stage not landed?)" % src)
            continue
        prows = published[src]
        if grows == prows:
            print("  [ ok ] %-34s %d rows match" % (src, len(grows)))
            continue
        fails.append(src)
        print("  [FAIL] %-34s generated %d rows, report %d rows" %
              (src, len(grows), len(prows)))
        for i in range(max(len(grows), len(prows))):
            g = grows[i] if i < len(grows) else "<missing>"
            p = prows[i] if i < len(prows) else "<missing>"
            if g != p:
                print("        first difference at row %d:" % i)
                print("          archive : %s" % g[:160])
                print("          report  : %s" % p[:160])
                break

    for src in published:
        if src not in generated:
            print("  [warn] %-34s in the report but not in this archive" % src)

    if fails:
        print("\nFAIL -- %d table(s) differ: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("\nPASS -- every table present in both is identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())

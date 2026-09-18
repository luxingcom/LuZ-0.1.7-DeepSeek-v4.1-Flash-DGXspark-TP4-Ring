#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_pr_v3_tables.py -- emit the PR-v3 tables from the archive.

Companion to `pr_matrix_v3.py`. The PR-v3 section of FINAL-METRICS carries a
`<!-- generated from ... -->` marker and `scripts/check_report_tables.py` compares
that table against this renderer's output, so the published numbers cannot drift
from `data/prv3-20260918/` without a failing check:

    python3 benchmarks/render_pr_v3_tables.py data/prv3-20260918

Prints two blocks (the 34-cell per-cell table and the 7x5 compressed view), each
preceded by the same marker the report uses.

The concurrency columns come from `pr_v3_concurrency.py`'s clustering rule
(gap tolerance 10 ms) applied to the raw per-stream files -- NOT from the
`ttft_overlap_peak` field in summary.json, which is degenerate when
`max_new_tokens=1` because `t_end - t_first` is ~0.1 ms.
"""
import glob
import json
import os
import statistics
import sys

CONCS = [1, 2, 4, 8, 16]
TOL = 0.010

MARKER_FULL = "<!-- generated from summary.json + raw/*-c*-w0.json -->"
MARKER_MATRIX = "<!-- generated from summary.json (7x5) -->"


def clusters(vs, tol=TOL):
    vs = sorted(vs)
    out = [[vs[0]]]
    for v in vs[1:]:
        if v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "data/prv3-20260918"
    summ = json.load(open(os.path.join(root, "summary.json"), encoding="utf-8"))
    cells = {(c["input_tokens"], c["concurrency"]): c for c in summ["cells"]}
    sizes = summ["_meta"]["sizes"]

    width = {}
    for f in glob.glob(os.path.join(root, "raw", "*-c*-w0.json")):
        st = json.load(open(f, encoding="utf-8"))
        ok = [r for r in st if not r.get("error") and r.get("t_first")]
        inp = ok[0].get("input_tokens") or ok[0].get("prompt_tokens")
        conc = len(st)
        cl = clusters([r["t_first"] for r in ok])
        width[(inp, conc)] = (max(len(c) for c in cl), len(cl))

    print(MARKER_FULL)
    print()
    print("| Input tokens | C | Streams OK | Total prompt tokens | Wall s | **Total t/s** "
          "| TTFT first s | TTFT last s | Observed batch width | Prefill batches | Verdict |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for s in sizes:
        for c in CONCS:
            x = cells.get((s, c))
            if not x:
                print(f"| {s} | {c} | — | — | — | **—** | — | — | — | — "
                      f"| ⛔ 未测（本轮停跑，非失败） |")
                continue
            w, nc = width[(s, c)]
            verdict = ("parallel (2/step)" if w >= 2
                       else ("serialized (1/step)" if c > 1 else "single stream"))
            print(f"| {s} | {c} | {x['streams_ok']}/{c} | {x['total_prompt_tokens']} "
                  f"| {x['wall_s']:.3f} | **{x['total_throughput_tps']:.1f}** "
                  f"| {x['ttft_first_s']:.3f} | {x['ttft_last_s']:.3f} | {w} | {nc} | {verdict} |")

    print()
    print(MARKER_MATRIX)
    print()
    print("| Input tokens | C1 | C2 | C4 | C8 | C16 | row median | best |")
    print("|---:|---:|---:|---:|---:|---:|---:|---|")
    for s in sizes:
        vals = [f"{cells[(s, c)]['total_throughput_tps']:.1f}" if (s, c) in cells else "—"
                for c in CONCS]
        have = [cells[(s, c)]["total_throughput_tps"] for c in CONCS if (s, c) in cells]
        b = max((cells[(s, c)]["total_throughput_tps"], c) for c in CONCS if (s, c) in cells)
        print(f"| {s} | " + " | ".join(vals) +
              f" | {statistics.median(have):.1f} | **{b[0]:.1f}** @C{b[1]} |")

    missing = [(s, c) for s in sizes for c in CONCS if (s, c) not in cells]
    if missing:
        print(f"\n# NOTE: {len(missing)} cell(s) not measured: {missing}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

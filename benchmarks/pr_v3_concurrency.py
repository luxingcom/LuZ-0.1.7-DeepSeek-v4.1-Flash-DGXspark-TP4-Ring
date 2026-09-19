#!/usr/bin/env python3
"""PR-v3 concurrency verdict, recomputed from the archived per-stream records.

Why this script exists
----------------------
`pr_matrix_v3.py` ships two concurrency signals per cell:

  * `gauge_parallel`  -- did the engine's `sglang:num_running_reqs` gauge ever
    exceed 1 (1 s sampler).
  * `ttft_overlap_peak` -- peak number of streams whose [t_first, t_end] spans
    overlapped.

Under PR-v3 the output budget is `max_new_tokens=1`, so **the single emitted
token is the first token**: `t_end - t_first` is ~0.1 ms and the spans are
degenerate. A zero-length sweep can never reach 2, so `ttft_overlap_peak`
collapses to 1 for *every* cell regardless of what the engine actually did,
and `serialized` (which requires `overlap >= min(conc,2)`) is therefore
biased toward "serialized". That is a defect of the metric, not a finding.

The honest discriminator under a 1-token budget is **completion-time
clustering**: if the scheduler really prefilled N requests in one step, those
N requests emit their first token at the same wall instant; if it ran them one
at a time, the first-token instants are spaced by one request's service time.
This script re-derives that from the raw archives, so the archived harness is
not modified and the archived numbers are not re-measured.

Usage
-----
    python3 pr_v3_concurrency.py <dir-with-*-c<N>-w0.json> [tolerance_s] [chunk_size]

`chunk_size` defaults to 4096 (the value the 2026-09-18 archive was measured at);
pass 8192 for the 2026-09-19 re-run (`data/prv3-v14-20260919/`).

Prints one row per cell: input, C, predicted admission width, observed cluster
count, max cluster size (= observed parallel width), median inter-cluster gap,
and a verdict.
"""

import json
import statistics
import sys
from pathlib import Path

DEFAULT_CHUNK = 4096

# Two orders of magnitude separate "same scheduler step" from "next step":
#   within-step jitter (streams that really shared one prefill step): <= 0.5 ms
#   smallest observed between-step gap:                                  64 ms
# so 10 ms sits 20x above the jitter and 6x below the gap. The verdict is
# stable for any tolerance in 0.005-0.05 s (admission law matches 34/34);
# only a tolerance >= 0.2 s starts merging adjacent steps and flips 7 cells.
DEFAULT_TOL = 0.010


def predicted_width(input_tokens, conc, chunk):
    """chunked-prefill admission law: min(C, max(1, floor(chunk / input)))."""
    per_step = max(1, chunk // input_tokens)
    return min(conc, per_step)


def clusters(values, tol):
    """Gap-based clustering of sorted timestamps. tol = max intra-cluster gap."""
    vs = sorted(values)
    out = [[vs[0]]]
    for v in vs[1:]:
        if v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    tol = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TOL
    chunk = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_CHUNK

    files = sorted(root.glob("*-c*-w0.json"))
    if not files:
        print(f"no per-stream files under {root}", file=sys.stderr)
        return 2

    rows = []
    for f in files:
        recs = json.loads(f.read_text(encoding="utf-8"))
        ok = [r for r in recs if not r.get("error") and r.get("t_first")]
        if not ok:
            continue
        tf = [r["t_first"] for r in ok]
        cl = clusters(tf, tol)
        starts = [c[0] for c in cl]
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        size = int(f.name.split("-c")[1].split("-")[0])
        inp = ok[0].get("input_tokens") or ok[0].get("prompt_tokens")
        conc = len(recs)
        pred = predicted_width(inp, conc, chunk)
        width = max(len(c) for c in cl)
        rows.append({
            "file": f.name,
            "input_tokens": inp,
            "concurrency": conc,
            "streams_ok": len(ok),
            "predicted_width": pred,
            "n_clusters": len(cl),
            "observed_width": width,
            "cluster_sizes": [len(c) for c in cl],
            "median_gap_s": round(statistics.median(gaps), 3) if gaps else None,
            "spread_within_max_s": round(max((c[-1] - c[0]) for c in cl), 4),
            "match": width == pred,
        })

    rows.sort(key=lambda r: (r["input_tokens"], r["concurrency"]))

    print(f"tolerance = {tol}s   chunked_prefill_size = {chunk}")
    print()
    print("| Input | C | predicted width | observed width | clusters | median gap s | "
          "max within-cluster spread s | admission law holds |")
    print("|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in rows:
        print(f"| {r['input_tokens']} | {r['concurrency']} | {r['predicted_width']} | "
              f"**{r['observed_width']}** | {r['n_clusters']} | {r['median_gap_s']} | "
              f"{r['spread_within_max_s']} | {'yes' if r['match'] else 'NO'} |")

    n_match = sum(1 for r in rows if r["match"])
    print()
    print(f"admission law: {n_match}/{len(rows)} cells match "
          f"min(C, max(1, floor({chunk}/input))) exactly")
    parallel = [r for r in rows if r["observed_width"] >= 2]
    print(f"cells with a real parallel step (observed width >= 2): "
          f"{len(parallel)}/{len(rows)}")
    for r in parallel:
        print(f"  {r['input_tokens']} x C{r['concurrency']}: width {r['observed_width']}, "
              f"clusters {r['n_clusters']}, sizes {r['cluster_sizes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

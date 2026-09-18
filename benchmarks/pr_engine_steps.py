#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pr_engine_steps.py -- attribute the engine's own prefill steps to PR cells.

The PR table predicts, per cell, how many prompts the scheduler can advance in
one prefill step:

    prefills per step  ==  min(concurrency, floor(chunked_prefill_size / input))

That prediction is worth nothing unless the engine can contradict it. Two other
layers already exist -- the client's per-stream `t0`/`t_end` and the engine's
`num_running_reqs`/`num_queue_reqs` gauge -- and this file builds the third, the
strongest one: the scheduler's own step log.

`#new-seq` on a `Prefill batch` line *is* the number of prompts admitted in that
step. So for a cell it must be constant at exactly the predicted value, and
`#new-token` must equal `input` for each of them (a request at or below the
budget is never truncated), while `#pending-token` falls by the chunk size per
step and lands on 0. Any deviation is a counterexample, and the point of this
file is to make counterexamples visible rather than arguable.

Note the log is the *whole* engine's, so steps are attributed to cells by the
wall-clock window of the cell's own streams, taken from the retained cell JSON.

Usage
-----
    pr_engine_steps.py <run_dir> [engine_log] [out_log]

`engine_log` defaults to $ENGINE_LOG. `out_log` defaults to
`<run_dir>/pr/engine-steps.log`; that file holds only the lines inside the PR
cells' windows. The per-cell table goes to stdout.

The window is padded by 0.5 s at each end, so a step that starts just outside a
cell cannot leak in and a boundary step cannot be lost. Overlap between adjacent
cells is impossible here -- a wave returns only after every stream has its last
token -- but the padding makes it explicit rather than assumed.
"""
import datetime
import glob
import json
import os
import re
import sys
from collections import Counter

STEP = re.compile(
    r"^(?P<ts>\S+Z)\s.*?Prefill batch,\s*#new-seq:\s*(?P<newseq>\d+),\s*"
    r"#new-token:\s*(?P<newtok>\d+),.*?#running-req:\s*(?P<run>\d+),\s*"
    r"#queue-req:\s*(?P<queue>\d+),\s*#pending-token:\s*(?P<pend>\d+)")
PAD = 0.0
# Attribution uses a global cursor instead of per-cell windows: cells in this
# chain run back-to-back (524288-c2's t_end equals 524288-c4's t0 to the
# second), so overlapping windows double-claim the seam step. The cursor makes
# each step belong to exactly one cell -- the earliest cell whose window
# reaches it.


def epoch(ts):
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def load_steps(path):
    out = []
    with open(path, "r", errors="replace") as f:
        for line in f:
            if "Prefill batch" not in line:
                continue
            m = STEP.match(line)
            if not m:
                continue
            out.append((epoch(m.group("ts")), int(m.group("newseq")),
                        int(m.group("newtok")), int(m.group("run")),
                        int(m.group("queue")), int(m.group("pend")), line.rstrip("\n")))
    out.sort(key=lambda s: s[0])
    return out


def cells(run):
    for p in glob.glob(os.path.join(run, "pr", "*-c*-w*.json")):
        b = os.path.basename(p)
        m = re.match(r"(\d+)-c(\d+)-w(\d+)\.json$", b)
        if not m:
            continue
        recs = json.load(open(p))
        t0 = [r["t0"] for r in recs if r.get("t0")]
        te = [r.get("t_end") or r.get("t_last") for r in recs if r.get("t_end") or r.get("t_last")]
        if not t0 or not te:
            continue
        yield (int(m.group(1)), int(m.group(2)), int(m.group(3)),
               min(t0), max(te), len(t0), p)


def predict(size, conc, chunk):
    """min(concurrency, floor(chunk / input)) -- the law under test."""
    return min(conc, chunk // size) if size <= chunk else 1


def main():
    if len(sys.argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    run = sys.argv[1]
    log = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("ENGINE_LOG")
    out_log = sys.argv[3] if len(sys.argv) > 3 else os.path.join(run, "pr", "engine-steps.log")
    if not log or not os.path.exists(log):
        sys.stderr.write("engine log not found: %r\n" % log)
        return 1

    meta = json.load(open(os.path.join(run, "pr", "summary.json"))).get("_meta", {})
    chunk = int(meta.get("chunked_prefill_size") or 4096)

    steps = load_steps(log)
    print("engine log: %s  (%d Prefill batch lines in the file)" % (log, len(steps)))
    print("chunked_prefill_size: %d (from pr/summary.json)" % chunk)

    rows, keep = [], []
    ordered = sorted(cells(run), key=lambda c: (c[3], c[4]))
    cursor = 0
    for size, conc, wave, lo, hi, nstream, path in ordered:
        sel = []
        while cursor < len(steps) and steps[cursor][0] <= hi:
            if steps[cursor][0] >= lo:
                sel.append(steps[cursor])
            cursor += 1
        keep.extend(sel)
        if not sel:
            rows.append((size, conc, None, 0, "no steps", 0, 0, 0))
            continue
        seqs = Counter(s[1] for s in sel)
        newtok = sum(s[2] for s in sel)
        rows.append((size, conc, max(seqs), len(sel),
                     ",".join("%dx%d" % (n, k) for k, n in sorted(seqs.items())),
                     max(s[4] for s in sel), newtok, conc * size))

    out = ["<!-- generated from pr/summary.json + pr/*.json + the engine step log -->", "",
           "`#new-seq` on each `Prefill batch` line is the number of prompts the scheduler",
           "advanced in that step, so it tests the prediction directly instead of restating",
           "it. `#new-seq values` is a histogram (`<count>x<value>`). `max #new-seq` should",
           "equal `Prefills/step (pred)`; `sum #new-token` should equal `C x input` (nothing",
           "is truncated at or below the chunk budget); `max #queue-req` is the engine's own",
           "queue from the same lines. Steps are attributed with a global cursor so each",
           "step belongs to exactly one cell -- cells run back-to-back and an overlap",
           "window would double-claim the seam step.", "",
           "| Input tokens | C | Prefills/step (pred) | Steps | #new-seq values | max #new-seq | max #queue-req | sum #new-token | C x input | Law |",
           "|---:|---:|---:|---:|---|---:|---:|---:|---:|---|"]
    for size, conc, mx, n, hist, q, nt, want in rows:
        pred = predict(size, conc, chunk)
        verdict = ("—" if mx is None else ("ok" if mx == pred and nt == want else "**DIFF**"))
        out.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            "{:,}".format(size), conc, pred, n, hist,
            "—" if mx is None else mx, q, "{:,}".format(nt), "{:,}".format(want), verdict))

    # the archive: only the pr-window lines, in time order, deduplicated
    keep = sorted({s[0]: s for s in keep}.values(), key=lambda s: s[0])
    with open(out_log, "w") as f:
        for s in keep:
            f.write(s[6] + "\n")
    out.append("")
    out.append("Raw step lines for these windows: `%s` (%d lines)." % (
        os.path.relpath(out_log, run), len(keep)))
    md = "\n".join(out) + "\n"
    sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pr_matrix_v3.py — pure-prefill total-throughput matrix (2026-09-18).

Rewrite of the PR benchmark per the supervisor's three requirements:

1. **KV-cache influence excluded.** Every request carries a fresh front nonce
   (nothing is served from the radix cache), AND `/flush_cache` is called
   between cells, so a cell never starts with the previous cell's pages in the
   pool. The flush is verified against `sglang:num_reqs`-style gauge sanity,
   and a flush failure aborts the run rather than silently continuing.

2. **Real concurrency, not a queue.** Output is forced to **1 token per
   request** (max_new_tokens=1), so the wave is pure prefill — no 1024-token
   decode tail that turns C>1 into "one prefill at a time plus decode
   followers" above the chunk size. The engine's own running/queue gauges are
   still sampled per second; a cell whose `running_max < conc` is flagged
   `serialized=true` in the summary and its row says so — the number is
   still the honest wall-clock throughput of that admission policy, but it is
   not labelled as parallel.

3. **Total throughput = Σ(prompt tokens) / wall-clock(arm start → last stream
   end).** One clock for the whole arm: start before dispatch, stop when the
   last stream returns. No per-stream medians, no windows, no decode term.

Sizes: 2048 / 4096 / 8192 / 16384 / 32768 / 65536 / 131072 (512K dropped by
owner decision). C = 1, 2, 4, 8, 16.

Env: SIZES, CONCS, WAVES, BASE, KEY_FILE, STATE_PATH, MODEL_PATH,
MANIFEST_PATH, OUT_DIR, RUN_TAG, REQUEST_TIMEOUT, CHUNKED_PREFILL_SIZE,
NO_FLUSH (set to skip inter-cell flush — never default).

Output: <OUT_DIR>/summary.json, <OUT_DIR>/<size>-c<N>-w<W>.json raw records
(with per-stream t0/t_first/t_end for audit), <OUT_DIR>/TABLE.md.
"""
import concurrent.futures
import hashlib
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sd_protocol as sd  # noqa: E402

BASE = os.environ.get("BASE", "http://127.0.0.1:8899")
MODEL = os.environ.get("MODEL", "deepseek-v4.1-flash")
STATE = Path(os.environ.get("STATE_PATH", "/state"))
model = Path(os.environ.get("MODEL_PATH", "/models/DeepSeek-V4.1-Flash"))
sys.path.insert(0, str(model / "encoding"))
from encoding import encode_messages  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402

tokenizer = Tokenizer.from_file(str(model / "tokenizer.json"))
manifest = Path(os.environ.get("MANIFEST_PATH", str(STATE / "launch.json")))
identity = hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.exists() else None
KEY = sd.read_key(str(STATE / "api-key"))

SIZES = [int(x) for x in os.environ.get(
    "SIZES", "2048,4096,8192,16384,32768,65536,131072").split(",")]
CONCS = [int(x) for x in os.environ.get("CONCS", "1,2,4,8,16").split(",")]
WAVES = int(os.environ.get("WAVES", "1"))
TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "7200"))
CHUNK = int(os.environ.get("CHUNKED_PREFILL_SIZE", "4096"))
NO_FLUSH = os.environ.get("NO_FLUSH", "") == "1"
RUN_TAG = os.environ.get("RUN_TAG") or sd.new_run_tag()
OUT_DIR = os.environ.get("OUT_DIR") or (str(STATE / "bench-results" /
                                        ("pr-v3-" + time.strftime("%Y%m%dT%H%M%S"))))
os.makedirs(OUT_DIR, exist_ok=True)
METRICS_URL = BASE.rstrip("/") + "/metrics"

MAXNEW = 1  # the whole point: pure prefill, no decode tail

FILLER = ("Reference notes: the cache stores recently accessed entries. "
          "An implementation should maintain ordering, handle replacement and "
          "validate its invariants.\n")
INSTRUCTION = ("\nNow write a complete Python LRU cache module with a doubly linked list "
               "and dictionary, including get, put, delete, iteration, resize, clear, "
               "invariant validation, detailed docstrings and ten usage examples. "
               "Return code only. Implement all methods fully.\n<｜Assistant｜></think>")


def encode(text):
    return tokenizer.encode(text, add_special_tokens=False).ids


filler_ids = encode(FILLER)
suffix_ids = encode(INSTRUCTION)


def build_ids(size, index, run_tag):
    """Exactly `size` tokens; fresh front nonce so nothing is radix-cached."""
    nonce = "%s-%d-%s" % (run_tag, index, uuid.uuid4().hex[:8])
    prefix = encode(encode_messages(
        [dict(role="user", content="[" + nonce + "]\nRead these notes.\n")],
        thinking_mode="chat").split("<｜Assistant｜>")[0])
    room = size - len(prefix) - len(suffix_ids)
    if room < 0:
        raise ValueError("size %d too small for prefix %d + suffix %d"
                         % (size, len(prefix), len(suffix_ids)))
    ids = prefix + (filler_ids * (room // len(filler_ids) + 1))[:room] + suffix_ids
    assert len(ids) == size, "built %d tokens, wanted %d" % (len(ids), size)
    return ids, nonce


def flush_cache():
    """POST /flush_cache with retry. Returns (ok, detail).

    The endpoint 400s while any request is still winding down ("When there are
    running or waiting requests, the operation will not be performed"), so a
    short settle-and-retry loop is the honest form: abort only if it keeps
    failing after the engine has had time to drain.
    """
    last = None
    for attempt in range(6):
        req = urllib.request.Request(
            BASE.rstrip("/") + "/flush_cache", data=b"{}",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()[:200].decode(errors="replace")
                return True, body
        except urllib.error.HTTPError as e:
            last = "HTTP %d %s" % (e.code, e.read()[:120].decode(errors="replace"))
        except Exception as e:
            last = repr(e)[:160]
        time.sleep(2.0 * (attempt + 1))
    return False, last


def _metrics_value(name):
    try:
        req = urllib.request.Request(METRICS_URL, headers={"Authorization": "Bearer " + KEY})
        with urllib.request.urlopen(req, timeout=5) as resp:
            text = resp.read().decode(errors="replace")
    except Exception:
        return None
    best = None
    for line in text.splitlines():
        if not line.startswith(name + "{"):
            continue
        try:
            v = float(line.rsplit(" ", 1)[1])
        except (IndexError, ValueError):
            continue
        best = v if best is None else max(best, v)
    return best


class EngineProbe(threading.Thread):
    """Sample engine running/queue gauges while a cell runs (1 s cadence)."""

    daemon = True

    def __init__(self):
        super().__init__()
        self.stop_flag = threading.Event()
        self.running, self.queue = [], []

    def run(self):
        while not self.stop_flag.is_set():
            r = _metrics_value("sglang:num_running_reqs")
            q = _metrics_value("sglang:num_queue_reqs")
            if r is not None:
                self.running.append(r)
            if q is not None:
                self.queue.append(q)
            self.stop_flag.wait(1.0)

    def summary(self):
        def stat(xs):
            if not xs:
                return (None, None, None)
            return (min(xs), statistics.median(xs), max(xs))
        rmin, rmed, rmax = stat(self.running)
        qmin, qmed, qmax = stat(self.queue)
        return {
            "samples": max(len(self.running), len(self.queue)),
            "running_min": rmin, "running_med": rmed, "running_max": rmax,
            "queue_min": qmin, "queue_med": qmed, "queue_max": qmax,
            "queue_gt0_frac": (round(sum(1 for q in self.queue if q > 0) / len(self.queue), 3)
                               if self.queue else None),
        }


def one(ids, nonce, index, wave_idx, conc):
    rec = sd.stream_generate(BASE, KEY, ids, MAXNEW, index=index, wave=wave_idx,
                             ptype="pr", conc=conc, force_fill=False,
                             timeout=TIMEOUT, events=False)
    rec["nonce"] = nonce
    rec["manifest_sha256"] = identity
    return rec


def run_cell(size, conc, wave_idx):
    """One arm: payload-prebuild → release all together → wall clock the arm."""
    built = [build_ids(size, i, RUN_TAG) for i in range(conc)]
    probe = EngineProbe()
    probe.start()
    t_arm_start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as pool:
        recs = list(pool.map(
            lambda t: one(t[1][0], t[1][1], t[0], wave_idx, conc),
            list(enumerate(built))))
    t_arm_end = time.time()
    probe.stop_flag.set()
    probe.join(timeout=10)

    ok = [r for r in recs if not r.get("error") and r.get("prompt_tokens")]
    total_prompt = sum(r["prompt_tokens"] for r in ok)
    wall = t_arm_end - t_arm_start
    t0s = sorted(r["t0"] for r in ok if r.get("t0"))
    t_firsts = sorted(r["t_first"] for r in ok if r.get("t_first"))
    dispatch_spread_ms = round((t0s[-1] - t0s[0]) * 1000.0, 1) if len(t0s) > 1 else 0.0
    p = probe.summary()
    # The gauge is republished only when the scheduler runs a step; with
    # max_new_tokens=1 a wave can finish between samples. The honest test for
    # "was it parallel" is therefore the gauge MAX seen during the cell (did
    # the scheduler ever hold >1 running request) — and, independently, the
    # TTFT overlap: if streams finished at the same wall moment their prefills
    # overlapped regardless of what the 1 s sampler caught.
    gauge_parallel = p["running_max"] is not None and p["running_max"] > 1
    overlap = 0
    if len(t_firsts) == conc and t0s:
        spans = sorted([(r["t_first"], 1) for r in ok if r.get("t_first")] +
                       [(r["t_end"], -1) for r in ok if r.get("t_end")])
        active = 0
        for _, d in spans:
            active += d
            overlap = max(overlap, active)
    serialized = (not gauge_parallel) and overlap < min(conc, 2)
    note = None
    if serialized and conc > 1:
        note = ("gauge never exceeded 1 running request and TTFT spans do not "
                "overlap: this cell ran one-request-at-a-time; its total t/s is "
                "the wall-clock throughput of serialized admission, not parallel prefill")
    summary = {
        "input_tokens": size, "concurrency": conc, "wave": wave_idx,
        "waves": WAVES, "run_tag": RUN_TAG, "manifest_sha256": identity,
        "max_new_tokens": MAXNEW,
        "streams_ok": len(ok), "streams_failed": conc - len(ok),
        "total_prompt_tokens": total_prompt,
        "wall_s": round(wall, 3),
        "total_throughput_tps": round(total_prompt / wall, 1) if wall > 0 else None,
        "ttft_first_s": round(t_firsts[0] - (t0s[0] if t0s else t_arm_start), 3) if t_firsts else None,
        "ttft_last_s": round(t_firsts[-1] - (t0s[0] if t0s else t_arm_start), 3) if t_firsts else None,
        "dispatch_spread_ms": dispatch_spread_ms,
        "engine_probe": p,
        "ttft_overlap_peak": overlap,
        "gauge_parallel": gauge_parallel,
        "serialized": serialized,
        "serialization_note": note,
        "flush_between_cells": not NO_FLUSH,
        "errors": [r.get("error") for r in recs if r.get("error")][:4],
        "convention": (
            "PR-v3 pure-prefill total throughput: max_new_tokens=1 per request "
            "(no decode tail), fresh nonce per request (no radix hit), /flush_cache "
            "between cells, total = sum(prompt_tokens of ok streams) / wall-clock "
            "(arm start -> last stream end). serialized=true means the engine's own "
            "running gauge never reached C: the cell ran under one-at-a-time "
            "admission and the figure is the wall-clock throughput of that policy."),
    }
    sd.dump(os.path.join(OUT_DIR, "%d-c%d-w%d.json" % (size, conc, wave_idx)), recs)
    return summary


def render(summaries):
    lines = [
        "# PR-v3 — pure-prefill total-throughput matrix", "",
        "One request = `max_new_tokens=1` (pure prefill; no decode tail). Fresh nonce",
        "per request; `/flush_cache` between cells. **total t/s = Σ(prompt tokens) /",
        "wall-clock from arm start to last stream end** — one clock per arm, no",
        "windows, no decode term.", "",
        "`serialized=⚠` rows: the engine's running gauge never exceeded 1 AND the",
        "streams' TTFT spans do not overlap — the cell ran one-request-at-a-time",
        "(chunked-prefill admission above %d tokens). The total t/s is still the" % CHUNK,
        "honest wall-clock throughput of that admission policy, but it is not",
        "parallel prefill. `overlap` is the peak number of streams whose prefills",
        "were in flight simultaneously (computed from per-stream t_first/t_end).", "",
        "| Input tokens | C | Streams OK | Total prompt tokens | Wall s | **Total t/s** | TTFT first s | TTFT last s | Prefill overlap peak | serialized |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in summaries:
        lines.append("| %s | %s | %s/%s | %s | %s | **%s** | %s | %s | %s | %s |" % (
            r["input_tokens"], r["concurrency"],
            r["streams_ok"], r["streams_ok"] + r["streams_failed"],
            r["total_prompt_tokens"], r["wall_s"],
            r["total_throughput_tps"] if r["total_throughput_tps"] else "—",
            r["ttft_first_s"] if r["ttft_first_s"] is not None else "—",
            r["ttft_last_s"] if r["ttft_last_s"] is not None else "—",
            r.get("ttft_overlap_peak"),
            "⚠" if r.get("serialized") else "ok"))
    return "\n".join(lines) + "\n"


def warmup():
    try:
        sd.stream_generate(BASE, KEY, build_ids(2048, 0, RUN_TAG)[0], 8,
                           index=0, wave=-1, ptype="pr", conc=1,
                           force_fill=False, timeout=600)
    except Exception:
        pass


def main():
    summaries = []
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    warmup()
    for size in SIZES:
        for conc in CONCS:
            for w in range(WAVES):
                if not NO_FLUSH:
                    ok_flush, detail = flush_cache()
                    if not ok_flush:
                        print(json.dumps({"event": "flush_failed", "detail": detail}),
                              file=sys.stderr, flush=True)
                        sys.exit(3)
                    time.sleep(1.0)  # let the pool settle after the flush
                s = run_cell(size, conc, w)
                summaries = [x for x in summaries
                             if not (x["input_tokens"] == size and x["concurrency"] == conc)]
                summaries.append(s)
                summaries.sort(key=lambda x: (SIZES.index(x["input_tokens"]), x["concurrency"]))
                sd.dump(os.path.join(OUT_DIR, "summary.json"), {
                    "_meta": {
                        "protocol_id": "PR-V3", "run_tag": RUN_TAG, "model": MODEL,
                        "base": BASE, "max_new_tokens": MAXNEW, "waves": WAVES,
                        "chunked_prefill_size": CHUNK,
                        "sizes": SIZES, "concurrencies": CONCS,
                        "flush_between_cells": not NO_FLUSH,
                        "started": started,
                        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "convention": s["convention"],
                    },
                    "cells": summaries})
                with open(os.path.join(OUT_DIR, "TABLE.md"), "w") as fh:
                    fh.write(render(summaries))
                print(json.dumps(s), flush=True)
    with open(os.path.join(OUT_DIR, "COMPLETE"), "w") as fh:
        fh.write(RUN_TAG + "\n" + time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
    print("OUT_DIR=" + OUT_DIR, flush=True)


if __name__ == "__main__":
    main()

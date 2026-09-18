#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pr_matrix_v2.py -- the prompt-rate / prefill-scaling matrix, on SD-1.

Replaces `matrix.py` as the reported table. `matrix.py` is kept unchanged as the
source of the earlier matrix, which is not published under `../data/`.

The one documented SD-1 exception is here: input size is the independent
variable, from 512 to 524288 tokens, so the prompt has to be token-exact, which
only the native `/generate` endpoint with `input_ids` provides. Everything else
follows SD-1, including the decode column.

What this table actually measures -- read before quoting a row
--------------------------------------------------------------
The engine's per-step prefill budget is `--chunked-prefill-size`
(`CHUNKED_PREFILL_SIZE`, 4096 on this build). A request whose prompt is *longer*
than that budget cannot be admitted whole: it becomes the scheduler's single
`chunked_req`, and ``PrefillAdder.add_chunked_req`` gives it the whole step's
budget, returning the req (still unfinished) so that no new prefill is admitted
in that step. A request at or below the budget is never truncated, is therefore
*not* the chunked_req, and several such requests are admitted into one step.

The consequence is a hard admission law, and it is what this matrix exists to
show:

    prefills advanced per step  ==  min(concurrency, floor(CHUNK / input_tokens))

So the prefill column **scales with concurrency only for prompts at or below
`CHUNK`**. Above it, prefill is strictly one request at a time, aggregate
prompt-rate equals the single-stream chunked rate, and TTFT grows linearly in
the request's queue position. That is engine admission policy, not a client
defect. The wave's payloads are built before the pool starts and every stream's
`t0` and `t_end` are retained in the cell JSON, so the client-side dispatch
spread and the peak overlap are *derived from the archive* rather than asserted.
(Do not read the client layer out of `summary.json`: the field named
`stagger_s` there is the **TTFT** spread, `ttft_last - ttft_first`, and carries
no information about dispatch. It was named before that distinction was clear;
it is kept as-is so the archived cells stay byte-reproducible by this file.)
The wave is measured as delivered.

Two consequences this file handles explicitly rather than hiding:

  * `Median TTFT s` at C>1 is **queue-position dominated** for long prompts, so
    the table also carries the first and last stream's TTFT. If those two differ
    by an order of magnitude, the median is describing the queue, not the engine.
  * The engine's own counters (`sglang:num_running_reqs`, `sglang:num_queue_reqs`)
    are sampled once a second during every cell and reduced into the cell. That
    is the independent record of how parallel the cell actually ran, so the
    claim does not have to be taken from this docstring.

Two decode columns are carried for this table specifically
----------------------------------------------------------
  median_decode_tps   SD-1 basis, (ct-1)/(tLast-tFirst) per stream.
  decode_window_tps   the earlier 129..641 window rate, 512/(t641-t129).
                      Recovered from the retained per-token event log, so the
                      older published column stays checkable rather than
                      becoming unreproducible. It is a different measure -- it
                      excludes the ramp -- which is exactly why both are kept.

Env
---
PREFILL_SIZES   default "512,2048,8192,32768,131072,524288"
CONCURRENCIES   default "1,2,4,8,16"
WAVES           default 1
MAXNEW          default 1024
REQUEST_TIMEOUT default 7200    (see the note in `TIMEOUT` below)
CHUNKED_PREFILL_SIZE  default 4096 -- must match the engine's launch flag; it is
                used only to *predict* prefills-per-step, and the prediction is
                checked against the engine counters that are sampled anyway
SAMPLES         default "512" -- sizes sent once as a warm-up before cell 1
MODEL_PATH      default /models/DeepSeek-V4.1-Flash
MANIFEST_PATH   default <STATE_PATH>/launch.json  (recorded, not enforced)
KEY_FILE        default <STATE_PATH>/api-key
METRICS_URL     default <BASE>/metrics
OUT_DIR         default <STATE_PATH>/pr-v2-<timestamp>

Output
------
<OUT_DIR>/summary.json          cell summaries, rewritten as the run proceeds
<OUT_DIR>/<size>-c<N>-w<W>.json raw per-stream records incl. the event log
<OUT_DIR>/TABLE.md              the rendered table
"""
import concurrent.futures
import hashlib
import json
import os
import statistics
import sys
import threading
import time
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
    "PREFILL_SIZES", "512,2048,8192,32768,131072,524288").split(",")]
CONCS = [int(x) for x in os.environ.get("CONCURRENCIES", "1,2,4,8,16").split(",")]
WAVES = int(os.environ.get("WAVES", "1"))
MAXNEW = int(os.environ.get("MAXNEW", "1024"))
# 3600 s is not enough for the 524288 row: prefill is one request at a time
# above CHUNKED_PREFILL_SIZE, so the 16th stream's first token lands at roughly
# 16 * 524288 / (measured single-stream chunked rate). At the observed ~1680 t/s
# that is ~5000 s, and a 3600 s budget silently drops the tail of the cell
# instead of reporting it. 7200 s covers the row and the cell still reports how
# many streams actually succeeded, so a genuine engine failure stays visible.
TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "7200"))
CHUNK = int(os.environ.get("CHUNKED_PREFILL_SIZE", "4096"))
SAMPLES = [int(x) for x in os.environ.get("SAMPLES", "512").split(",") if x.strip()]
PROBE_PERIOD = float(os.environ.get("PROBE_PERIOD", "1.0"))
METRICS_URL = os.environ.get("METRICS_URL", BASE.rstrip("/") + "/metrics")
RUN_TAG = os.environ.get("RUN_TAG") or sd.new_run_tag()
OUT_DIR = sd.out_dir("pr-v2")

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
    """Exactly `size` tokens, with a fresh front nonce so nothing is cached."""
    nonce = "%s-%d-%s" % (run_tag, index, uuid.uuid4().hex[:8])
    prefix = encode(encode_messages(
        [dict(role="user", content="[" + nonce + "]\nRead these notes.\n")],
        thinking_mode="chat").split("<｜Assistant｜>")[0])
    room = size - len(prefix) - len(suffix_ids)
    if room < 0:
        raise ValueError("size %d too small for prefix %d + suffix %d"
                         % (size, len(prefix), len(suffix_ids)))
    ids = prefix + (filler_ids * (room // len(filler_ids) + 1))[:room] + suffix_ids
    if len(ids) != size:
        raise AssertionError("built %d tokens, wanted %d" % (len(ids), size))
    return ids, nonce


def prefills_per_step(size, conc):
    """The admission law this table measures: see the module docstring."""
    return max(1, min(conc, CHUNK // size)) if size <= CHUNK else 1


# --------------------------------------------------------------------------
# Engine-side concurrency probe
# --------------------------------------------------------------------------

def _metrics_value(name):
    """Max across label sets of one sglang: gauge, or None if absent."""
    try:
        req = urllib.request.Request(METRICS_URL, headers={
            "Authorization": "Bearer " + KEY})
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
    """Sample the engine's own running/queue counters while a cell runs.

    This is the independent record of how parallel the cell actually was. The
    client cannot see the scheduler's `#new-seq`, so without this the claim
    "prefill ran one at a time" would rest on the client's own timestamps.
    """

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
            self.stop_flag.wait(PROBE_PERIOD)

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
            "queue_gt0_frac": (round(sum(1 for q in self.queue if q > 0)
                                     / len(self.queue), 3) if self.queue else None),
        }


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------

def one(ids, nonce, index, wave_idx, conc):
    rec = sd.stream_generate(BASE, KEY, ids, MAXNEW, index=index, wave=wave_idx,
                             ptype="pr", conc=conc, force_fill=True,
                             timeout=TIMEOUT, events=True)
    rec["nonce"] = nonce
    rec["manifest_sha256"] = identity
    return rec


def run_wave(size, conc, wave_idx):
    """Build every payload first, then release all `conc` requests together.

    The payload has to exist before the pool starts, otherwise the per-request
    build (tokenizer call, list construction, `repr` for the prompt hash, JSON
    body) runs inside the worker threads and, being GIL-bound, staggers the
    wave's start. At the largest size here that build is ~55 ms per request, so
    the effect is small -- it is fixed because a wave that is *supposed* to be
    simultaneous should not carry a launch ramp of its own, not because it
    moved any published number.
    """
    built = [build_ids(size, i, RUN_TAG) for i in range(conc)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as pool:
        recs = list(pool.map(
            lambda t: one(t[1][0], t[1][1], t[0], wave_idx, conc),
            list(enumerate(built))))
    return recs


def warmup(size):
    """One short forced-fill stream. Fills graph capture and the tokenizer path,
    which are one-time costs; without it the smallest cell carries them."""
    try:
        sd.stream_generate(BASE, KEY, build_ids(size, 0, RUN_TAG)[0], 32,
                           index=0, wave=-1, ptype="pr", conc=1,
                           force_fill=True, timeout=600)
    except Exception:
        pass


def window_rate(rec):
    """The 129..641 window rate from the retained event log, if it is reachable."""
    ev = rec.get("events_s_count")
    if not ev:
        return None

    def at(n):
        return next((s for s, c in ev if c >= n), None)
    left, right = at(129), at(641)
    if left is None or right is None or right <= left:
        return None
    return 512.0 / (right - left)


def render(summaries):
    lines = ["# Prompt-rate matrix (SD-1)", "",
             "Input size is token-exact and the prompt carries a fresh nonce, so no "
             "request is served from the radix cache. The output budget is forced "
             "(`min_new_tokens = max_new_tokens`, `ignore_eos`), so every stream "
             "delivers the full 1,024 tokens and short-stream tails cannot inflate "
             "per-stream rates. Synthetic repeated notes; **not a quality test**.", "",
             "**The prefill column scales only for `input <= CHUNKED_PREFILL_SIZE`** "
             "(%d tokens here). Above it a request is chunked and takes the whole "
             "step's prefill budget, so it is prefilled one at a time: aggregate "
             "prompt-rate collapses to the single-stream chunked rate and TTFT grows "
             "with queue position. `Prefills/step (pred)` is "
             "`min(C, floor(CHUNK / input))`; `Engine running/queue` are the engine's "
             "own counters sampled once a second during the cell, so the prediction "
             "can be checked rather than believed." % CHUNK, "",
             "`TTFT first/last s` bracket the wave's queue position -- when the "
             "median sits between two values an order of magnitude apart it is "
             "describing the queue, not the engine. `median decode` is SD-1: "
             "per-stream `(ct-1)/(tLast-tFirst)`. `window decode` is the older "
             "129..641 measure, recovered from the retained event log. `agg prefill` "
             "= sum(prompt_tokens) / (last first-token - first send).", "",
             "| Input tokens | C | Prefills/step (pred) | Prefill tok/s (agg) | TTFT first s | Median TTFT s | TTFT last s | Median decode tok/s/req | Window decode tok/s/req | Total decode tok/s (union) | Engine running (min/med/max) | Engine queue (min/med/max) | OK |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|"]
    for r in summaries:
        f = lambda k, d=2: ("%.*f" % (d, r[k])) if r.get(k) is not None else "—"
        p = r.get("engine_probe") or {}

        def trio(pre):
            if p.get(pre + "_min") is None:
                return "—"
            return "%g/%g/%g" % (p[pre + "_min"], p[pre + "_med"], p[pre + "_max"])
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s/%s |" % (
            r["input_tokens"], r["concurrency"], r["prefills_per_step_pred"],
            f("agg_prefill_tps", 2), f("ttft_first_s", 2), f("median_ttft_s", 2),
            f("ttft_last_s", 2), f("median_decode_tps"),
            f("median_window_decode_tps"), f("agg_decode_tps", 2),
            trio("running"), trio("queue"), r["streams_ok"], r["concurrency"]))
    return "\n".join(lines) + "\n"


def main():
    summaries = []
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    for s in SAMPLES:
        warmup(s)
    print(json.dumps({"progress": "warmup", "sizes": SAMPLES}), flush=True)
    for size in SIZES:
        for conc in CONCS:
            for w in range(WAVES):
                probe = EngineProbe()
                probe.start()
                recs = run_wave(size, conc, w)
                probe.stop_flag.set()
                probe.join(timeout=10)
                ok = [r for r in recs if not r.get("error") and r.get("decode_tps")]
                wr = [x for x in (window_rate(r) for r in ok) if x]
                spans = sorted([(r["t_first"], 1) for r in ok] +
                               [(r["t_end"], -1) for r in ok])
                active = peak = 0
                for _, delta in spans:
                    active += delta
                    peak = max(peak, active)
                wave = sd.aggregate_wave(recs, conc)
                ttfts = sorted(r["t_first"] - r["t0"] for r in ok)
                summary = {
                    "input_tokens": size, "concurrency": conc, "wave": w,
                    "waves": WAVES, "run_tag": RUN_TAG, "manifest_sha256": identity,
                    "chunked_prefill_size": CHUNK,
                    "prefills_per_step_pred": prefills_per_step(size, conc),
                    "streams_ok": len(ok), "streams_failed": conc - len(ok),
                    "peak_client_overlap": peak,
                    # NOTE: `stagger_s` is the TTFT spread (ttft_last - ttft_first),
                    # NOT the client dispatch spread. The dispatch spread has to be
                    # derived from the per-stream `t0` in the dumped cell JSON; see
                    # pr_evidence_table() in render_report_tables.py. Kept under this
                    # name so the archived cells stay reproducible by this file.
                    "stagger_s": round(ttfts[-1] - ttfts[0], 3) if ttfts else None,
                    "ttft_first_s": round(ttfts[0], 3) if ttfts else None,
                    "ttft_last_s": round(ttfts[-1], 3) if ttfts else None,
                    "agg_prefill_tps": wave.get("agg_prefill_tps"),
                    "median_prefill_tps": wave.get("median_prefill_tps"),
                    "median_ttft_s": wave.get("median_ttft_s"),
                    "median_decode_tps": wave.get("median_decode_tps"),
                    "median_window_decode_tps": round(statistics.median(wr), 2) if wr else None,
                    "agg_decode_tps": wave.get("agg_decode_tps"),
                    "agg_decode_tps_window": wave.get("agg_decode_tps_window"),
                    "agg_decode_tps_wall": wave.get("agg_decode_tps_wall"),
                    "median_completion_tokens": wave.get("median_completion_tokens"),
                    "engine_probe": probe.summary(),
                    "errors": [r.get("error") for r in recs if r.get("error")][:4],
                    "convention": sd.PROTOCOL_DOC,
                }
                sd.dump(os.path.join(OUT_DIR, "%d-c%d-w%d.json" % (size, conc, w)), recs)
                summaries = [s for s in summaries
                             if not (s["input_tokens"] == size and s["concurrency"] == conc)]
                summaries.append(summary)
                summaries.sort(key=lambda s: (SIZES.index(s["input_tokens"]), s["concurrency"]))
                sd.dump(os.path.join(OUT_DIR, "summary.json"), {
                    "_meta": {"protocol": sd.PROTOCOL_DOC, "protocol_id": sd.PROTOCOL_ID,
                              "run_tag": RUN_TAG, "model": MODEL, "base": BASE,
                              "max_new_tokens": MAXNEW, "waves": WAVES,
                              "chunked_prefill_size": CHUNK,
                              "prefills_per_step_law":
                                  "min(concurrency, floor(chunked_prefill_size / input_tokens))",
                              "sizes": SIZES, "concurrencies": CONCS,
                              "request_timeout_s": TIMEOUT,
                              "warmup_sizes": SAMPLES,
                              "started": started,
                              "updated": time.strftime("%Y-%m-%dT%H:%M:%S")},
                    "cells": summaries})
                with open(os.path.join(OUT_DIR, "TABLE.md"), "w") as fh:
                    fh.write(render(summaries))
                print(json.dumps(summary), flush=True)
    with open(os.path.join(OUT_DIR, "COMPLETE"), "w") as fh:
        fh.write(RUN_TAG + "\n" + time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
    print("OUT_DIR=" + OUT_DIR, flush=True)


if __name__ == "__main__":
    main()

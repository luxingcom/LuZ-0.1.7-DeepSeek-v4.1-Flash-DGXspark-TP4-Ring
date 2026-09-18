#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""de_matrix_v3.py -- DE decode matrix on SD-1. The board's decode table.

`de_matrix.py` (free-form) and `de_matrix_structured.py` (schema-constrained) measure two
other, still-legitimate things and are kept unchanged: they are the only reproduction path
for their own outputs. This harness is the one that produces the **reported** decode table.

Three things this harness refuses to do, and why
------------------------------------------------
1. **No grammar.** `de_matrix_structured.py` sends xgrammar `json_schema`, so every step
   goes through a grammar mask -- a real per-token cost that no other row on the board
   pays. It additionally makes `ignore_eos` conditional: once the schema is satisfiable,
   EOS fires anyway, so its cells carry streams far shorter than the budget, and a short
   stream's rate is inflated by its own tail. A grammar-constrained row and a free row are
   **not two points on one axis**; putting them in one table compares a constrained decoder
   against a free one, and the resulting gap is the cost of guided decoding, not a property
   of the output shape.
2. **No unstated aggregation.** `de_matrix.py` reports the upper median
   (`sorted(x)[n//2]`), a hardcoded `512.0` prefill numerator and a single wave -- each of
   which is a different measurement from the true median over three waves with the engine's
   own `prompt_tokens`. The convention lives in `sd_protocol.py`; this file imports it and
   does not restate it, because a second copy is how a board ends up with three.
3. **No recalled budget.** The output budget is force-filled (`min_tokens = max_tokens`,
   `ignore_eos`, empty stop list), retried if the server strips those parameters.

sparkDash's method, which this file follows
-------------------------------------------
Its structured/prose/code/json are four *prompts*. It never sends `response_format`, a
grammar or guided JSON. Output types are labels; the only thing that varies across the four
rows is the prompt.

Guided decoding is not dropped, it is moved to its own same-channel A/B in `grammar_ab.py`.

Env
---
TYPES          default "structured,prose,code,json"
CONCURRENCIES  default "1,2,4,8,16"
WAVES          default 3
MAXTOK         default 2048           (fp4-indexer A/B uses MAXTOK=256)
BASE           default http://127.0.0.1:8899
MODEL          default deepseek-v4.1-flash
KEY_FILE       default /state/api-key
RUN_TAG        default generated; goes into every prompt and into _meta
OUT_DIR        default /state/de-v3-<timestamp>

Output
------
<OUT_DIR>/de_v3_matrix.json            cells + _meta
<OUT_DIR>/de_<type>_c<N>.json          raw per-stream records, per cell
"""
import concurrent.futures
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sd_protocol as sd  # noqa: E402

BASE = os.environ.get("BASE", "http://127.0.0.1:8899")
MODEL = os.environ.get("MODEL", "deepseek-v4.1-flash")
KEY = sd.read_key()
TYPES = [t.strip() for t in os.environ.get("TYPES", "structured,prose,code,json").split(",")]
CONCS = [int(x) for x in os.environ.get("CONCURRENCIES", "1,2,4,8,16").split(",")]
WAVES = int(os.environ.get("WAVES", "3"))
MAXTOK = int(os.environ.get("MAXTOK", "2048"))
RUN_TAG = os.environ.get("RUN_TAG") or sd.new_run_tag()
OUT_DIR = sd.out_dir("de-v3")
TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "3600"))


def run_wave(ptype, conc, wave_idx):
    prompts = [sd.build_prompt(ptype, conc, i, RUN_TAG) for i in range(conc)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as ex:
        recs = list(ex.map(
            lambda t: sd.stream_chat(BASE, KEY, MODEL, t[1], MAXTOK, index=t[0],
                                     wave=wave_idx, ptype=ptype, conc=conc,
                                     timeout=TIMEOUT),
            list(enumerate(prompts))))
    return recs


def warmup(ptype):
    """One short stream per type. Fills graphs and the tokenizer path, which are
    one-time costs; without it the first wave of the first cell carries them."""
    try:
        sd.stream_chat(BASE, KEY, MODEL, sd.build_prompt(ptype, 1, 0, RUN_TAG),
                       32, force_fill=False, timeout=300)
    except Exception:
        pass


def main():
    results = {}
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    for ptype in TYPES:
        warmup(ptype)
        for c in CONCS:
            waves, raw_all = [], []
            for w in range(WAVES):
                recs = run_wave(ptype, c, w)
                waves.append(sd.aggregate_wave(recs, c))
                raw_all.append(recs)
                print(json.dumps({"progress": "wave", "type": ptype, "conc": c,
                                  "wave": w, "ok": waves[-1]["streams_ok"],
                                  "median_decode_tps": waves[-1].get("median_decode_tps")}),
                      flush=True)
            cell = sd.cell_summary(waves, raw_all, ptype=ptype, conc=c,
                                   max_tokens=MAXTOK, run_tag=RUN_TAG)
            results["DE-V3_%s_C%d" % (ptype, c)] = cell
            print(json.dumps(cell), flush=True)
            sd.dump(os.path.join(OUT_DIR, "de_%s_c%d.json" % (ptype, c)), raw_all)
            # keep the summary current on disk: a long run must be readable
            # while it is still going
            sd.dump(os.path.join(OUT_DIR, "de_v3_matrix.json"), {
                "_meta": {"protocol": sd.PROTOCOL_DOC, "protocol_id": sd.PROTOCOL_ID,
                          "run_tag": RUN_TAG, "model": MODEL, "base": BASE,
                          "max_tokens": MAXTOK, "waves": WAVES,
                          "concurrencies": CONCS, "types": TYPES,
                          "started": started, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")},
                **results})
    # leave a marker so a truncated run is distinguishable from a complete one
    with open(os.path.join(OUT_DIR, "COMPLETE"), "w") as f:
        f.write(RUN_TAG + "\n" + time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
    print("OUT_DIR=" + OUT_DIR, flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""grammar_ab.py -- what guided decoding costs, as a same-channel A/B.

Guided decoding is not part of SD-1 and must not be mixed into a type row: the
structured/`json` rows on the board are prompt labels, and xgrammar puts a mask
in front of every decode step, which no other row pays. That does not make the
cost unmeasurable -- it makes it a *separate* measurement, and this is it.

Design: identical prompt *body*, identical channel, identical accounting. The only
thing that differs between arm N and arm G is whether `sampling_params.json_schema`
is present. Both arms are token-exact on the native endpoint. Every request draws
its own nonce, so neither arm can be served from the radix cache -- note that this
means the two arms send *different* prompts, which is deliberate: with one shared
prompt per index, whichever arm ran second ran on a prefix the first arm had just
filled, and the A/B would be measuring that instead of the grammar.

The schema carries `minItems: 400`. Under a grammar `ignore_eos` stops being
absolute -- once the schema can be satisfied the grammar emits EOS regardless --
so a satisfiable schema would end the stream early and the early rows would be
the ones being compared. The floor keeps the budget reachable.

Result shape: a delta at the same prompt, per concurrency. A negative delta is
the price of the constraint, and it is the only honest way to quote one.

Env
---
CONCURRENCIES  default "1,2,4,8,16"
WAVES          default 3
MAXTOK         default 2048
MODEL_PATH     default /models/DeepSeek-V4.1-Flash
OUT_DIR        default /state/grammar-ab-<timestamp>

Output
------
<OUT_DIR>/grammar_ab.json          cell summaries
<OUT_DIR>/<arm>_c<N>.json          raw per-stream records, per arm and per cell.
                                   These are what make a cell auditable below its
                                   own level: a cell median with no records behind
                                   it is a number nobody can check, and a
                                   surprising result is exactly the one that needs
                                   checking, not the one that can be taken on
                                   trust. Keep them.
"""
import concurrent.futures
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sd_protocol as sd  # noqa: E402

BASE = os.environ.get("BASE", "http://127.0.0.1:8899")
MODEL = os.environ.get("MODEL", "deepseek-v4.1-flash")
KEY = sd.read_key()
CONCS = [int(x) for x in os.environ.get("CONCURRENCIES", "1,2,4,8,16").split(",")]
WAVES = int(os.environ.get("WAVES", "3"))
MAXTOK = int(os.environ.get("MAXTOK", "2048"))
RUN_TAG = os.environ.get("RUN_TAG") or sd.new_run_tag()
OUT_DIR = sd.out_dir("grammar-ab")
TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "3600"))

_model = Path(os.environ.get("MODEL_PATH", "/models/DeepSeek-V4.1-Flash"))
sys.path.insert(0, str(_model / "encoding"))
from encoding import encode_messages  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402
_tok = Tokenizer.from_file(str(_model / "tokenizer.json"))

SCHEMA_JSON = json.dumps(sd.GRAMMAR_SCHEMAS["json"])


def build_ids(index, run_tag):
    """The `json` prompt of SD-1, as token ids, with a fresh front nonce.

    Token-exact because the native endpoint takes ids, and re-templated here so
    the prompt body is the same one the chat channel would have sent.
    """
    text = "[%s r%d] %s" % (sd.new_nonce(run_tag, "sd1g"), index,
                            sd.DECODE_JSON_PROMPT + sd.FILL_TO_MAX_SUFFIX)
    templated = encode_messages(
        [dict(role="user", content=text)], thinking_mode="chat").split("<｜Assistant｜>")[0]
    return _tok.encode(templated, add_special_tokens=False).ids


def one(arm, index, wave_idx):
    ids = build_ids(index, RUN_TAG)
    gj = SCHEMA_JSON if arm == "grammar" else None
    rec = sd.stream_generate(BASE, KEY, ids, MAXTOK, index=index, wave=wave_idx,
                             ptype="json", conc=None, force_fill=True,
                             timeout=TIMEOUT, grammar_json=gj)
    rec["arm"] = arm
    # Carry the schema's digest into the record. Without it the archive can only
    # assert which arm *was meant* to be constrained -- the `arm` label is written
    # by the same process that decided it, so on its own it is not evidence.
    rec["grammar_sha16"] = hashlib.sha256(gj.encode()).hexdigest()[:16] if gj else None
    return rec


def main():
    results = {}
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    for c in CONCS:
        arms = {"free": [], "grammar": []}
        raw = {"free": [], "grammar": []}
        for w in range(WAVES):
            # alternate within the wave so any drift over time hits both arms
            for arm in (("free", "grammar") if w % 2 == 0 else ("grammar", "free")):
                with concurrent.futures.ThreadPoolExecutor(max_workers=c) as ex:
                    recs = list(ex.map(lambda i: one(arm, i, w), range(c)))
                arms[arm].append(sd.aggregate_wave(recs, c))
                raw[arm].append(recs)
        # Write the raw records *before* the summary, so a crash between the two
        # leaves the auditable half rather than the summarised one.
        for arm in ("free", "grammar"):
            sd.dump(os.path.join(OUT_DIR, "%s_c%d.json" % (arm, c)), raw[arm])
        cell = {"conc": c, "max_tokens": MAXTOK, "waves": WAVES, "run_tag": RUN_TAG}
        for arm, waves in arms.items():
            okw = [w for w in waves if w.get("streams_ok")]
            cell[arm] = {
                "ok_waves": len(okw),
                "median_decode_tps": round(statistics.median(
                    [w["median_decode_tps"] for w in okw]), 2) if okw else None,
                "agg_decode_tps": round(statistics.median(
                    [w["agg_decode_tps"] for w in okw if w.get("agg_decode_tps") is not None]), 1)
                    if okw else None,
                "median_prefill_tps": round(statistics.median(
                    [w["median_prefill_tps"] for w in okw if w.get("median_prefill_tps")]), 1)
                    if okw else None,
                "median_ttft_s": round(statistics.median(
                    [w["median_ttft_s"] for w in okw]), 4) if okw else None,
                "median_completion_tokens": statistics.median(
                    [w["median_completion_tokens"] for w in okw]) if okw else None,
            }
        f, g = cell["free"], cell["grammar"]
        if f.get("median_decode_tps") and g.get("median_decode_tps"):
            cell["decode_delta_pct"] = round(
                (g["median_decode_tps"] / f["median_decode_tps"] - 1) * 100, 1)
        if f.get("agg_decode_tps") and g.get("agg_decode_tps"):
            cell["agg_delta_pct"] = round(
                (g["agg_decode_tps"] / f["agg_decode_tps"] - 1) * 100, 1)
        if f.get("median_prefill_tps") and g.get("median_prefill_tps"):
            cell["prefill_delta_pct"] = round(
                (g["median_prefill_tps"] / f["median_prefill_tps"] - 1) * 100, 1)
        cell["convention"] = ("native /generate both arms; same prompt body, one nonce "
                              "per request so neither arm warms the other's prefix; "
                              "only json_schema differs; "
                              "schema carries minItems=400 so the grammar cannot satisfy "
                              "it and stop early. " + sd.PROTOCOL_DOC)
        results["GRAMMAR_AB_C%d" % c] = cell
        print(json.dumps(cell), flush=True)
        sd.dump(os.path.join(OUT_DIR, "grammar_ab.json"), {
            "_meta": {"protocol_id": sd.PROTOCOL_ID, "run_tag": RUN_TAG, "started": started,
                      "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}, **results})
    with open(os.path.join(OUT_DIR, "COMPLETE"), "w") as fh:
        fh.write(RUN_TAG + "\n")
    print("OUT_DIR=" + OUT_DIR, flush=True)


if __name__ == "__main__":
    main()

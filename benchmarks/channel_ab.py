#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""channel_ab.py -- chat channel vs native /generate, same prompt, same wave.

Why this exists
---------------
The grammar A/B (`grammar_ab.py`) found the constrained arm *faster* than the free
arm at every concurrency -- +4.5% at C1 up to +98% on the aggregate at C16. That is
the opposite of the expected sign, and before quoting it there is one confound to
remove: the free arm runs on the native `/generate` channel while the DE stage's
unconstrained `json` row runs on the chat channel, and those two sit ~27% apart at
C16 (21.88 vs 29.90 tok/s/req). If the native channel is simply slower for the same
unconstrained prompt, then "the grammar makes decoding faster" is really "the grammar
recovers what the channel gave up" -- two very different sentences.

So: measure the channel on its own. Both arms send the same prompt body, unconstrained,
force-filled, one nonce per request, alternating *within* each wave so any drift over
time hits both.

This does not re-open the grammar question. It fixes the baseline the grammar arm is
read against.

Env
---
CONCURRENCIES  default "1,16"
WAVES          default 3
MAXTOK         default 2048
MODEL_PATH     default /models/DeepSeek-V4.1-Flash
OUT_DIR        default /state/channel-ab-<timestamp>

Output
------
<OUT_DIR>/channel_ab.json          cell summaries
<OUT_DIR>/<arm>_c<N>.json          raw per-stream records, per arm and cell

Do not run this while a matrix is running.
"""
import concurrent.futures
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
CONCS = [int(x) for x in os.environ.get("CONCURRENCIES", "1,16").split(",")]
WAVES = int(os.environ.get("WAVES", "3"))
MAXTOK = int(os.environ.get("MAXTOK", "2048"))
RUN_TAG = os.environ.get("RUN_TAG") or sd.new_run_tag()
OUT_DIR = sd.out_dir("channel-ab")
TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "3600"))

_model = Path(os.environ.get("MODEL_PATH", "/models/DeepSeek-V4.1-Flash"))
sys.path.insert(0, str(_model / "encoding"))
from encoding import encode_messages  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402

_tok = Tokenizer.from_file(str(_model / "tokenizer.json"))


def native_ids(text):
    """The same body the chat arm sends, pre-templated and token-exact."""
    templated = encode_messages(
        [dict(role="user", content=text)], thinking_mode="chat").split("<｜Assistant｜>")[0]
    return _tok.encode(templated, add_special_tokens=False).ids


def one(arm, index, wave_idx):
    if arm == "chat":
        text = sd.build_prompt("json", 1, index, RUN_TAG)
        rec = sd.stream_chat(BASE, KEY, MODEL, text, MAXTOK, index=index,
                             wave=wave_idx, ptype="json", conc=None,
                             force_fill=True, timeout=TIMEOUT)
    else:
        text = sd.build_prompt("json", 1, index, RUN_TAG)
        rec = sd.stream_generate(BASE, KEY, native_ids(text), MAXTOK, index=index,
                                 wave=wave_idx, ptype="json", conc=None,
                                 force_fill=True, timeout=TIMEOUT)
    rec["arm"] = arm
    return rec


def main():
    results = {}
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    for c in CONCS:
        arms = {"chat": [], "native": []}
        raw = {"chat": [], "native": []}
        for w in range(WAVES):
            order = ("chat", "native") if w % 2 == 0 else ("native", "chat")
            for arm in order:
                with concurrent.futures.ThreadPoolExecutor(max_workers=c) as ex:
                    recs = list(ex.map(lambda i: one(arm, i, w), range(c)))
                arms[arm].append(sd.aggregate_wave(recs, c))
                raw[arm].append(recs)
        for arm in ("chat", "native"):
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
                "median_chars_per_token": round(statistics.median(
                    [w["median_chars_per_token"] for w in okw
                     if w.get("median_chars_per_token")]), 3) if okw else None,
            }
        ch, na = cell["chat"], cell["native"]
        if ch.get("median_decode_tps") and na.get("median_decode_tps"):
            cell["native_vs_chat_pct"] = round(
                (na["median_decode_tps"] / ch["median_decode_tps"] - 1) * 100, 1)
        if ch.get("agg_decode_tps") and na.get("agg_decode_tps"):
            cell["native_vs_chat_agg_pct"] = round(
                (na["agg_decode_tps"] / ch["agg_decode_tps"] - 1) * 100, 1)
        cell["convention"] = ("same prompt body, unconstrained, force-filled, one nonce per "
                              "request, arms alternated within each wave; the only variable "
                              "is the channel. Negative native_vs_chat = the native channel "
                              "is slower for an identical unconstrained request. "
                              + sd.PROTOCOL_DOC)
        results["CHANNEL_AB_C%d" % c] = cell
        print(json.dumps(cell), flush=True)
        sd.dump(os.path.join(OUT_DIR, "channel_ab.json"), {
            "_meta": {"protocol_id": sd.PROTOCOL_ID, "run_tag": RUN_TAG, "started": started,
                      "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}, **results})
    with open(os.path.join(OUT_DIR, "COMPLETE"), "w") as fh:
        fh.write(RUN_TAG + "\n")
    print("OUT_DIR=" + OUT_DIR, flush=True)


if __name__ == "__main__":
    main()

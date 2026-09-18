#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cache_effect_probe.py -- what a repeated prompt is actually worth, by size.

Why this exists
---------------
The SD-1 board claims every request is cold. On 09-18 that claim was found to be
false in four places at once (see the note above `sd_protocol.new_nonce`), and the
expensive one was `gw_ab_v2`'s prefill arm: a single 131,072-token prompt sent to
the gateway and then, byte for byte, to the direct endpoint. That is only a defect
if a repeat is worth something. So measure what a repeat is worth.

`preflight_sd1.py` already probes the cache, but at 2,895 tokens that probe is
underpowered: TTFT on this stack carries ~0.25 s of fixed scheduling and transport
cost, and the prefill of a few thousand tokens hides inside it -- the observed
ratio on a repeat was 1.03, i.e. no signal either way. This probe uses sizes where
prefill dominates the TTFT, so the ratio means something.

Method, per size
----------------
  cold      a prompt with a fresh nonce
  repeat    the *same* prompt again, byte for byte
  distinct  the same body with a *different* nonce

  worth = 1 - ttft_repeat / ttft_cold

Self-check, printed rather than assumed: prompt_sha16(cold) must equal
prompt_sha16(repeat) and differ from prompt_sha16(distinct). If the two hashes in
the first pair do not match, the probe is not measuring what it claims.

Do NOT run this while a matrix is running. A 131k-token prefill injected into a
C=1 measurement is a contamination, not a diagnostic.

Env
---
BASE      default http://127.0.0.1:8899
MODEL     default deepseek-v4.1-flash
KEY_FILE  default /state/api-key
SIZES     default "2048,32768,131072"
OUT_DIR   default /state/cache-probe

Output
------
<OUT_DIR>/cache_effect.json   one row per size, plus the hashes
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sd_protocol as sd  # noqa: E402

BASE = os.environ.get("BASE", "http://127.0.0.1:8899")
MODEL = os.environ.get("MODEL", "deepseek-v4.1-flash")
KEY = sd.read_key()
SIZES = [int(x) for x in os.environ.get("SIZES", "2048,32768,131072").split(",")]
OUT_DIR = sd.out_dir("cache-probe")
RUN_TAG = sd.new_run_tag()

HEADER = "Ignore the filler below and reply with OK when done."
FILLER = " the "
PROBE_TOKENS = 16


def body_for(size):
    """~`size` tokens of filler. Actual token count is reported, not assumed."""
    return HEADER + "\n" + FILLER * max(1, size - len(HEADER) // 4)


def send(prompt):
    return sd.stream_chat(BASE, KEY, MODEL, prompt, PROBE_TOKENS, index=0,
                          ptype="cacheprobe", conc=1, force_fill=True, timeout=1800)


def main():
    rows = []
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    for size in SIZES:
        # each size gets its own body, so nothing here can warm a different size
        shared = body_for(size)
        # the nonce is drawn once and kept: the repeat must be the same string
        cold_prompt = sd.new_nonce(RUN_TAG, "cp") + " " + shared
        cold = send(cold_prompt)
        repeat = send(cold_prompt)
        # ... and the control must differ only in the nonce
        distinct = send(sd.new_nonce(RUN_TAG, "cp") + " " + shared)
        row = {
            "size_requested": size,
            "prompt_tokens": cold.get("prompt_tokens"),
            "ttft_cold_s": cold.get("ttft_s"),
            "ttft_repeat_s": repeat.get("ttft_s"),
            "ttft_distinct_s": distinct.get("ttft_s"),
            "prefill_tps_cold": cold.get("prefill_tps"),
            "prefill_tps_repeat": repeat.get("prefill_tps"),
            "sha_cold": cold.get("prompt_sha16"),
            "sha_repeat": repeat.get("prompt_sha16"),
            "sha_distinct": distinct.get("prompt_sha16"),
            "errors": [r.get("error") for r in (cold, repeat, distinct) if r.get("error")],
        }
        row["selfcheck_repeat_is_byte_identical"] = row["sha_cold"] == row["sha_repeat"]
        row["selfcheck_distinct_differs"] = row["sha_cold"] != row["sha_distinct"]
        if row["ttft_cold_s"] and row["ttft_repeat_s"]:
            row["worth_of_a_repeat"] = round(1 - row["ttft_repeat_s"] / row["ttft_cold_s"], 4)
        rows.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
    payload = {
        "_meta": {
            "run_tag": RUN_TAG, "model": MODEL, "base": BASE,
            "probe_tokens": PROBE_TOKENS, "sizes": SIZES,
            "started": started, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "note": "worth_of_a_repeat = 1 - ttft_repeat/ttft_cold. Positive means the "
                    "engine served the second identical prompt from its radix cache. "
                    "This is the quantity that made a shared prompt in gw_ab_v2's "
                    "prefill arm a real defect rather than a theoretical one.",
        },
        "rows": rows,
    }
    sd.dump(os.path.join(OUT_DIR, "cache_effect.json"), payload)
    print("OUT_DIR=" + OUT_DIR, flush=True)


if __name__ == "__main__":
    main()

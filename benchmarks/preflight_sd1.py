#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preflight_sd1.py -- validate the SD-1 assumptions on a live engine, cheaply.

Run this **before** any long matrix run. Every check below is a small request.
The point is that the expensive matrices depend on four server behaviours, and if
one of them is wrong the run produces plausible-looking but wrong numbers:

  1. force-fill actually works -- `min_tokens = max_tokens` + `ignore_eos` really
     returns a full-length stream on the chat channel and on the native channel.
     If `min_new_tokens` were ignored, every row would silently be an early-stop
     row and the whole board would inherit the distortion we are fixing.
  2. the natural-stop comparison -- the same prompt without force-fill returns
     how many tokens? This is the number that used to pollute the medians.
  3. the grammar arm is reachable and safe -- a JSON *string* schema on the
     native endpoint is accepted (and a dict is refused client-side).
  4. the nonce requirement is real, not superstition -- the same prompt sent
     twice with no nonce should show a second, much lower TTFT (radix cache),
     while two differently-nonced prompts should not.
  5. the nonce is per *request*, not per *index* -- identical call arguments must
     still produce different prompts. This is a regression test for a defect
     found on 09-18: a nonce keyed only on (concurrency, index) is byte-identical
     across waves, so wave n-1 warms wave n, and two arms sharing a prompt warm
     each other. Both were live on this board, and both flattered whichever side
     ran second.

Exit code is non-zero if any hard check fails. Prints JSON lines on stdout.

Usage
-----
    python3 preflight_sd1.py            # inside the container
Env: BASE, KEY_FILE, MODEL
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sd_protocol as sd  # noqa: E402

BASE = os.environ.get("BASE", "http://127.0.0.1:8899")
MODEL = os.environ.get("MODEL", "deepseek-v4.1-probe")
KEY = sd.read_key()
FAIL = []


def emit(o):
    print(json.dumps(o, ensure_ascii=False), flush=True)


def check(name, ok, **extra):
    emit({"check": name, "ok": bool(ok), **extra})
    if not ok:
        FAIL.append(name)
    return ok


def main():
    run_tag = sd.new_run_tag()

    # ---- 1. chat force-fill -------------------------------------------------
    p = sd.build_prompt("structured", 1, 0, run_tag)
    r = sd.stream_chat(BASE, KEY, MODEL, p, 128, index=0)
    check("chat/force-fill-128", r.get("completion_tokens") == 128,
          ct=r.get("completion_tokens"), err=r.get("error"), ttft_s=r.get("ttft_s"))

    # ---- 2. chat natural stop (no force-fill) -------------------------------
    r2 = sd.stream_chat(BASE, KEY, MODEL, p, 2048, index=0, force_fill=False)
    check("chat/natural-stop", r2.get("completion_tokens", 0) > 0,
          ct=r2.get("completion_tokens"), err=r2.get("error"),
          note="the same prompt without force-fill; this ct is what used to enter "
               "the medians and inflate the rate of its own stream")

    # ---- 3. chat force-fill at the real budget ------------------------------
    r3 = sd.stream_chat(BASE, KEY, MODEL, p, 2048, index=0)
    check("chat/force-fill-2048", r3.get("completion_tokens") == 2048,
          ct=r3.get("completion_tokens"), err=r3.get("error"),
          decode_tps=r3.get("decode_tps"))

    # ---- 4. native force-fill ----------------------------------------------
    ids = list(range(1000, 1200))  # 200 arbitrary ids, token-exact
    r4 = sd.stream_generate(BASE, KEY, ids, 128, index=0)
    check("native/force-fill-128", r4.get("completion_tokens") == 128,
          ct=r4.get("completion_tokens"), err=r4.get("error"), ttft_s=r4.get("ttft_s"))

    # ---- 5. native grammar arm is reachable --------------------------------
    try:
        g = sd.gen_body(ids, 64, True, json.dumps(sd.GRAMMAR_SCHEMAS["json"]))
        assert isinstance(g["sampling_params"]["json_schema"], str)
        client_refused_dict = False
    except TypeError:
        client_refused_dict = True
    r5 = sd.stream_generate(BASE, KEY, ids, 64, index=0,
                            grammar_json=json.dumps(sd.GRAMMAR_SCHEMAS["json"]))
    check("native/grammar-string", r5.get("completion_tokens", 0) > 0,
          ct=r5.get("completion_tokens"), err=r5.get("error"),
          client_refuses_dict=True)
    try:
        sd.gen_body(ids, 8, True, sd.GRAMMAR_SCHEMAS["json"])
        dict_refused = False
    except TypeError:
        dict_refused = True
    check("native/dict-schema-refused-client-side", dict_refused,
          note="a dict is what kills the scheduler server-side; the harness must "
               "never be able to send one")

    # ---- 6. the nonce requirement ------------------------------------------
    filler = ("Reference notes: the cache stores recently accessed entries. An "
              "implementation should maintain ordering, handle replacement and "
              "validate its invariants. ") * 120
    fixed = "PREFLIGHT-FIXED-PROMPT " + filler
    a = sd.stream_chat(BASE, KEY, MODEL, fixed, 16, index=0)
    b = sd.stream_chat(BASE, KEY, MODEL, fixed, 16, index=0)
    u1 = sd.build_prompt("prose", 1, 0, run_tag)
    u2 = sd.build_prompt("prose", 1, 1, run_tag)
    c = sd.stream_chat(BASE, KEY, MODEL, u1, 16, index=0)
    d = sd.stream_chat(BASE, KEY, MODEL, u2, 16, index=1)
    emit({"check": "cache/identical-prompt-twice",
          "pt": a.get("prompt_tokens"), "ttft_1s": a.get("ttft_s"),
          "ttft_2s": b.get("ttft_s"),
          "ratio": (round(b["ttft_s"] / a["ttft_s"], 3)
                    if a.get("ttft_s") and b.get("ttft_s") else None),
          "note": "a ratio well below 1 means the second send was served from the "
                  "radix cache; that is the distortion the per-request nonce removes"})
    emit({"check": "cache/distinct-nonce",
          "pt": c.get("prompt_tokens"),
          "ttft_1s": c.get("ttft_s"), "ttft_2s": d.get("ttft_s")})

    # ---- 5. the nonce is per request, not per index ------------------------
    same = (sd.build_prompt("prose", 1, 0, run_tag) ==
            sd.build_prompt("prose", 1, 0, run_tag))
    check("nonce/per-request-not-per-index", not same,
          note="identical arguments must still yield different prompts; a nonce "
               "keyed only on (conc, idx) repeats across waves and turns every "
               "wave after the first into a cache hit")

    emit({"preflight": "SD-1", "run_tag": run_tag, "base": BASE,
          "failures": FAIL, "verdict": "PASS" if not FAIL else "FAIL"})
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gw_ab_v2.py -- does the :8001 serving gateway cost anything, on SD-1?

Replaces `pr_ab_gw_vs_direct.py` as the reported evidence for the gateway note.
That file still runs and is still the reproduction path for the earlier numbers;
what it lacked was SD-1 accounting (it averaged two samples) and a decode arm
(it measured prefill only, while the conclusion the board drew was about long
outputs).

Three arms, because the three claims on the board are three different claims:

  prefill    a large prompt, tiny forced output -> the prompt-rate column.
             English filler, not a repeated character: the older x-repeat
             method was compressed by the tokenizer, so its token counts were
             not what the prompt size column said.
  decode     streaming, forced full output budget -> per-stream decode rate.
  wall       the same request **not** streamed -> total wall time. This is the
             arm the "+156.4% -> +4.7%" fix was about; a streaming comparison
             cannot see a buffering relay, because the client is not waiting for
             the last byte in one read.

Both paths are alternated inside each round, so drift over the run lands on both.

Env
---
BIG_TOKENS     default 131072   *repeats* of " the" in the prefill arm -- not tokens.
                               This tokenizer emits ~2 tokens per repeat, so the engine
                               reports ~262,090 prompt tokens for the default. The name
                               is kept for compatibility with the archives; read the
                               reported `prompt_tokens`, never this variable.
DECODE_TOKENS  default 1024     forced output size for the decode and wall arms
ROUNDS         default 2        each round sends gw then direct
GATEWAY        default http://127.0.0.1:8001
DIRECT         default http://127.0.0.1:8899
OUT_DIR        default /state/gw-ab-<timestamp>

Output
------
<OUT_DIR>/gw_ab.json   stdout lines are the record; tee them
"""
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sd_protocol as sd  # noqa: E402

MODEL = os.environ.get("MODEL", "deepseek-v4.1-flash")
KEY = sd.read_key()
GW = os.environ.get("GATEWAY", "http://127.0.0.1:8001")
DIRECT = os.environ.get("DIRECT", "http://127.0.0.1:8899")
BIG_TOKENS = int(os.environ.get("BIG_TOKENS", "131072"))
DECODE_TOKENS = int(os.environ.get("DECODE_TOKENS", "1024"))
ROUNDS = int(os.environ.get("ROUNDS", "2"))
RUN_TAG = os.environ.get("RUN_TAG") or sd.new_run_tag()
OUT_DIR = sd.out_dir("gw-ab")

FILLER = " the"
HEADER = "Ignore the filler below and reply with OK when done."


def big_prompt(nonce):
    """Filler for the prefill arm. **BIG_TOKENS counts repeats, not tokens.**

    `" the" * N` tokenizes to about 2N tokens on this tokenizer, so BIG_TOKENS=131072
    yields a prompt the engine reports as ~262,090 tokens. That is why the variable is
    used only as a size knob and every published figure comes from the reported
    `prompt_tokens`: the label says "tokens", the quantity is repeats, and an earlier
    version of this docstring said "≈BIG_TOKENS tokens" -- publishing one quantity
    under another one's name, which is the defect this repository keeps recording.
    """
    body = " the " * max(1, BIG_TOKENS - 48)
    return "[gwab %s] %s\n%s\n\nReply OK." % (nonce, HEADER, body)


def do_request(url, prompt, max_tokens, stream, timeout=900):
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0, "top_p": 1, "stream": stream,
            "chat_template_kwargs": {"enable_thinking": False, "thinking": False,
                                     "thinking_mode": "disabled"}}
    if stream:
        body["stream_options"] = {"include_usage": True}
    if max_tokens:
        body["min_tokens"] = max_tokens
        body["ignore_eos"] = True
        body["stop"] = []
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + KEY})
    t0 = time.time()
    t_first = t_last = None
    ct = pt = None
    chars = 0
    err = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if not stream:
                payload = json.loads(resp.read())
                ct = (payload.get("usage") or {}).get("completion_tokens")
                pt = (payload.get("usage") or {}).get("prompt_tokens")
                t_first = t_last = time.time()
            else:
                for raw in resp:
                    line = raw.strip()
                    if not line.startswith(b"data:"):
                        continue
                    p = line[5:].strip()
                    if p == b"[DONE]":
                        break
                    try:
                        ev = json.loads(p)
                    except Exception:
                        continue
                    if ev.get("error"):
                        err = str(ev["error"])[:200]
                        break
                    d = (ev.get("choices") or [{}])[0].get("delta") or {}
                    piece = (d.get("content") or "") + (d.get("reasoning_content") or "")
                    if piece:
                        now = time.time()
                        if t_first is None:
                            t_first = now
                        t_last = now
                        chars += len(piece)
                    if ev.get("usage"):
                        ct = ev["usage"].get("completion_tokens")
                        pt = ev["usage"].get("prompt_tokens")
    except urllib.error.HTTPError as e:
        err = "HTTP %d %s" % (e.code, e.read()[:200].decode(errors="replace"))
    except Exception as e:
        err = repr(e)[:200]
    t_end = time.time()
    out = {"error": err, "stream": stream, "prompt_tokens": pt,
           "completion_tokens": ct, "wall_s": round(t_end - t0, 4)}
    if t_first:
        out["ttft_s"] = round(t_first - t0, 4)
        if pt:
            out["prefill_tps"] = round(pt / (t_first - t0), 1)
    if t_last and t_first and t_last > t_first and ct and ct > 1:
        out["decode_tps"] = round((ct - 1) / (t_last - t_first), 2)
    return out


def main():
    results = []
    for r in range(ROUNDS):
        for label, url in (("gw8001", GW), ("direct8899", DIRECT)):
            # prefill arm -- tiny forced output. One nonce per *path*, not per
            # round: with a shared prompt the second path is a pure cache hit, and
            # at BIG_TOKENS=131072 that is most of the difference being reported.
            rec = do_request(url, big_prompt(sd.new_nonce(RUN_TAG, "gwpre")), 16, True)
            rec.update({"arm": "prefill", "path": label, "round": r})
            results.append(rec)
            print(json.dumps(rec), flush=True)
            # decode arm -- streaming, forced full budget. Own nonce per path, same
            # reason as above.
            p = "[%s] %s%s" % (sd.new_nonce(RUN_TAG, "gwdec"),
                               sd.DECODE_PROSE_PROMPT, sd.FILL_TO_MAX_SUFFIX)
            rec = do_request(url, p, DECODE_TOKENS, True)
            rec.update({"arm": "decode", "path": label, "round": r})
            results.append(rec)
            print(json.dumps(rec), flush=True)
            # wall arm -- the same request, not streamed. It deliberately reuses `p`
            # from this path's own decode arm, because "same request" is the point
            # of the arm; both paths reach this line equally warm, so the
            # gw-vs-direct comparison stays symmetric.
            rec = do_request(url, p, DECODE_TOKENS, False)
            rec.update({"arm": "wall", "path": label, "round": r})
            results.append(rec)
            print(json.dumps(rec), flush=True)
    summary = {}
    for arm in ("prefill", "decode", "wall"):
        s = {}
        for label in ("gw8001", "direct8899"):
            key = "prefill_tps" if arm == "prefill" else (
                "decode_tps" if arm == "decode" else "wall_s")
            vals = [x[key] for x in results
                    if x["arm"] == arm and x["path"] == label
                    and not x.get("error") and x.get(key)]
            s[label] = {"n": len(vals), "median": round(statistics.median(vals), 3) if vals else None}
        if s["gw8001"]["median"] and s["direct8899"]["median"]:
            s["delta_pct"] = round((s["gw8001"]["median"] / s["direct8899"]["median"] - 1) * 100, 1)
        if arm == "wall":
            s["note"] = ("wall time: positive delta means the gateway makes it slower. "
                         "A buffering relay is only visible here -- a streaming client "
                         "is not waiting on a single read")
        else:
            s["note"] = "positive delta means the gateway is faster on this arm"
        summary[arm] = s
    sd.dump(os.path.join(OUT_DIR, "gw_ab.json"), {
        "_meta": {"protocol_id": sd.PROTOCOL_ID, "run_tag": RUN_TAG, "model": MODEL,
                  "gateway": GW, "direct": DIRECT, "big_tokens": BIG_TOKENS,
                  "decode_tokens": DECODE_TOKENS, "rounds": ROUNDS,
                  "finished": time.strftime("%Y-%m-%dT%H:%M:%S")},
        "summary": summary, "records": results})
    print(json.dumps({"summary": summary}), flush=True)
    print("OUT_DIR=" + OUT_DIR, flush=True)


if __name__ == "__main__":
    main()

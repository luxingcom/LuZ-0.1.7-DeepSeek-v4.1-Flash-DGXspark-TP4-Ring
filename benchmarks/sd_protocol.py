#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sd_protocol.py -- SD-1, the single measurement convention for this board.

Why this file exists
--------------------
The board used to carry three aggregation rules and three prefill numerators at
once (`benchmarks/README.md` sections 3 and 6). That made two tables
incomparable while both looked authoritative. The fix is not "make the old
harnesses agree" -- several of them are the only reproduction path for archives
that already shipped, so editing them would break that. The fix is to define the
convention **once, here**, and have every harness that produces a published
number import it. If a harness needs a different measurement, it must say so as
an explicit mode, not as a local variation.

SD-1
----
Measurement
  * channel        : `/v1/chat/completions`, streaming, `stream_options.include_usage`.
                     The PR matrix is the one documented exception -- see below.
  * output type    : a **prompt label**, never a constraint. sparkDash does not
                     use response_format, grammars or guided JSON at all; its
                     structured/prose/code/json are four prompts. Guided decoding
                     is measured, but only as its own arm (`GRAMMAR`), never mixed
                     into a type row.
  * force-fill     : `min_tokens = max_tokens`, `ignore_eos = true`, `stop = []`.
                     Without this, a model that finishes its thought early emits a
                     short stream, and a short stream's tail inflates its per-stream
                     rate. sparkDash force-fills and retries up to 400 times if the
                     server drops the parameters.
  * sampling       : `temperature = 0`, `top_p = 1`, thinking disabled through
                     `chat_template_kwargs`.
  * cache          : every request carries a **fresh nonce**, including C=1. A
                     reused prefix is served from the radix cache and its prefill
                     cost disappears, which silently inflates the prompt-rate
                     column. The nonce goes at the very front so no prompt text is
                     shared between any two requests, in this run or any other.
                     Each record carries `prompt_sha16`, so a reader can confirm
                     that no two streams shared a prompt without storing prompts.

Accounting (all per stream, from absolute timestamps)
  * ttft_s        = t_first_content - t0
  * decode_s      = t_last_content - t_first_content
  * decode_tps    = (completion_tokens - 1) / decode_s
  * prefill_tps   = usage.prompt_tokens / ttft_s          (queueing included)
  * Records keep `t0`, `t_first`, `t_last`, `t_end` as absolute epoch floats, so
    every aggregate below is recomputable by a third party from the raw JSON.
    The earlier harnesses kept only durations measured against a wave start that
    was never itself recorded, which made the common window non-re-derivable.

Aggregation (one rule, stated once)
  * cell central  = `statistics.median` over **every** ok stream of **every**
                    wave. Not a median of wave medians -- that is a different
                    measurement and it is what made wave count silently matter.
  * agg (primary) = sum(decode_tokens) / (max(t_last) - min(t_first))
                    -- the union window, sparkDash's basis.
  * agg_window    = tokens delivered inside [max(t_first), min(t_last)] over that
                    interval -- the true simultaneous-decoding window.
  * agg_wall      = sum(completion_tokens) / (max(t_end) - min(t0))
                    -- whole-wave wall, the basis the old code256 table used.
    All three are emitted. They answer different questions and quoting the wrong
    one is how this board previously published a number that had no source.
  * wave count is recorded in every emitted cell.

PR matrix exception
-------------------
The PR matrix varies input size from 512 to 524288 tokens, so the prompt must be
token-exact. That is only possible through the native `/generate` endpoint with
`input_ids`. It uses `min_new_tokens`/`ignore_eos` for the same force-fill
behaviour and the same accounting. Recorded as the one exception; everything
else, including its decode column, follows SD-1.

Provisioning
------------
KEY_FILE   engine API key, one line, optionally `API_KEY=<value>`
BASE       default http://127.0.0.1:8899
"""

import hashlib
import itertools
import json
import os
import statistics
import time
import urllib.error
import urllib.request
import uuid

PROTOCOL_ID = "SD-1"
PROTOCOL_DOC = (
    "SD-1: chat channel, prompt-label output types (no guided decoding), "
    "force-fill min_tokens=max_tokens + ignore_eos + stop=[], temp 0 / top_p 1 / "
    "thinking off, fresh nonce on every request incl. C=1, per-stream "
    "decode=(ct-1)/(tLast-tFirst), cell central value = statistics.median over all "
    "ok streams of all waves, aggregates over absolute timestamps "
    "(union / intersection / wall all emitted), wave count recorded"
)

# --------------------------------------------------------------------------
# Prompts -- verbatim from sparkDash src/shared/llmPrompts.js
# --------------------------------------------------------------------------

FILL_TO_MAX_SUFFIX = (" Continue generating until you hit the maximum output "
                      "length; do not stop early\u2014keep expanding with more content.")

DECODE_STRUCTURED_PROMPT = ("Count from 1 to 200. Output only the numbers, "
                            "separated by spaces. No other text.")
DECODE_PROSE_PROMPT = ("Write a detailed step-by-step explanation of how a hash map works, "
                       "including collision handling, resizing, and time complexity. Be thorough.")
DECODE_CODE_PROMPT = (
    "Output only Python source code. No comments, no docstrings, no markdown fences. "
    "Write functions clamp_00 through clamp_49. Each function is exactly:\n"
    "def clamp_NN(x, lo=0, hi=1):\n"
    "    if x < lo:\n"
    "        return lo\n"
    "    if x > hi:\n"
    "        return hi\n"
    "    return x\n"
    "Change only the function name suffix (00, 01, \u2026 49). One blank line between functions. "
    "No other text.")
DECODE_JSON_PROMPT = ("Emit only a JSON array of fake GPU metrics rows. Each object needs "
                      "host, gpuIndex, utilPct, tempC, powerW, memUsedMb. Invent many rows. "
                      "No markdown. Keep expanding the array.")

PROMPTS = {
    "structured": DECODE_STRUCTURED_PROMPT,
    "prose": DECODE_PROSE_PROMPT,
    "code": DECODE_CODE_PROMPT,
    "json": DECODE_JSON_PROMPT,
}

# The one schema used by the GRAMMAR arm. Deliberately carries an unreachable
# floor (`minItems`) so the constrained decoder cannot satisfy it and stop early;
# under a grammar, ignore_eos stops being absolute.
GRAMMAR_SCHEMAS = {
    "json": {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "host": {"type": "string"},
                        "gpuIndex": {"type": "integer"},
                        "utilPct": {"type": "number"},
                        "tempC": {"type": "number"},
                        "powerW": {"type": "number"},
                        "memUsedMb": {"type": "number"},
                    },
                    "required": ["host", "gpuIndex", "utilPct", "tempC", "powerW", "memUsedMb"],
                },
                "minItems": 400,
            }
        },
        "required": ["rows"],
    }
}


def new_run_tag():
    """Short, unique per run. Goes into every prompt and into the output paths."""
    return time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]


# --------------------------------------------------------------------------
# Nonces -- the whole "nothing here was served from the radix cache" argument
# --------------------------------------------------------------------------
# A nonce that encodes only `idx` is byte-identical across waves, and at C=1
# every wave is then an exact repeat of wave 0. Four leaks existed on this board
# before this counter did, and all four were mine:
#   * `warmup()` sent the same string as the C=1 wave-0 stream, so even the first
#     "cold" cell arrived pre-warmed;
#   * waves 1..n-1 repeated wave 0 byte for byte;
#   * grammar_ab's two arms shared one prompt, so whichever ran second always ran
#     on a prefix its own first arm had just filled -- the opposite of the
#     "neither arm can be flattered" the file advertised;
#   * gw_ab_v2 sent one 131,072-token prompt to the gateway and then the same
#     prompt to the direct endpoint, so the gateway column was the cold prefill
#     and the direct column was a cache hit. On a 131k prompt that is not a
#     rounding error, it is most of the difference being reported.
# So: the nonce is drawn from a process-wide counter and salted per process, and
# it is unique across warm-ups, waves, cells, arms and stages. The lesson is not
# "add a nonce"; it is that a *loop-invariant* string hoisted out of a wave or an
# arm loop is a cache leak by construction.
_PROC_SALT = uuid.uuid4().hex[:6]
_NONCE_SEQ = itertools.count(1)


def new_nonce(run_tag, label="sd1"):
    """A token that differs for every request this process will ever send.

    Call it once per request, at the moment that request is built. Never hoist a
    call out of a wave loop or an arm loop -- that is how all four leaks above
    happened.
    """
    return "%s:%s:%s:%05d" % (label, run_tag, _PROC_SALT, next(_NONCE_SEQ))


def build_prompt(ptype, count, idx, run_tag):
    """sparkDash prompt for `ptype`, prefixed with a per-request unique token.

    The nonce is at the very front. `count` and `idx` appear in the prefix for
    traceability only -- they are *not* what makes it unique. See the note above
    `new_nonce` for why that distinction is the whole ballgame.
    """
    base = PROMPTS[ptype] + FILL_TO_MAX_SUFFIX
    return "[%s c%d r%d] %s" % (new_nonce(run_tag), count, idx, base)


# --------------------------------------------------------------------------
# Request bodies
# --------------------------------------------------------------------------

def chat_body(model, prompt, max_tokens, force_fill=True):
    """Chat-channel body. Deliberately carries **no** grammar parameter.

    Guided decoding on this stack is only accepted as a JSON *string* on the
    native endpoint. The OpenAI-shaped alternative on the chat endpoint --
    `response_format: {"type": "json_schema", "json_schema": {"schema": {...}}}` --
    decodes into a Python dict server-side and hits the documented
    `TypeError: unhashable type: 'dict'`, which kills the scheduler and exits the
    container. Do not add it here. The grammar arm lives on the native channel,
    in `grammar_ab.py`, where the hazard is one layer away by construction.
    """
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "top_p": 1,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {
            "enable_thinking": False,
            "thinking": False,
            "thinking_mode": "disabled",
        },
    }
    if force_fill:
        body["min_tokens"] = max_tokens
        body["ignore_eos"] = True
        body["stop"] = []
    return body


def gen_body(input_ids, max_tokens, force_fill=True, grammar_json=None):
    """Native /generate body. `input_ids` is a token-exact prompt.

    `grammar_json` must be a JSON **string** (see the note in `chat_body`).
    """
    sp = {"temperature": 0, "max_new_tokens": max_tokens}
    if force_fill:
        sp["min_new_tokens"] = max_tokens
        sp["ignore_eos"] = True
    if grammar_json is not None:
        if not isinstance(grammar_json, str):
            raise TypeError("grammar_json must be a JSON string, not %s -- "
                            "a dict kills the scheduler" % type(grammar_json).__name__)
        sp["json_schema"] = grammar_json
    return {"input_ids": input_ids, "stream": True, "sampling_params": sp}


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------

def _blank(prompt_chars, index, wave, ptype=None, conc=None):
    return {"type": ptype, "conc": conc, "index": index, "wave": wave,
            "prompt_chars": prompt_chars, "error": None}


def _finish(rec, t0, t_first, t_last, t_end, ct, pt, chars):
    rec["t0"] = round(t0, 6)
    rec["t_first"] = None if t_first is None else round(t_first, 6)
    rec["t_last"] = None if t_last is None else round(t_last, 6)
    rec["t_end"] = round(t_end, 6)
    rec["prompt_tokens"] = pt or 0
    rec["completion_tokens"] = ct or 0
    rec["output_chars"] = chars
    if t_first is None or not ct:
        rec["error"] = rec.get("error") or "no content tokens"
        return rec
    rec["ttft_s"] = round(t_first - t0, 4)
    rec["wall_s"] = round(t_end - t0, 4)
    decode_s = (t_last - t_first) if (t_last and t_last > t_first) else 0.0
    rec["decode_s"] = round(decode_s, 4)
    if decode_s > 0 and ct > 1:
        rec["decode_tps"] = round((ct - 1) / decode_s, 2)
    if rec["ttft_s"] > 0 and pt:
        rec["prefill_tps"] = round(pt / rec["ttft_s"], 1)
    if ct:
        rec["chars_per_token"] = round(chars / ct, 3)
    return rec


def _open(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout)


def stream_chat(base, key, model, prompt, max_tokens, index=0, wave=0,
                ptype=None, conc=None, force_fill=True, timeout=3600):
    """One streaming chat request. Returns a single raw record."""
    rec = _blank(len(prompt), index, wave, ptype, conc)
    rec["prompt_sha16"] = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    body = chat_body(model, prompt, max_tokens, force_fill)
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    t0 = time.time()
    t_first = t_last = None
    chars = 0
    ct = pt = None
    try:
        with _open(req, timeout) as resp:
            for raw in resp:
                line = raw.strip()
                if not line.startswith(b"data:"):
                    continue
                payload = line[5:].strip()
                if payload == b"[DONE]":
                    break
                try:
                    ev = json.loads(payload)
                except Exception:
                    continue
                if ev.get("error"):
                    rec["error"] = str(ev["error"])[:200]
                    break
                ch = (ev.get("choices") or [{}])[0]
                d = ch.get("delta") or {}
                piece = (d.get("content") or "") + (d.get("reasoning_content") or "")
                if piece:
                    now = time.time()
                    if t_first is None:
                        t_first = now
                    t_last = now
                    chars += len(piece)
                u = ev.get("usage")
                if u:
                    ct = u.get("completion_tokens")
                    pt = u.get("prompt_tokens")
    except urllib.error.HTTPError as e:
        try:
            rec["error"] = "HTTP %d %s" % (e.code, e.read()[:200].decode(errors="replace"))
        except Exception:
            rec["error"] = "HTTP %d" % e.code
    except Exception as e:
        rec["error"] = repr(e)[:200]
    return _finish(rec, t0, t_first, t_last, time.time(), ct, pt, chars)


def stream_generate(base, key, input_ids, max_tokens, index=0, wave=0,
                    ptype=None, conc=None, force_fill=True, timeout=2400,
                    events=False, grammar_json=None):
    """One streaming native /generate request with a token-exact prompt."""
    rec = _blank(0, index, wave, ptype, conc)
    rec["input_tokens"] = len(input_ids)
    rec["prompt_sha16"] = hashlib.sha256(
        repr(list(input_ids)).encode()).hexdigest()[:16]
    body = gen_body(input_ids, max_tokens, force_fill, grammar_json)
    req = urllib.request.Request(
        base.rstrip("/") + "/generate", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    t0 = time.time()
    t_first = t_last = None
    ct = pt = 0
    ev_log = []
    try:
        with _open(req, timeout) as resp:
            for raw in resp:
                line = raw.strip()
                if not line.startswith(b"data:"):
                    continue
                payload = line[5:].strip()
                if payload == b"[DONE]":
                    break
                try:
                    ev = json.loads(payload)
                except Exception:
                    continue
                if ev.get("error"):
                    rec["error"] = str(ev["error"])[:200]
                    break
                mi = ev.get("meta_info") or {}
                c = mi.get("completion_tokens") or 0
                if c > 0:
                    now = time.time()
                    if t_first is None:
                        t_first = now
                    t_last = now
                    ct = c
                if mi.get("prompt_tokens"):
                    pt = mi["prompt_tokens"]
                if events:
                    ev_log.append([round(time.time() - t0, 5), c])
    except urllib.error.HTTPError as e:
        try:
            rec["error"] = "HTTP %d %s" % (e.code, e.read()[:200].decode(errors="replace"))
        except Exception:
            rec["error"] = "HTTP %d" % e.code
    except Exception as e:
        rec["error"] = repr(e)[:200]
    out = _finish(rec, t0, t_first, t_last, time.time(), ct, pt, 0)
    if events:
        # cumulative token counts with times, so a windowed rate can be rebuilt
        out["events_s_count"] = ev_log
    return out


# --------------------------------------------------------------------------
# Aggregation -- the one rule
# --------------------------------------------------------------------------

def _ok(recs):
    return [r for r in recs if not r.get("error") and r.get("decode_tps")]


def aggregate_wave(recs, conc):
    """Wave-level roll-up over absolute timestamps."""
    ok = _ok(recs)
    w = {"conc": conc, "streams_ok": len(ok), "streams_requested": conc,
         "streams_failed": conc - len(ok)}
    if not ok:
        w["error"] = next((r.get("error") for r in recs if r.get("error")), "no ok streams")
        return w
    dec_tokens = sum(r["completion_tokens"] - 1 for r in ok)
    t_first = [r["t_first"] for r in ok if r.get("t_first")]
    t_last = [r["t_last"] for r in ok if r.get("t_last")]
    t0s = [r["t0"] for r in ok]
    t_ends = [r["t_end"] for r in ok]
    union_s = max(t_last) - min(t_first)
    inter_s = min(t_last) - max(t_first)
    wall_s = max(t_ends) - min(t0s)
    w["union_window_s"] = round(union_s, 4)
    w["inter_window_s"] = round(inter_s, 4)
    w["wall_s"] = round(wall_s, 4)
    if union_s > 0:
        w["agg_decode_tps"] = round(dec_tokens / union_s, 1)
    if inter_s > 0:
        # tokens actually delivered while every stream in the wave was decoding.
        # Only computable where a per-token event log was retained (the native
        # path); omit the key rather than publish a zero that looks like a
        # measurement of nothing happening.
        inside = 0
        usable = True
        for r in ok:
            ev = r.get("events_s_count")
            if not ev:
                usable = False
                break
            lo, hi = max(t_first), min(t_last)
            c_lo = max((c for s, c in ev if r["t0"] + s <= lo), default=0)
            c_hi = max((c for s, c in ev if r["t0"] + s <= hi), default=0)
            inside += max(0, c_hi - c_lo)
        if usable and inside > 0:
            w["agg_decode_tps_window"] = round(inside / inter_s, 1)
    if wall_s > 0:
        w["agg_decode_tps_wall"] = round(sum(r["completion_tokens"] for r in ok) / wall_s, 1)
    total_pt = sum(r["prompt_tokens"] for r in ok)
    if wall_s > 0 and (t_first and max(t_first) > min(t0s)):
        w["agg_prefill_tps"] = round(total_pt / (max(t_first) - min(t0s)), 1)
    w["median_decode_tps"] = round(statistics.median(r["decode_tps"] for r in ok), 2)
    w["median_prefill_tps"] = round(statistics.median(
        r["prefill_tps"] for r in ok if r.get("prefill_tps")), 1) if any(
        r.get("prefill_tps") for r in ok) else None
    w["median_ttft_s"] = round(statistics.median(r["ttft_s"] for r in ok), 4)
    w["median_completion_tokens"] = statistics.median(r["completion_tokens"] for r in ok)
    return w


def cell_summary(waves, raw_all, ptype=None, conc=None, max_tokens=None,
                 run_tag=None, grammar=None):
    """One cell. Central value = median over all ok streams of all waves."""
    ok_waves = [w for w in waves if w.get("streams_ok")]
    all_ok = [r for recs in raw_all for r in recs if not r.get("error") and r.get("decode_tps")]
    cell = {
        "type": ptype,
        "conc": conc,
        "grammar": grammar,
        "max_tokens": max_tokens,
        "run_tag": run_tag,
        "waves": len(waves),
        "ok_waves": len(ok_waves),
        "streams_ok": len(all_ok),
        "waves_detail": ok_waves,
    }
    if all_ok:
        cell["median_decode_tps"] = round(statistics.median(r["decode_tps"] for r in all_ok), 2)
        cell["mean_decode_tps"] = round(statistics.mean(r["decode_tps"] for r in all_ok), 2)
        cell["median_ttft_s"] = round(statistics.median(r["ttft_s"] for r in all_ok), 4)
        cell["median_completion_tokens"] = statistics.median(
            r["completion_tokens"] for r in all_ok)
        pf = [r["prefill_tps"] for r in all_ok if r.get("prefill_tps")]
        if pf:
            cell["median_prefill_tps"] = round(statistics.median(pf), 1)
        cpt = [r["chars_per_token"] for r in all_ok if r.get("chars_per_token")]
        if cpt:
            cell["median_chars_per_token"] = round(statistics.median(cpt), 3)
        if ok_waves:
            cell["agg_decode_tps"] = round(statistics.median(
                [w["agg_decode_tps"] for w in ok_waves if w.get("agg_decode_tps") is not None]), 1)
            cell["agg_decode_tps_best_wave"] = max(
                (w["agg_decode_tps"] for w in ok_waves if w.get("agg_decode_tps") is not None),
                default=None)
            ap = [w["agg_prefill_tps"] for w in ok_waves if w.get("agg_prefill_tps")]
            if ap:
                cell["agg_prefill_tps"] = round(statistics.median(ap), 1)
    cell["convention"] = PROTOCOL_DOC
    return cell


def percentile(values, p):
    """Nearest-rank percentile; used for the tail evidence, not for central values."""
    if not values:
        return None
    xs = sorted(values)
    k = max(0, min(len(xs) - 1, int(round((p / 100.0) * (len(xs) - 1)))))
    return xs[k]


def read_key(path=None):
    raw = open(path or os.environ.get("KEY_FILE", "/state/api-key")).read().strip()
    return raw.split("=", 1)[1] if raw.startswith("API_KEY=") else raw


def out_dir(prefix):
    d = os.environ.get("OUT_DIR") or ("/state/" + prefix + "-" + time.strftime("%Y%m%dT%H%M%S"))
    os.makedirs(d, exist_ok=True)
    return d


def dump(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1)

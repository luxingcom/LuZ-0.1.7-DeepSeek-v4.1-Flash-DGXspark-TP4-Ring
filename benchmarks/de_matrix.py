#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""de_matrix.py -- DE (decode-engine) text-throughput matrix, free-form.

This is the harness behind `data/de-freeform-20260917/` (15 cells: 3 task shapes
x 5 concurrencies) and therefore behind the DE half of section 3 of
`docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md`.

Method
------
- 3 task shapes: coding / json / prose
- input ~512 tokens (uuid nonce + filler + task instruction -> cold prefix per
  request), output budget 4096, `ignore_eos=True`, temperature 0
- decode rate  = (completion_tokens - 1) / (wall - ttft)   [per stream]
- prefill rate = 512.0 / ttft                              [per stream]
- cell summary = the per-stream statistic below, aggregate = that x N
- endpoint: SGLang native /generate on 127.0.0.1:8899, streaming

Reproducibility note (do not "fix" this silently)
-------------------------------------------------
This harness reports the **upper** median, `sorted(x)[n // 2]`, and hardcodes
512.0 for the prefill numerator. The structured-output harness
(`de_matrix_structured.py`) instead uses `statistics.median` (mean of the two
middles for even n) and reads the real `prompt_tokens` out of `meta_info`.
For C=1 the two agree; for even C they do not. Both are kept exactly as they
were when the published archives were produced -- changing either one would
make this file's output irreproducible from the file itself. The divergence is
recorded in `benchmarks/README.md` §3.

Env
---
CONCURRENCIES  default "1,2,4,8,16"
OUT_DIR        default /state/de-<timestamp>
KEY_FILE       default /state/api-key   (engine API key, one line of text)

Output
------
<OUT_DIR>/de_matrix.json plus <OUT_DIR>/de_<task>_c<N>.json per cell.
"""
import concurrent.futures
import json
import os
import re  # noqa: F401  (kept: imported by the original, harmless)
import time
import urllib.request
import uuid

BASE = "http://127.0.0.1:8899"
KEY = open(os.environ.get("KEY_FILE", "/state/api-key")).read().strip()
CONCS = [int(x) for x in os.environ.get("CONCURRENCIES", "1,2,4,8,16").split(",")]
OUT_DIR = os.environ.get("OUT_DIR") or ("/state/de-" + time.strftime("%Y%m%dT%H%M%S"))
os.makedirs(OUT_DIR, exist_ok=True)

# 512-token input: uuid nonce + short filler + task instruction (cold prefix per request)
FILLER = ("Reference notes: the cache stores recently accessed entries. An implementation "
          "should maintain ordering, handle replacement and validate its invariants.\n")

TASK_TEMPLATES = {
    "coding": (
        "\u8bf7\u7528 Python \u5b9e\u73b0\u4e00\u4e2a\u5927\u578b\u5de5\u5177\u5e93 process_lib\uff0c"
        "\u5305\u542b\u4ee5\u4e0b\u6a21\u5757\u5e76\u7ed9\u51fa\u5b8c\u6574\u53ef\u8fd0\u884c\u4ee3\u7801\u3001"
        "docstring \u4e0e pytest \u6d4b\u8bd5\uff1a\n"
        "1) process_records(records: list[dict]) -> dict\uff1a\u6309 category \u5206\u7ec4\u7edf\u8ba1 "
        "avg_score/count\uff0c\u6309 count \u964d\u5e8f\u8fd4\u56de\uff1b\n"
        "2) DataPipeline \u7c7b\uff1a\u652f\u6301 read/transform/aggregate/write \u56db\u9636\u6bb5\uff0c"
        "\u542b\u91cd\u8bd5\u4e0e\u65e5\u5fd7\uff1b\n"
        "3) cli \u5165\u53e3\uff1aargparse \u89e3\u6790 --input/--output/--verbose/--workers\u3002\n"
        "\u4ee3\u7801\u8981\u5c3d\u91cf\u957f\u800c\u5b8c\u6574\uff0c\u8986\u76d6\u7c7b\u578b\u6ce8\u89e3\u3001"
        "\u8fb9\u754c\u5904\u7406\u3001\u5f02\u5e38\u5904\u7406\u4e0e\u6ce8\u91ca\u3002\u53ea\u8f93\u51fa\u4ee3\u7801\uff0c"
        "\u4e0d\u8981\u89e3\u91ca\u3002"
    ),
    "json": (
        "\u8bf7\u751f\u6210\u4e00\u4e2a\u5927\u578b JSON \u5bf9\u8c61\uff08\u53ea\u8f93\u51fa JSON\uff0c"
        "\u4e0d\u8981\u4efb\u4f55\u5176\u4ed6\u6587\u672c\uff09\uff1a\u63cf\u8ff0\u4e00\u4e2a\u5305\u542b 200 "
        "\u540d\u5458\u5de5\u7684\u7ec4\u7ec7\u3002\n"
        "\u6bcf\u4e2a\u5458\u5de5\u542b id / name / role / department / skills(\u6570\u7ec4\uff0c5-10 \u9879) / "
        "projects(\u6570\u7ec4\uff0c\u6bcf\u9879\u542b name/status/deadline/milestones\u6570\u7ec4) / "
        "metrics(\u542b efficiency/quality/velocity \u4e09\u4e2a 0-100 \u6570\u503c) / tags(\u6570\u7ec4) / "
        "active(bool)\u3002\n"
        "status \u5fc5\u987b\u53d6 planned|in_progress|done \u4e4b\u4e00\uff1bdeadline \u4e3a ISO "
        "\u65e5\u671f\u5b57\u7b26\u4e32\uff1bid \u7528 E001-E200\u3002\n"
        "\u5b57\u6bb5\u5c3d\u53ef\u80fd\u591a\u3001\u5185\u5bb9\u5c3d\u53ef\u80fd\u4e30\u5bcc\uff0c"
        "\u76f4\u63a5\u8f93\u51fa\u5b8c\u6574 JSON\u3002"
    ),
    "prose": (
        "\u8bf7\u4ee5\u6563\u6587\u98ce\u683c\u7eed\u5199\u4e0b\u9762\u8fd9\u6bb5\u6587\u5b57\uff0c"
        "\u5199\u6210\u4e00\u7bc7\u957f\u6563\u6587\uff0c\u5185\u5bb9\u8981\u975e\u5e38\u957f\u3001"
        "\u7ec6\u8282\u4e30\u5bcc\u3001\u6709\u753b\u9762\u611f\uff1a\n"
        "\u591c\u8272\u6e10\u6df1\uff0c\u5c0f\u9547\u7684\u706f\u706b\u6b21\u7b2c\u4eae\u8d77\u3002"
        "\u5df7\u53e3\u7684\u68a7\u6850\u6811\u4e0b\uff0c\u98ce\u628a\u6700\u540e\u4e00\u7247\u843d\u53f6"
        "\u9001\u8fdb\u4e86\u90ae\u7b52\u2026\u2026\n"
        "\u8bf7\u6301\u7eed\u5c55\u5f00\u53d9\u8ff0\uff1a\u4eba\u7269\u7684\u8eab\u4e16\u3001"
        "\u5df7\u5f04\u7684\u666f\u81f4\u3001\u5f80\u4e8b\u4e0e\u6b64\u523b\u7684\u4ea4\u7ec7\u3001"
        "\u56db\u5b63\u7684\u6d41\u8f6c\uff0c\u9010\u6b65\u63a8\u8fdb\u5230\u7ed3\u5c3e\uff0c"
        "\u5199\u5230 8000 \u5b57\u4ee5\u4e0a\u3002\u8bed\u8a00\u4f18\u7f8e\u3001\u81ea\u7136\uff0c"
        "\u4e0d\u8981\u603b\u7ed3\u3001\u4e0d\u8981\u89e3\u91ca\u3001\u4e0d\u8981\u8bc4\u8bba\u5199\u4f5c\u672c\u8eab\u3002"
    ),
}


def build_text(task):
    nonce = uuid.uuid4().hex
    prefix = nonce + "\nRead these notes.\n" + FILLER
    return prefix + TASK_TEMPLATES[task]


def one(task, idx, wave_start):
    text = build_text(task)
    body = json.dumps({
        "text": text, "stream": True,
        "sampling_params": {"temperature": 0, "max_new_tokens": 4096, "ignore_eos": True},
    }).encode()
    req = urllib.request.Request(BASE + "/generate", data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    t0 = time.time()
    ttft = None
    out = {"task": task, "index": idx, "started_s": time.monotonic() - wave_start}
    try:
        with urllib.request.urlopen(req, timeout=3600) as resp:
            for line in resp:
                line = line.decode().strip()
                if not line.startswith("data:"):
                    continue
                p = line[5:].strip()
                if p == "[DONE]":
                    break
                ev = json.loads(p)
                meta = ev.get("meta_info", {}) or {}
                ct = (meta.get("completion_tokens") or 0)
                if ttft is None and ct > 0:
                    ttft = time.time() - t0
                out["completion_tokens"] = ct
        out["ttft"] = ttft
        out["wall"] = time.time() - t0
        ct = out.get("completion_tokens", 0)
        if ttft and ct > 1:
            out["decode_tps"] = (ct - 1) / (out["wall"] - ttft)
            out["prefill_tps"] = 512.0 / ttft
    except Exception as e:
        out["error"] = repr(e)
    return out


results = {}
for task in ["coding", "json", "prose"]:
    for c in CONCS:
        wave_start = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=c) as ex:
            recs = list(ex.map(lambda i: one(task, i, wave_start), range(c)))
        ok = [r for r in recs if not r.get("error") and r.get("decode_tps")]
        n = len(ok)
        # upper median -- see the reproducibility note in the module docstring
        med = lambda k: sorted(r[k] for r in ok)[n // 2] if n else None
        summary = {
            "task": task, "conc": c, "ok": n, "requested": c,
            "prefill_tps": med("prefill_tps"),
            "decode_tps": med("decode_tps"),
            "ttft_s": med("ttft"),
            "median_ct": sorted(r["completion_tokens"] for r in ok)[n // 2] if n else None,
            "aggregate_decode_tps": (med("decode_tps") * c) if n else None,
        }
        results[f"DE_{task}_C{c}"] = summary
        print(json.dumps(summary), flush=True)
        with open(os.path.join(OUT_DIR, f"de_{task}_c{c}.json"), "w") as f:
            json.dump(recs, f, indent=1)

with open(os.path.join(OUT_DIR, "de_matrix.json"), "w") as f:
    json.dump(results, f, indent=1)
print("OUT_DIR=" + OUT_DIR, flush=True)

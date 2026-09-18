#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""de_matrix_structured.py -- DE matrix with STRUCTURED (schema-constrained) output.

This harness is what measured **guided-decoding cost** (coding/json x 5
concurrencies, 3 waves per cell) against the free-form harness above. It is the answer to
a different question from "which output shape is fastest" -- `grammar_ab.py` re-measures
that A/B under SD-1 and publishes it in FINAL-METRICS §5.1. Retained as-is, with its
archive generation removed from `data/`.

Method
------
- channel: SGLang native /generate, streaming, `sampling_params.json_schema`
- input ~512 tokens (uuid nonce + filler + instruction -> cold prefix per request),
  output budget 4096, `ignore_eos=True`, temperature 0
- WAVES waves per cell; the reported cell value is the median of the per-wave
  medians (steady state), not a single wave
- decode rate  = (completion_tokens - 1) / (wall - ttft)   [per stream]
- prefill rate = prompt_tokens / ttft                      [per stream]
- aggregate    = per-stream median x N

Two traps this harness exists to keep visible
---------------------------------------------
1. `json_schema` MUST be passed as a JSON **string**. Passing a dict kills the
   engine (xgrammar `TypeError: unhashable type: 'dict'` -> scheduler dies ->
   container exit 247). Reproduced 2026-09-17 16:27.
2. Under grammar constraints `ignore_eos=True` stops being absolute: if the
   schema can terminate early, EOS still fires. Hence the `minItems` floors
   below -- they exist to keep the token budget reachable, not for decoration.

Reproducibility note (do not "fix" this silently)
-------------------------------------------------
Unlike `de_matrix.py` (free-form), this harness uses `statistics.median` and
reads the real `prompt_tokens` from `meta_info`. The two therefore disagree for
even concurrency levels. Both are kept as they were when the archives were
produced; see `benchmarks/README.md`.

Env
---
CONCURRENCIES  default "1,2,4,8,16"
WAVES          default 3
OUT_DIR        default /state/de-struct-<timestamp>
KEY_FILE       default /dev/shm/apikey   (engine API key, one line of text)

Output
------
<OUT_DIR>/de_structured_matrix.json plus <OUT_DIR>/de_<task>_c<N>.json per cell.
"""
import concurrent.futures
import json
import os
import statistics
import time
import urllib.request
import uuid

BASE = "http://127.0.0.1:8899"
KEY = open(os.environ.get("KEY_FILE", "/dev/shm/apikey")).read().strip()
CONCS = [int(x) for x in os.environ.get("CONCURRENCIES", "1,2,4,8,16").split(",")]
WAVES = int(os.environ.get("WAVES", "3"))
OUT_DIR = os.environ.get("OUT_DIR") or ("/state/de-struct-" + time.strftime("%Y%m%dT%H%M%S"))
os.makedirs(OUT_DIR, exist_ok=True)

FILLER = ("Reference notes: the cache stores recently accessed entries. An implementation "
          "should maintain ordering, handle replacement and validate its invariants.\n")

CODE_SCHEMA = {
    "type": "object",
    "properties": {
        "language": {"type": "string", "enum": ["python"]},
        "module": {"type": "string"},
        "code": {"type": "string"},
        "tests": {"type": "string"},
        "functions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "docstring": {"type": "string"},
                    "raises": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "docstring"],
            },
            "minItems": 120,
        },
        "design_notes": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 300,
        },
    },
    "required": ["language", "module", "code", "tests", "functions", "design_notes"],
}

ORG_SCHEMA = {
    "type": "object",
    "properties": {
        "employees": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "department": {"type": "string"},
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "projects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "status": {"type": "string", "enum": ["planned", "in_progress", "done"]},
                                "deadline": {"type": "string"},
                                "milestones": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["name", "status", "deadline", "milestones"],
                        },
                    },
                    "metrics": {
                        "type": "object",
                        "properties": {
                            "efficiency": {"type": "integer"},
                            "quality": {"type": "integer"},
                            "velocity": {"type": "integer"},
                        },
                        "required": ["efficiency", "quality", "velocity"],
                    },
                    "active": {"type": "boolean"},
                    "bio": {"type": "string"},
                    "notes": {"type": "string"},
                    "activity_log": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 40,
                    },
                },
                "required": ["id", "name", "role", "department", "skills", "projects",
                             "metrics", "active", "bio", "notes", "activity_log"],
            },
        },
    },
    "required": ["employees"],
}

PROMPTS = {
    "coding": (
        "请用 Python 实现一个大型工具库 process_lib，包含分组统计、数据管道（read/transform/"
        "aggregate/write 四阶段，含重试与日志）与 CLI 入口。把完整实现写入 code 字段，pytest "
        "测试写入 tests 字段，每个函数的签名与 docstring 摘要列入 functions 数组。code 与 tests "
        "都必须内容详实完整（含类型注解、边界处理、异常处理、注释），长度必须尽可能长，直到 "
        "4096 token 上限为止都要持续生成。只输出符合 schema 的 JSON。"
    ),
    "json": (
        "生成一个组织对象：employees 数组至少 50 名员工（尽量多填直到上限），每个员工含 "
        "id/name/role/department/skills(5-10项)/projects(含 name/status/deadline/milestones)/"
        "metrics(efficiency/quality/velocity 0-100)/active/bio(100字以上生平)/notes(200字笔记)/"
        "activity_log(至少40条每日工作记录，每条30字以上)。status 只能取 planned|in_progress|done。"
        "直接输出符合 schema 的 JSON，内容要持续生成到 4096 token 上限。"
    ),
}

SCHEMAS = {"coding": CODE_SCHEMA, "json": ORG_SCHEMA}


def build_text(task):
    nonce = uuid.uuid4().hex
    prefix = nonce + "\nRead these notes.\n" + FILLER
    return prefix + PROMPTS[task]


def one(task, idx, wave_start):
    body = json.dumps({
        "text": build_text(task),
        "stream": True,
        "sampling_params": {
            "temperature": 0,
            "max_new_tokens": 4096,
            "ignore_eos": True,
            # STRING, never a dict -- see trap 1 in the module docstring
            "json_schema": json.dumps(SCHEMAS[task]),
        },
    }).encode()
    req = urllib.request.Request(BASE + "/generate", data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    t0 = time.time()
    ttft = None
    ct = 0
    pt = 0
    out = {"task": task, "index": idx}
    try:
        with urllib.request.urlopen(req, timeout=3600) as resp:
            buf = b""
            while True:
                chunk = resp.read(1)
                if not chunk:
                    break
                buf += chunk
                if not buf.endswith(b"\n\n"):
                    continue
                for line in buf.decode().split("\n"):
                    if not line.startswith("data:"):
                        continue
                    p = line[5:].strip()
                    if p == "[DONE]":
                        continue
                    ev = json.loads(p)
                    mi = ev.get("meta_info") or {}
                    c = mi.get("completion_tokens") or 0
                    if ttft is None and c > 0:
                        ttft = time.time() - t0
                    ct = c
                    if mi.get("prompt_tokens"):
                        pt = mi["prompt_tokens"]
                buf = b""
        out["ttft"] = ttft
        out["wall"] = time.time() - t0
        out["completion_tokens"] = ct
        out["prompt_tokens"] = pt
        if ttft and ct > 1:
            out["decode_tps"] = (ct - 1) / (out["wall"] - ttft)
            out["prefill_tps"] = (pt or 512.0) / ttft
    except Exception as e:
        out["error"] = repr(e)
    return out


results = {}
for task in ["coding", "json"]:
    for c in CONCS:
        all_waves = []
        for w in range(WAVES):
            wave_start = time.monotonic()
            with concurrent.futures.ThreadPoolExecutor(max_workers=c) as ex:
                recs = list(ex.map(lambda i: one(task, i, wave_start), range(c)))
            all_waves.append(recs)
        wave_decode, wave_prefill, wave_ct = [], [], []
        for recs in all_waves:
            ok = [r for r in recs if not r.get("error") and r.get("decode_tps")]
            if not ok:
                continue
            wave_decode.append(statistics.median(r["decode_tps"] for r in ok))
            wave_ct.append(statistics.median(r["completion_tokens"] for r in ok))
            wave_prefill.append(statistics.median(r["prefill_tps"] for r in ok))
        md = statistics.median(wave_decode) if wave_decode else None
        mp = statistics.median(wave_prefill) if wave_prefill else None
        mct = statistics.median(wave_ct) if wave_ct else None
        summary = {
            "task": task, "conc": c, "waves": WAVES, "ok_waves": len(wave_decode),
            "prefill_tps": mp, "decode_tps": md, "median_ct": mct,
            "aggregate_decode_tps": (md * c) if md else None,
        }
        results[f"DE-S_{task}_C{c}"] = summary
        print(json.dumps(summary), flush=True)
        with open(os.path.join(OUT_DIR, f"de_{task}_c{c}.json"), "w") as f:
            json.dump(all_waves, f, indent=1)

with open(os.path.join(OUT_DIR, "de_structured_matrix.json"), "w") as f:
    json.dump(results, f, indent=1)
print("OUT_DIR=" + OUT_DIR, flush=True)

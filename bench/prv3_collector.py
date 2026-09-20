#!/usr/bin/env python3
"""PR-v3 纯 prefill 总吞吐矩阵采集器（重建版，口径=prv3-v14-final/TABLE.md）

- 纯 prefill: max_tokens=1, stream=True（/v1/chat/completions）
- 每请求 fresh nonce；每 cell 前 POST /flush_cache
- total t/s = Σ(prompt tokens) / [arm start → last stream end]
- 逐流记录 t0/t_first/t_end/ttft/prompt_sha16 —— 与 v14 final 数据模式同构
运行（容器内）: python3 /state/prv3_collector.py   [输出 /state/bench-results/prv3-v18-<ts>/]
"""
import concurrent.futures, hashlib, json, os, statistics, sys, time, urllib.request, uuid
from pathlib import Path
from tokenizers import Tokenizer

BASE = os.environ.get("PRV3_BASE", "http://127.0.0.1:8899")
MODEL = Path(os.environ.get("MODEL_PATH", "/models/DeepSeek-V4.1-Flash"))
OUTROOT = Path(os.environ.get("STATE_PATH", "/state")) / "bench-results"
SIZES = [int(x) for x in os.environ.get("PREFILL_SIZES", "512,2048,4096,8192,16384,32768,65536,131072").split(",")]
CONCS = [int(x) for x in os.environ.get("CONCURRENCIES", "1,2,4,8,16").split(",")]
KEY = (Path(os.environ.get("STATE_PATH", "/state")) / "api-key").read_text().strip()

tok = Tokenizer.from_file(str(MODEL / "tokenizer.json"))
FILL = ("Reference notes: the cache stores recently accessed entries. An implementation "
        "should maintain ordering, handle replacement and validate its invariants.\n")
fill_ids = tok.encode(FILL, add_special_tokens=False).ids
INSTR = "\nNow write a complete Python LRU cache module. Return code only.\n"
instr_ids = tok.encode(INSTR, add_special_tokens=False).ids

folder = OUTROOT / ("prv3-v18-" + time.strftime("%Y%m%dT%H%M%S"))
folder.mkdir(parents=True)
identity = hashlib.sha256((Path(os.environ.get("STATE_PATH", "/state")) / "launch.json").read_bytes()).hexdigest()


def flush_cache():
    try:
        req = urllib.request.Request(BASE + "/flush_cache", data=b"", method="POST",
                                     headers={"Authorization": "Bearer " + KEY})
        urllib.request.urlopen(req, timeout=60).read()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] flush_cache: {e}", flush=True)


def one(size, index, arm_start):
    nonce = uuid.uuid4().hex
    text = nonce + "\nRead these notes.\n" + FILL * ((size) // max(len(FILL) // 4, 1) + 8) + INSTR
    ids = tok.encode(text, add_special_tokens=False).ids
    ids = ids[:size - len(instr_ids)] + instr_ids
    body = {"model": "deepseek-v4.1-flash", "temperature": 0, "max_tokens": 1, "stream": True,
            "chat_template_kwargs": {"thinking": False},
            "messages": [{"role": "user", "content": tok.decode(ids)}]}
    rec = dict(type="pr", index=index, conc=None, input_tokens=size, nonce=nonce,
               manifest_sha256=identity, error=None, events=[],
               t0=time.monotonic() - arm_start)
    try:
        req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + KEY})
        with urllib.request.urlopen(req, timeout=2400) as r:
            first = None
            usage = {}
            for line in r:
                line = line.decode("utf-8", "replace").strip()
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                obj = json.loads(payload)
                if obj.get("usage"):
                    usage = obj["usage"]
                ch = obj.get("choices") or [{}]
                delta = (ch[0].get("delta") or {}).get("content")
                if delta and first is None:
                    first = time.monotonic() - arm_start
            t_end = time.monotonic() - arm_start
            rec.update(prompt_tokens=usage.get("prompt_tokens", size),
                       completion_tokens=usage.get("completion_tokens", 1),
                       ttft_s=first, t_first=first, t_end=t_end, t_last=t_end,
                       prompt_sha16=hashlib.sha256(tok.decode(ids).encode()).hexdigest()[:16],
                       prompt_chars=len(tok.decode(ids)), output_chars=1,
                       chars_per_token=None)
    except Exception as e:  # noqa: BLE001
        rec["error"] = repr(e)
    return rec


def render():
    rows = []
    for f in sorted(folder.glob("*-c*-w0.json")):
        recs = json.loads(f.read_text())
        good = [r for r in recs if not r.get("error")]
        if not good:
            rows.append((f.stem, 0, len(recs), None, None, None, None, 0))
            continue
        wall = max(r["t_end"] for r in good) - min(r["t0"] for r in good)
        total = sum(r["prompt_tokens"] for r in good)
        spans = sorted([(r["t_first"], 1) for r in good] + [(r["t_end"], -1) for r in good])
        active = peak = 0
        for _, d in spans:
            active += d
            peak = max(peak, active)
        serialized = "serialized=⚠" if peak <= 1 else "ok"
        rows.append((f.stem, len(good), len(recs), total, wall, total / wall if wall else None,
                     statistics.median(r["ttft_s"] for r in good), peak, serialized))
    lines = ["# PR-v3 — pure-prefill total-throughput matrix (v18/0.2.4)", "",
             "One request = `max_tokens=1` (pure prefill; no decode tail). Fresh nonce per "
             "request; `/flush_cache` between cells. **total t/s = Σ(prompt tokens) / "
             "wall-clock from arm start to last stream end**.", "",
             "| Cell | OK/Streams | Σ prompt tok | Wall s | **Total t/s** | median TTFT s | overlap peak | serialized |",
             "|---|---:|---:|---:|---:|---:|---:|---|"]
    for row in rows:
        name, ok, n, total, wall, tps, ttft, peak = row[:8]
        ser = row[8] if len(row) > 8 else ""
        fmt = lambda v, d=2: ("{:." + str(d) + "f}").format(v) if isinstance(v, (int, float)) else "—"
        lines.append(f"| {name} | {ok}/{n} | {total or '—'} | {fmt(wall)} | **{fmt(tps)}** | {fmt(ttft)} | {peak} | {ser} |")
    (folder / "TABLE.md").write_text("\n".join(lines) + "\n")


print(str(folder), flush=True)
for size in SIZES:
    for conc in CONCS:
        flush_cache()
        time.sleep(2)
        start = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as pool:
            recs = list(pool.map(lambda i: one(size, i, start), range(conc)))
        for r in recs:
            r["conc"] = conc
        (folder / f"{size}-c{conc}-w0.json").write_text(json.dumps(recs))
        good = [r for r in recs if not r.get("error")]
        wall = time.monotonic() - start
        tps = sum(r.get("prompt_tokens", size) for r in good) / wall if good else 0
        print(f"{size}-c{conc}: {len(good)}/{conc} ok  wall={wall:.1f}s  tps={tps:.0f}", flush=True)
        render()
        if len(good) != conc:
            print(f"[abort] cell {size}-c{conc} failed", flush=True)
            sys.exit(1)
(folder / "COMPLETE").write_text(time.strftime("%Y-%m-%dT%H:%M:%S"))
render()
print("DONE", flush=True)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
F 新基线 GSM8K 200 题 (idx0-199, 8-shot CoT) — Tessa / testing-expert
====================================================================
历史口径 (v026r): 网关8003, temp=0, max_tokens=1024, 顺序
新基线口径: 网关8003, temp=0.6 (probabilistic draft 生效前提), max_tokens=1024, 顺序
判分: extract_content (boxed{}->last_num(content)) + extract_marker 双口径
输出: raw jsonl + summary json + stdout summary
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8003"  # 网关 (worker <MGMT_OCTET>), 可通过 --base 覆盖
MODEL = "deepseek-v4.1-flash"
API_KEY = "YOUR_API_KEY"
DATA = os.environ.get("GSM8K_DATA", os.path.expanduser("~/data/gsm8k_test.jsonl"))  # 环境变量可覆盖；~ 经 expanduser 展开
OUT_RAW = "/home/spark/dsv41-4x-spark/bench-results/gsm8k-dsv41.raw.jsonl"
OUT_SUMMARY = "/home/spark/dsv41-4x-spark/bench-results/gsm8k-dsv41.summary.json"
MAX_TOKENS = 1024
NQ = 200
TEMPERATURE = 0.6
CONC = 1  # 顺序 (与历史口径一致)

EXAMPLES = [
    ("There are 15 trees in the grove. Grove workers will plant trees in the grove today. "
     "After they are done, there will be 21 trees. How many trees did the grove workers plant today?",
     "There are 15 trees originally. Then there were 21 trees after some more were planted. "
     "So there must have been 21 - 15 = 6 trees planted. The answer is 6."),
    ("If there are 3 cars in the parking lot and 2 more cars arrive, how many cars are in the parking lot?",
     "There are originally 3 cars. 2 more cars arrive. 3 + 2 = 5. The answer is 5."),
    ("Leah has 32 chocolates and her sister has 42. If they eat 35, how many pieces do they have left in total?",
     "Originally, Leah had 32 chocolates and her sister had 42. So in total they had 32 + 42 = 74. "
     "After eating 35, they had 74 - 35 = 39 pieces left. The answer is 39."),
    ("Jason had 20 lollipops. He gave Denny some lollipops. Now Jason has 12 lollipops. "
     "How many lollipops did Jason give to Denny?",
     "Jason started with 20 lollipops. Then he had 12 after giving some away. "
     "So he gave 20 - 12 = 8 lollipops to Denny. The answer is 8."),
    ("Shawn has five toys. For Christmas, he got two toys each from his mom and dad. How many toys does he have now?",
     "Shawn started with 5 toys. If he got 2 toys each from his mom and dad, that is 4 more toys. "
     "5 + 4 = 9. The answer is 9."),
    ("There were nine computers in the server room. Five more computers were installed each day, "
     "from monday to thursday. How many computers are now in the server room?",
     "There were originally 9 computers. For each of 4 days, 5 more computers were added. "
     "So 4 * 5 = 20 computers were added. 9 + 20 = 29. The answer is 29."),
    ("Michael had 58 golf balls. On tuesday, he lost 23 golf balls. On wednesday, he lost 2 more. "
     "How many golf balls did he have at the end of wednesday?",
     "Michael started with 58 golf balls. After losing 23 on Tuesday, he had 58 - 23 = 35. "
     "After losing 2 more, he had 35 - 2 = 33 golf balls. The answer is 33."),
    ("If Maria has 2 candies and she gets 4 more, how many candies does she have?",
     "Maria started with 2 candies. She got 4 more. 2 + 4 = 6. The answer is 6."),
]


def build_prompt(q):
    parts = [f"Question: {qq}\nAnswer: {aa}" for qq, aa in EXAMPLES]
    parts.append(f"Question: {q}\nAnswer:")
    return "\n\n".join(parts)


def chat(prompt):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": False,
    }
    req = urllib.request.Request(
        BASE + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {API_KEY}"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        obj = json.loads(r.read().decode())
    msg = obj["choices"][0]["message"]
    reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
    content = msg.get("content") or ""
    ct = (obj.get("usage") or {}).get("completion_tokens", 0)
    return reasoning, content, ct, time.time() - t0


def last_num(s):
    s = s.replace(",", "")
    nums = re.findall(r"\d+", s)
    if not nums:
        return None
    try:
        return int(nums[-1])
    except ValueError:
        return None


def extract_content(content, reasoning):
    m = re.findall(r"\\boxed\{([^}]*)\}", content)
    for cand in reversed(m):
        v = last_num(cand)
        if v is not None:
            return v
    v = last_num(content)
    if v is not None:
        return v
    return last_num(reasoning)


def extract_marker(content, reasoning):
    txt = (content or "") + "\n" + (reasoning or "")
    for cand in reversed(re.findall(r"\\boxed\{([^}]*)\}", txt)):
        v = last_num(cand)
        if v is not None:
            return v
    for m in reversed(re.findall(r"(?:Thus answer|answer is|Answer|answer)[:\s]+([\d,]+)", txt)):
        v = last_num(m)
        if v is not None:
            return v
    v = last_num(content)
    if v is not None:
        return v
    return last_num(reasoning)


def main():
    global BASE, MODEL, API_KEY, MAX_TOKENS, TEMPERATURE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--api-key", default=API_KEY)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--temperature", type=float, default=TEMPERATURE)
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    ap.add_argument("--nq", type=int, default=NQ)
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--out-raw", default=OUT_RAW)
    ap.add_argument("--out-summary", default=OUT_SUMMARY)
    args = ap.parse_args()

    BASE = args.base.rstrip("/")
    API_KEY = args.api_key
    MODEL = args.model
    TEMPERATURE = args.temperature
    MAX_TOKENS = args.max_tokens
    nq = args.nq
    out_raw = args.out_raw
    out_summary = args.out_summary

    rows = [json.loads(l) for l in open(DATA, encoding="utf-8")][args.skip:args.skip+nq]
    results = [None] * nq
    t_start = time.time()

    for i in range(nq):
        row = rows[i]
        goldv = last_num(row["answer"])
        try:
            reasoning, content, ct, dt = chat(build_prompt(row["question"]))
            pc = extract_content(content, reasoning)
            pm = extract_marker(content, reasoning)
            results[i] = {"i": i, "gold": goldv, "pred_content": pc, "pred_marker": pm,
                          "ok_content": pc is not None and pc == goldv,
                          "ok_marker": pm is not None and pm == goldv,
                          "ct": ct, "sec": round(dt, 2), "err": None}
        except Exception as e:  # noqa: BLE001
            results[i] = {"i": i, "gold": goldv, "pred_content": None, "pred_marker": None,
                          "ok_content": False, "ok_marker": False,
                          "ct": 0, "sec": 0.0, "err": str(e)[:200]}
        print(json.dumps({"i": i, "gold": goldv,
                          "pred_content": results[i]["pred_content"],
                          "pred_marker": results[i]["pred_marker"],
                          "ok_content": results[i]["ok_content"],
                          "ct": results[i]["ct"], "sec": results[i]["sec"],
                          "err": results[i]["err"]},
                         ensure_ascii=False), file=sys.stderr, flush=True)
        time.sleep(0.05)

    with open(out_raw, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_ok_c = sum(1 for r in results if r["ok_content"])
    n_ok_m = sum(1 for r in results if r["ok_marker"])
    n_err = sum(1 for r in results if r["err"])
    cts = [r["ct"] for r in results if r["ct"]]
    secs = [r["sec"] for r in results if r["sec"]]
    summary = {
        "base": BASE, "model": MODEL, "nq": nq, "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE, "shots": 8, "concurrency": CONC,
        "accuracy_content": round(n_ok_c / nq, 4), "correct_content": n_ok_c,
        "accuracy_marker": round(n_ok_m / nq, 4), "correct_marker": n_ok_m,
        "err": n_err,
        "median_ct": int(sorted(cts)[len(cts) // 2]) if cts else None,
        "median_elapsed": round(sorted(secs)[len(secs) // 2], 2) if secs else None,
        "elapsed_s": round(time.time() - t_start, 1),
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(out_summary, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

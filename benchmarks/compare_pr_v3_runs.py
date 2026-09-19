#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compare_pr_v3_runs.py -- mechanical 4096-vs-8192 PR-v3 run comparator.

Companion to `pr_matrix_v3.py` / `pr_v3_concurrency.py`. Takes two *sides*
(baseline chunk=4096, candidate chunk=8192), each possibly several run dirs
(one per boot / per wave group), and emits:

  1. a per-cell delta table (Δ% recomputed in python, never by hand),
  2. a step-width change table (clustering of per-stream first-token instants),
  3. a per-criterion PASS / NOGO / BOUNDARY / INVALID / NOT-EVALUATED block.

Design rules that this script enforces
--------------------------------------
* **Missing cells are reported as `MISSING`, never as 0.** A cell absent on
  either side yields no Δ% and is excluded from every verdict numerator and
  denominator (its denominator shrinks, and the shrink is printed).
* **Δ% is always recomputed here.** Nothing is transcribed from a report.
* **Concurrency is judged by first-token clustering, never by
  `ttft_overlap_peak`.** Under `max_new_tokens=1` the single emitted token *is*
  the first token, so `t_end - t_first ~ 0.1 ms` and the interval sweep is
  degenerate (恒为 1). See `pr_v3_concurrency.py`.
* **Wave centre is the median** (house convention, FINAL-METRICS §1.3).
* **Criteria needing inputs this script cannot see** (boot memory floors,
  gate.sh, GSM8K) are reported `NOT-EVALUATED` unless supplied via `--gates`.
  They are never silently treated as PASS.

Why per-wave values come from `raw/` and not `summary.json`
-----------------------------------------------------------
`pr_matrix_v3.py` rewrites `summary.json` after every wave and *drops the
previous wave's cell* (it filters the old (size, conc) entry then appends), so
`summary.json` only ever holds the **last** wave. The raw archives
`<size>-c<N>-w<W>.json` keep every wave, so this script recomputes the cell
figure from the raw records for every wave and cross-checks the last wave
against `summary.json`.

Cell figure recomputed from raw (identical method on both sides, so any bias
cancels in Δ%):
    wall   = max(t_end) - min(t0)      (arm is armed just before dispatch, so
                                        this is a hair shorter than the
                                        harness wall; measured worst-case
                                        deviation vs summary.json on the
                                        09-18 baseline: +0.12%)
    tokens = sum(prompt_tokens of ok streams)
    tps    = tokens / wall

Usage
-----
    # self-test: baseline against itself, every Δ% must be exactly 0.0
    python3 benchmarks/compare_pr_v3_runs.py \
        --base data/prv3-20260918 --new data/prv3-20260918 --self-test

    # real comparison, 8192 side = two boots
    python3 benchmarks/compare_pr_v3_runs.py \
        --base data/prv3-20260918 \
        --new  data/prv3-chunk8192-bootA data/prv3-chunk8192-bootB \
        --gates gates-8192.json

Exit codes: 0 = PASS, 1 = NOGO, 2 = usage/data error,
3 = BOUNDARY (needs a human ruling), 4 = INVALID (not decidable).
"""
import argparse
import glob
import json
import math
import os
import statistics
import sys

# ---------------------------------------------------------------- thresholds
# Every number below is written down before the window opens. Change them here
# and nowhere else; the emitted table echoes them so a report cannot drift.

TOL = 0.010                 # first-token clustering tolerance, seconds

C0_BOOT_MEM_MIN_GB = 14.00  # boot `available_gpu_mem` floor
C0_FLOOR_EFF_PASS = 6.00    # GiB, 1x/4x 245.7K head floor
C0_FLOOR_AVAIL_PASS = 4.00  # GiB
C0_FLOOR_EFF_ABORT = 3.00   # GiB, hard stop
C0_LATENCY_MAX_REGRESS_PCT = 10.0

C1_MEDIAN_MIN_PCT = 10.0    # 8192 row: 2 blocks -> 1 block
C1_MIN_POS_CELLS = 4        # of 5
C23_SHORT_MEDIAN_MIN_PCT = 5.0
C23_SHORT_MEDIAN_NOGO_PCT = -5.0
C4_MIN_ELIGIBLE_PASS = 6    # of 7 eligible cells
C5_LONG_ROWS = (32768, 65536, 131072)
C5_ROW_MEDIAN_NOGO_PCT = -10.0
C5_ROW_MEDIAN_BOUNDARY_PCT = -5.0
C5_SINGLE_CELL_HARD_NOGO_PCT = -20.0

C8_MIN_READINGS = 3             # readings per cell (waves x boots)
C8_MIN_BOOTS = 2                # independent stack restarts
C8_TWOBOOT_MAX_DIVERGENCE_PP = 5.0   # |Δ%_bootA − Δ%_bootB| must be ≤ this

GSM8K_BASELINE = 0.9600     # 192/200, FINAL-METRICS §9
GSM8K_ALLOW = 1             # ±1 题
GSM8K_MIN = (192 - GSM8K_ALLOW) / 200.0

# -------------------------------------------------------------------- model


def pred_width(inp, conc, chunk):
    """chunked-prefill admission law: min(C, max(1, floor(chunk / input))).

    The `max(1, ...)` clamp is load-bearing: for input > chunk the floor is 0
    but the scheduler still runs one request per step. `pr_v3_concurrency.py`
    implements the clamp but *prints* the law without it; CONCURRENCY.md
    repeats the unclamped form. This script prints the clamped form.
    """
    per = chunk // inp
    if per < 1:
        per = 1
    return min(conc, per)


def clusters(vs, tol=TOL):
    vs = sorted(vs)
    out = [[vs[0]]]
    for v in vs[1:]:
        if v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def block_count(inp, chunk):
    return int(math.ceil(inp / chunk))


# ------------------------------------------------------------------- loading


class Side:
    def __init__(self, name, dirs):
        self.name = name
        self.dirs = dirs
        self.cells = {}      # (inp, conc) -> {"waves": [tps...], "widths": [...]}
        self.meta = {}
        self.chunk = None
        self.summary_cells = {}
        self.load()

    def load(self):
        for d in self.dirs:
            sfile = os.path.join(d, "summary.json")
            if not os.path.exists(sfile):
                raise SystemExit(f"{self.name}: no summary.json under {d}")
            summ = json.load(open(sfile, encoding="utf-8"))
            m = summ["_meta"]
            chunk = int(m.get("chunked_prefill_size"))
            if self.chunk is None:
                self.chunk = chunk
                self.meta = m
            elif self.chunk != chunk:
                raise SystemExit(
                    f"{self.name}: mixed chunked_prefill_size across dirs "
                    f"({self.chunk} vs {chunk}); a side must be one config")
            for c in summ["cells"]:
                self.summary_cells[(c["input_tokens"], c["concurrency"])] = c
            for f in sorted(glob.glob(os.path.join(d, "raw", "*-c*-w*.json"))):
                self._load_raw(f)
        if self.chunk is None:
            raise SystemExit(f"{self.name}: could not determine chunk size")

    def _load_raw(self, f):
        recs = json.load(open(f, encoding="utf-8"))
        ok = [r for r in recs if not r.get("error") and r.get("t_first")]
        if not ok:
            return
        inp = ok[0].get("input_tokens") or ok[0].get("prompt_tokens")
        conc = len(recs)
        wall = max(r["t_end"] for r in ok) - min(r["t0"] for r in ok)
        toks = sum(r["prompt_tokens"] for r in ok)
        tps = toks / wall if wall > 0 else None
        cl = clusters([r["t_first"] for r in ok])
        width = max(len(c) for c in cl)
        cell = self.cells.setdefault((inp, conc), {"waves": [], "widths": []})
        cell["waves"].append(tps)
        cell["widths"].append(width)

    def value(self, key):
        """median over waves; also min/max/spread."""
        c = self.cells.get(key)
        if not c or not c["waves"]:
            return None
        w = [x for x in c["waves"] if x]
        if not w:
            return None
        med = statistics.median(w)
        spread = (max(w) - min(w)) / med * 100.0 if med else 0.0
        return {"median": med, "min": min(w), "max": max(w),
                "spread": spread, "n": len(w),
                "width": int(round(statistics.median(c["widths"])))}

    def _manifest(self):
        for c in self.summary_cells.values():
            v = c.get("manifest_sha256")
            if v:
                return str(v)[:16]
        return "n/a"

    def crosscheck(self):
        """worst |raw-recompute - summary.json| over cells, in %."""
        worst, at = 0.0, None
        for k, v in self.cells.items():
            s = self.summary_cells.get(k)
            if not s or not v["waves"]:
                continue
            h = s.get("total_throughput_tps")
            if not h:
                continue
            d = abs(v["waves"][-1] - h) / h * 100.0
            if d > worst:
                worst, at = d, k
        return worst, at


def pct(new, old):
    return (new - old) / old * 100.0


def row_delta(base_side, other, keys):
    """median Δ% over `keys`, comparing `other` against `base_side`."""
    ds = []
    for k in keys:
        b = base_side.value(k)
        n = other.value(k)
        if b and n:
            ds.append(pct(n["median"], b["median"]))
    return statistics.median(ds) if ds else None


def fmt(v, nd=1):
    return "MISSING" if v is None else f"{v:.{nd}f}"


def fpct(v, nd=2):
    return "MISSING" if v is None else f"{v:+.{nd}f}"


# ------------------------------------------------------------------ verdicts


def main():
    global TOL
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", nargs="+", required=True)
    ap.add_argument("--new", nargs="+", required=True)
    ap.add_argument("--tol", type=float, default=TOL)
    ap.add_argument("--gates", help="JSON with boot-memory / gate / gsm8k inputs")
    ap.add_argument("--self-test", action="store_true",
                    help="same-side compare: assert every Δ%% is exactly 0")
    ap.add_argument("--out", help="also write the report here")
    a = ap.parse_args()

    TOL = a.tol

    base = Side("base", a.base)
    new = Side("new", a.new)

    lines = []
    P = lines.append

    sizes = sorted(set(list(base.meta.get("sizes", [])) +
                       [k[0] for k in base.cells] + [k[0] for k in new.cells]))
    concs = sorted(set(list(base.meta.get("concurrencies", [])) +
                       [k[1] for k in base.cells] + [k[1] for k in new.cells]))
    if not sizes or not concs:
        raise SystemExit("no cells found on either side")

    P("## chunk %d → %d · PR-v3 逐格对比（机械生成）" % (base.chunk, new.chunk))
    P("")
    P("| 项 | base (chunk=%d) | new (chunk=%d) |" % (base.chunk, new.chunk))
    P("|---|---|---|")
    P("| run dirs | %s | %s |" % (", ".join(base.dirs), ", ".join(new.dirs)))
    P("| run_tag | %s | %s |" % (base.meta.get("run_tag"), new.meta.get("run_tag")))
    P("| manifest | %s | %s |" % (base._manifest(), new._manifest()))
    P("| waves/cell (max) | %d | %d |" %
      (max((len(v["waves"]) for v in base.cells.values()), default=0),
       max((len(v["waves"]) for v in new.cells.values()), default=0)))
    cb, atb = base.crosscheck()
    cn, atn = new.crosscheck()
    P("| raw 复算 vs summary.json 最大偏差 | %s%% @ %s | %s%% @ %s |" %
      (f"{cb:.3f}", atb, f"{cn:.3f}", atn))
    P("| 聚类容差 | %.3f s | %.3f s |" % (TOL, TOL))
    P("")

    # ---------------------------------------------------------- delta table
    P("### 1. 逐格 Δ%（格中心值 = 各波中位）")
    P("")
    P(f"| Input | C | blocks {base.chunk}→{new.chunk} | base t/s | new t/s | Δ% | "
      f"base spread% | new spread% | 可分辨 | 步宽 {base.chunk}→{new.chunk} | 预测步宽 |")
    P("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    deltas = {}
    n_missing = 0
    for s in sizes:
        for c in concs:
            k = (s, c)
            b = base.value(k)
            n = new.value(k)
            pb = pred_width(s, c, base.chunk)
            pn = pred_width(s, c, new.chunk)
            if b is None or n is None:
                n_missing += 1
                P(f"| {s} | {c} | {block_count(s, base.chunk)}→"
                  f"{block_count(s, new.chunk)} | {fmt(b and b['median'])} | "
                  f"{fmt(n and n['median'])} | **MISSING** | — | — | — | — | — |")
                continue
            d = pct(n["median"], b["median"])
            noise = max(b["spread"], n["spread"])
            resolvable = abs(d) > noise
            deltas[k] = {"d": d, "noise": noise, "resolvable": resolvable}
            P(f"| {s} | {c} | {block_count(s, base.chunk)}→"
              f"{block_count(s, new.chunk)} | {b['median']:.1f} | {n['median']:.1f} | "
              f"**{d:+.2f}** | {b['spread']:.2f} | {n['spread']:.2f} | "
              f"{'yes' if resolvable else 'NO'} | {b['width']}→{n['width']} | {pb}→{pn} |")
    P("")
    P("⛔ **MISSING 格数 = %d**（缺格不计入任何判定的分子与分母；分母收缩数已在上表体现）。"
      % n_missing)
    P("")

    if a.self_test:
        bad = [(k, v["d"]) for k, v in deltas.items() if abs(v["d"]) > 1e-9]
        P("### SELF-TEST")
        P("")
        P("比较格数 = %d，非零 Δ%% 的格 = %d" % (len(deltas), len(bad)))
        for k, v in bad[:20]:
            P(f"  - {k}: {v:+.6f}")
        out = "\n".join(lines)
        print(out)
        if a.out:
            open(a.out, "w", encoding="utf-8").write(out + "\n")
        if bad:
            print("\nSELF-TEST FAILED", file=sys.stderr)
            return 2
        print("\nSELF-TEST OK: every Δ% is exactly 0.000000")
        return 0

    # ------------------------------------------------------ step-width table
    P("### 2. 准入步宽变化（逐流首包时刻聚类，容差 %.3f s；**不用** "
      "`ttft_overlap_peak`）" % TOL)
    P("")
    P("| Input | C | 预测 %d | 实测 %d | 预测 %d | 实测 %d | 准入增益格 | 达标 |" %
      (base.chunk, base.chunk, new.chunk, new.chunk))
    P("|---:|---:|---:|---:|---:|---:|---:|---:|")
    eligible = []
    hits = 0
    for s in sizes:
        for c in concs:
            k = (s, c)
            b = base.value(k)
            n = new.value(k)
            if b is None or n is None:
                continue
            pb = pred_width(s, c, base.chunk)
            pn = pred_width(s, c, new.chunk)
            is_elig = pn > pb
            ok = (n["width"] >= pn) if is_elig else None
            if is_elig:
                eligible.append(k)
                if ok:
                    hits += 1
            P(f"| {s} | {c} | {pb} | {b['width']} | {pn} | {n['width']} | "
              f"{'YES' if is_elig else '—'} | "
              f"{('达标' if ok else '未达标') if is_elig else '—'} |")
    P("")
    P("准入增益格（predicted_new > predicted_base）= **%d** 格；达标 = **%d/%d**。"
      % (len(eligible), hits, len(eligible)))
    P("")
    P("> 判据用**聚类步宽**，不用 `overlap peak`：`max_new_tokens=1` 下唯一产出的 "
      "token 就是首 token，`t_end − t_first ≈ 0.1 ms`，区间扫描恒为 1。")
    P("")

    # ------------------------------------------------------------- criteria
    P("### 3. 事前判据逐条结论")
    P("")
    P("| # | 判据 | 阈值（事前写死） | 实测 | 结论 |")
    P("|---|---|---|---|---|")

    verdicts = {}

    def row_median(keys):
        ds = [deltas[k]["d"] for k in keys if k in deltas]
        if not ds:
            return None, 0
        return statistics.median(ds), len(ds)

    # C1 -- the 8192 row (only row whose block count falls to 1)
    c1_keys = [(8192, c) for c in concs]
    c1_med, c1_n = row_median(c1_keys)
    c1_pos = sum(1 for k in c1_keys if k in deltas and deltas[k]["d"] > 0)
    if c1_med is None:
        v1 = "INVALID"
    elif c1_med >= C1_MEDIAN_MIN_PCT and c1_pos >= C1_MIN_POS_CELLS:
        v1 = "PASS"
    elif c1_med <= 0:
        v1 = "NOGO"
    else:
        v1 = "BOUNDARY"
    verdicts["C1"] = v1
    P(f"| **C1** | 8192 档（**唯一 2 块→1 块**）中位 Δ% | ≥ **+{C1_MEDIAN_MIN_PCT:.0f}%** 且 "
      f"≥{C1_MIN_POS_CELLS}/5 格为正 | 中位 {fmt(c1_med, 2)}%（n={c1_n}），正格 {c1_pos}/5 | "
      f"**{v1}** |")

    # C2 -- 4096 row, admission 1 -> 2 (C2..C16)
    c2_keys = [(4096, c) for c in concs if c >= 2]
    c2_med, c2_n = row_median(c2_keys)
    v2 = ("INVALID" if c2_med is None else
          "PASS" if c2_med >= C23_SHORT_MEDIAN_MIN_PCT else
          "NOGO" if c2_med <= C23_SHORT_MEDIAN_NOGO_PCT else "BOUNDARY")
    verdicts["C2"] = v2
    P(f"| **C2** | 4096 档（准入 1→2）C2..C16 中位 Δ% | ≥ **+{C23_SHORT_MEDIAN_MIN_PCT:.0f}%** | "
      f"{fmt(c2_med, 2)}%（n={c2_n}） | **{v2}** |")

    # C3 -- 2048 row, admission 2 -> 4 (C4..C16)
    c3_keys = [(2048, c) for c in concs if c >= 4]
    c3_med, c3_n = row_median(c3_keys)
    v3 = ("INVALID" if c3_med is None else
          "PASS" if c3_med >= C23_SHORT_MEDIAN_MIN_PCT else
          "NOGO" if c3_med <= C23_SHORT_MEDIAN_NOGO_PCT else "BOUNDARY")
    verdicts["C3"] = v3
    P(f"| **C3** | 2048 档（准入 2→4）C4..C16 中位 Δ% | ≥ **+{C23_SHORT_MEDIAN_MIN_PCT:.0f}%** | "
      f"{fmt(c3_med, 2)}%（n={c3_n}） | **{v3}** |")

    # C4 -- admission width release.
    # `expected` is derived from the admission law over the *whole* grid, so a
    # missing cell cannot silently shrink the bar; `measured` counts only the
    # expected-eligible cells that actually have both sides present.
    expected = [(s, c) for s in sizes for c in concs
                if pred_width(s, c, new.chunk) > pred_width(s, c, base.chunk)]
    measured = [k for k in expected if base.value(k) and new.value(k)]
    if not expected:
        v4 = "不适用"
        note4 = "两侧 chunk 相同 ⇒ 无准入增益格"
    elif len(measured) < C4_MIN_ELIGIBLE_PASS:
        v4 = "INVALID"
        note4 = (f"应测 {len(expected)} 格，实测 {len(measured)} 格 < "
                 f"{C4_MIN_ELIGIBLE_PASS} ⇒ 分母不足，不可判")
    else:
        v4 = ("PASS" if hits >= C4_MIN_ELIGIBLE_PASS else
              "BOUNDARY" if hits >= C4_MIN_ELIGIBLE_PASS - 2 else "NOGO")
        note4 = f"{hits}/{len(measured)} 达标（应测 {len(expected)} 格）"
    verdicts["C4"] = v4
    P(f"| **C4** | 准入步宽解除（聚类步宽 ≥ 预测值） | "
      f"≥ **{C4_MIN_ELIGIBLE_PASS}** 格达标，且实测分母 ≥ {C4_MIN_ELIGIBLE_PASS} | "
      f"{note4} | **{v4}** |")

    # C5 -- long rows red line
    worst_cell = None
    v5 = "NOT-EVALUATED"
    detail5 = []
    for s in C5_LONG_ROWS:
        ks = [(s, c) for c in concs]
        med, n = row_median(ks)
        if med is None:
            detail5.append(f"{s}: MISSING")
            continue
        detail5.append(f"{s}: {med:+.2f}%（n={n}）")
        if med <= C5_ROW_MEDIAN_NOGO_PCT:
            if v5 != "NOGO":
                v5 = "NOGO"
        elif med <= C5_ROW_MEDIAN_BOUNDARY_PCT and v5 not in ("NOGO",):
            v5 = "BOUNDARY"
        elif v5 == "NOT-EVALUATED":
            v5 = "PASS"
        for k in ks:
            if k in deltas and deltas[k]["d"] <= C5_SINGLE_CELL_HARD_NOGO_PCT:
                v5 = "NOGO"
                worst_cell = (k, deltas[k]["d"])
    if any(med is not None for med in [row_median([(s, c) for c in concs])[0]
                                       for s in C5_LONG_ROWS]):
        if v5 == "NOT-EVALUATED":
            v5 = "INVALID"
    verdicts["C5"] = v5
    P(f"| **C5** | 长档红线（≥32768）| 行中位 ≤ **{C5_ROW_MEDIAN_NOGO_PCT:.0f}%** ⇒ NOGO；"
      f"单点 ≤ **{C5_SINGLE_CELL_HARD_NOGO_PCT:.0f}%** ⇒ NOGO | "
      f"{'; '.join(detail5)}"
      f"{'；单点塌方 ' + str(worst_cell) if worst_cell else ''} | **{v5}** |")

    # C8 -- error bars / two-boot reproduction
    # Readings, not waves: a "wave" is a repeat inside one boot, a "boot" is an
    # independent stack restart. Both axes are required -- waves give the error
    # bar, boots give reproduction across start-up state.
    nread_new = max((len(v["waves"]) for v in new.cells.values()), default=0)
    nread_base = max((len(v["waves"]) for v in base.cells.values()), default=0)
    boots_new = len(new.dirs)      # convention: one run dir per boot
    boots_base = len(base.dirs)
    spreads = [v["spread"] for v in
               (base.value(k) for k in base.cells) if v]
    bspread = max(spreads) if spreads else None
    if nread_base < 2:
        v8 = "INVALID"
        note8 = (f"基线每格仅 {nread_base} 个读数 ⇒ **基线无误差棒**，"
                 f"Δ% 不可判（须同窗复测 4096 ≥2 读数）")
    elif nread_new < C8_MIN_READINGS:
        v8 = "INVALID"
        note8 = f"8192 侧每格仅 {nread_new} 个读数（要求 ≥{C8_MIN_READINGS}）"
    elif boots_new < C8_MIN_BOOTS:
        v8 = "INVALID"
        note8 = (f"8192 侧仅跨 {boots_new} 个起栈（要求 ≥{C8_MIN_BOOTS} 靴）；"
                 f"同靴多波不能替代跨靴复现")
    else:
        v8 = "PASS"
        note8 = (f"基线 {nread_base} 读数/{boots_base} 靴；"
                 f"8192 {nread_new} 读数/{boots_new} 靴；"
                 f"基线最大格内 spread {fmt(bspread, 2)}%")
        if boots_new >= 2:
            # two-boot reproduction: the row median Δ% must agree across boots
            sets = {"C1": c1_keys, "C2": c2_keys, "C3": c3_keys}
            worst_pp, worst_row = 0.0, None
            for label, keys in sets.items():
                per = [row_delta(base, Side("boot", [d]), keys) for d in new.dirs]
                if any(x is None for x in per):
                    continue
                div = max(per) - min(per)
                if div > worst_pp:
                    worst_pp, worst_row = div, label
            if worst_row is not None:
                note8 += (f"；两靴最大分歧 {worst_pp:.2f} pp（{worst_row}，"
                          f"门 ≤ {C8_TWOBOOT_MAX_DIVERGENCE_PP:.1f} pp）")
                if worst_pp > C8_TWOBOOT_MAX_DIVERGENCE_PP:
                    v8 = "INVALID"
                    note8 += " ⇒ **两靴不一致，不可判**"
    verdicts["C8"] = v8
    P(f"| **C8** | 误差棒与两靴复现 | 8192 ≥3 波且跨 ≥2 靴；基线须同窗复测 ≥2 波 | "
      f"{note8} | **{v8}** |")

    # C0 / C6 / C7 -- external inputs
    gates = {}
    if a.gates:
        gates = json.load(open(a.gates, encoding="utf-8"))

    def ext(name, fn):
        if name not in gates:
            P(f"| {name} | 外部输入 | — | 未提供 `--gates` ⇒ 不判定 | "
              f"**NOT-EVALUATED** |")
            verdicts[name] = "NOT-EVALUATED"
            return
        v, txt = fn(gates[name])
        verdicts[name] = v
        P(f"| {name} | 外部输入 | — | {txt} | **{v}** |")

    def c0(v):
        ok = v >= C0_BOOT_MEM_MIN_GB
        return ("PASS" if ok else "NOGO",
                f"available_gpu_mem = {v:.2f} GB（门 ≥ {C0_BOOT_MEM_MIN_GB:.2f}）")

    ext("C0", c0)

    def c0b(v):
        e, av = v["eff"], v["avail"]
        if e < C0_FLOOR_EFF_ABORT:
            return "NOGO", f"eff {e:.2f} GiB < {C0_FLOOR_EFF_ABORT:.2f}（硬停）"
        if e >= C0_FLOOR_EFF_PASS and av >= C0_FLOOR_AVAIL_PASS:
            return "PASS", f"eff {e:.2f} / avail {av:.2f} GiB"
        return "BOUNDARY", f"eff {e:.2f} / avail {av:.2f} GiB（擦线区）"

    ext("C0b", c0b)

    def c0c(v):
        e, av = v["eff"], v["avail"]
        if e < C0_FLOOR_EFF_ABORT:
            return "NOGO", f"eff {e:.2f} GiB < {C0_FLOOR_EFF_ABORT:.2f}（硬停）"
        if e >= C0_FLOOR_EFF_PASS and av >= C0_FLOOR_AVAIL_PASS:
            return "PASS", f"eff {e:.2f} / avail {av:.2f} GiB"
        return "BOUNDARY", f"eff {e:.2f} / avail {av:.2f} GiB（擦线区）"

    ext("C0c", c0c)

    def c0d(v):
        d1 = pct(v["1x_new"], v["1x_base"])
        d4 = pct(v["4x_new"], v["4x_base"])
        worst = max(d1, d4)
        return ("PASS" if worst <= C0_LATENCY_MAX_REGRESS_PCT else "NOGO",
                f"1× {d1:+.2f}% / 4× {d4:+.2f}%（门 ≤ +{C0_LATENCY_MAX_REGRESS_PCT:.0f}%）")

    ext("C0d", c0d)

    def c6(v):
        return ("PASS" if v else "NOGO", f"gate.sh --full = {v}")

    ext("C6", c6)

    def c7(v):
        return ("PASS" if v >= GSM8K_MIN else "NOGO",
                f"GSM8K = {v:.4f}（门 ≥ {GSM8K_MIN:.4f} = 基线 −{GSM8K_ALLOW} 题）")

    ext("C7", c7)

    P("")

    # -------------------------------------------------------------- overall
    order = ["C0", "C0b", "C0c", "C0d", "C1", "C2", "C3", "C4", "C5", "C6",
             "C7", "C8"]
    counted = [verdicts[o] for o in order if o in verdicts]
    if "NOGO" in counted:
        overall, rc = "NOGO", 1
    elif "INVALID" in counted:
        overall, rc = "INVALID（不可判，须补数）", 4
    elif "BOUNDARY" in counted:
        overall, rc = "BOUNDARY（需人工裁定）", 3
    elif "NOT-EVALUATED" in counted:
        overall, rc = "NOT-EVALUATED（外部输入未给全）", 3
    else:
        overall, rc = "PASS", 0

    P("### 4. 总判定")
    P("")
    P("**%s**" % overall)
    P("")
    P("逐条：%s" % ", ".join(f"{o}={verdicts[o]}" for o in order if o in verdicts))
    P("")
    P("> 阈值常量在本脚本头部（`TOL` / `C0_*` / `C1_*` / `C23_*` / `C4_*` / "
      "`C5_*` / `GSM8K_*`），改判据只改那里；本表逐条回显阈值，报告无法与之漂移。")

    out = "\n".join(lines)
    print(out)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(out + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())

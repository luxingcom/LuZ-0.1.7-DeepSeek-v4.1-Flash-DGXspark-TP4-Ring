#!/usr/bin/env bash
# boot-signature.sh — 起栈签名检查（靴态），补上质量门查不出的那一维。
#
# 由来：2026-09-16 慢靴事故 —— 质量门（gate 4/4、code 12/12、corruption 0 U+FFFD）**全绿**，
# 但生产解码慢 ~10-25×（c1 2.4 t/s vs 56.8；decode 1.75 s/步 vs ~0.06）。
# 快慢两靴**配置逐字节相同**（`.env.tp4` md5 相同），唯一变量是"哪一次靴"。
# 处置 = 配置不动直接重启（2026-09-16 实测单次重启即恢复）。
#
# ★★ 判据在 2026-09-16 晚**被实测推翻过一次**，本版是修订版（依据 `SLOWBOOT-FORENSICS.md`）：
#   · 旧版主判据是 `capture elapsed > 20s`。**已证伪（既不充分）**：
#       2026-09-14 04:14 靴 capture=**30.00s**（2.90s/层，与慢靴同族）却**健康**
#       （warmup 12s、探针 57-67 t/s）⇒ 单靠 capture 会把好靴重启掉。
#   · `Warm-up done in Ns` **从判据中删除**：健康靴也有 141s/250s 的，
#       那是 **prompt 工作量驱动**（257K/474K token），不是靴态。
#   · 新主判据 = **warmup 块的 per-batch `input throughput (token/s)` 中位数**：
#       同一份日志自带、**零流量依赖**、且分离度大：
#         健康 13:10 靴 **median 663**（n=8）  vs  慢靴 09:55 靴 **median 55**（n=17）
#         （独立复算：本文件作者用暖靴/慢靴两段切片实算，非转述）
#   · capture elapsed 保留为**警告**：它不能单独触发重启，但值得记一笔。
#
# 用法：
#   boot-signature.sh            # 只读日志判靴态（零成本、零流量）
#   boot-signature.sh --bench    # 追加 canonical 吞吐（会起流量，~400s）
#
# ⚠GB10 环境已知不可读字段（别在这上面浪费时间）：`clocks.memory` / `supported_clocks`
#   / `power.limit` 均为 **N/A**；DCGM 在 GB10 无 DRAM 计数器。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${DSV41_LOG:-$ROOT/logs-tp4/dsv41.log}"
KEY="${DSV41_API_KEY:-$(grep -m1 '^API_KEY=' "$ROOT/.env.tp4" 2>/dev/null | cut -d= -f2-)}"
DO_BENCH=0
[ "${1:-}" = "--bench" ] && DO_BENCH=1

fail=0
say() { printf '%s %s\n' "$1" "$2"; }

# ---- 1) ★主判据：warmup 块的 per-batch 吞吐中位数 ---------------------------
# warmup 块 = `The server is fired up and ready to roll!` 之后、`Warm-up done in ...` 之前。
# 这一段**每次起栈必有**，所以本判据在全新靴上也能判定（这是它优于 decode 间隔的地方，
# 后者要等流量才有采样，见下方 3)。
warm="$(python3 - "$LOG" <<'EOF' 2>/dev/null
import re, statistics as st, sys
lines = open(sys.argv[1], errors='ignore').read().split('\n')
lo = hi = None
for i, l in enumerate(lines):
    if lo is None and 'The server is fired up and ready to roll' in l:
        lo = i
    if lo is not None and 'Warm-up done in' in l:
        hi = i
        break
if lo is None or hi is None:
    print(""); raise SystemExit
vals = []
for l in lines[lo:hi]:
    m = re.search(r'input throughput \(token/s\): ([0-9.]+)', l)
    if m:
        vals.append(float(m.group(1)))
if not vals:
    print(""); raise SystemExit
dur = re.search(r'Warm-up done in (\d+)s', lines[hi])
print(f"{st.median(vals):.1f} {min(vals):.1f} {max(vals):.1f} {len(vals)} {dur.group(1) if dur else '?'}")
EOF
)"
if [ -n "$warm" ]; then
  wmed="$(echo "$warm" | awk '{print $1}')"; wmin="$(echo "$warm" | awk '{print $2}')"
  wmax="$(echo "$warm" | awk '{print $3}')"; wn="$(echo "$warm" | awk '{print $4}')"
  wdur="$(echo "$warm" | awk '{print $5}')"
  if awk "BEGIN{exit !($wmed < 200)}"; then
    say '[✗]' "warmup 吞吐中位=${wmed} t/s (<200；健康 388-709，慢靴 ~55；n=${wn}, min=${wmin}, max=${wmax}, warmup ${wdur}s)"
    say '[✗]' "⇒ **判慢靴态** ⇒ 处置=**配置不动重启**（实测单次重启即恢复）"
    fail=1
  elif awk "BEGIN{exit !($wmed < 400)}"; then
    say '[!]' "warmup 吞吐中位=${wmed} t/s 在 200-400 灰区（n=${wn}, warmup ${wdur}s）⇒ 建议 --bench 复核"
  else
    say '[+]' "warmup 吞吐中位=${wmed} t/s（n=${wn}, min=${wmin}, warmup ${wdur}s）⇒ 靴态正常"
  fi
else
  say '[!]' "找不到 warmup 块（日志里没有 'fired up'/'Warm-up done' 对）—— **主判据未判定**；若刚起栈请稍后重跑"
  fail=1
fi

# ---- 2) 参考项：capture elapsed（**降级为警告，不能单独触发重启**）---------
cap="$(sed -n 's/.*Capture target verify CUDA graph end\. elapsed=\([0-9][0-9.]*\) s.*/\1/p' "$LOG" 2>/dev/null | tail -1)"
if [ -z "$cap" ]; then
  say '[i]' "读不到 capture elapsed（日志缺该行）—— 参考项跳过"
elif awk "BEGIN{exit !($cap > 10)}"; then
  say '[!]' "capture=${cap}s > 10s（健康 5.7-6.7s）—— ⚠**仅供参考**：2026-09-14 有 capture=30.0s 而健康的反例 ⇒ 本项**不单独判 FAIL**；以 warmup 吞吐为准"
else
  say '[+]' "capture=${cap}s（参考项，正常）"
fi

# ---- 3) decode 40 步间隔：需流量；有流量时是强判据 -------------------------
cad="$(python3 - "$LOG" <<'EOF' 2>/dev/null
import re,sys
from datetime import datetime
ts=[m.group(1) for m in (re.search(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[^\]]*\] Decode batch',l) for l in open(sys.argv[1],errors='ignore')) if m]
# 只取最近 12 个间隔：解码行每 40 步打一行，但**空闲期不打** ⇒ 大间隔既可能是慢靴、
# 也可能是"引擎空转"，中位数会把空转误判成慢靴（2026-09-16 实测踩到：空闲 2h ⇒ 中位 1244s）。
# 判"慢"要用**最快的一档**：min = 最近实际跑出的最好 40 步耗时。空闲间隔只会更大，永不误伤。
if len(ts)<4: print(""); raise SystemExit
d=[(datetime.strptime(ts[i],'%Y-%m-%d %H:%M:%S')-datetime.strptime(ts[i-1],'%Y-%m-%d %H:%M:%S')).total_seconds() for i in range(1,len(ts))]
d=d[-12:]
print(f"{min(d):.1f} {sorted(d)[len(d)//2]:.1f} {len(d)}")
EOF
)"
if [ -n "$cad" ]; then
  cmin="$(echo "$cad" | awk '{print $1}')"; cmed="$(echo "$cad" | awk '{print $2}')"; cn="$(echo "$cad" | awk '{print $3}')"
  if awk "BEGIN{exit !($cmin > 20)}"; then
    say '[✗]' "decode 40 步**最快**间隔=${cmin}s（正常 2-6s；中位 ${cmed}s，n=${cn}）⇒ **每步开销异常**（慢靴 ~70s）"
    fail=1
  else
    say '[+]' "decode 40 步最快间隔=${cmin}s（中位 ${cmed}s，n=${cn}）⇒ 步时正常"
    awk "BEGIN{exit !($cmed > 20)}" && \
      say '[i]' "中位 ${cmed}s 偏大但最快仅 ${cmin}s ⇒ 判**空闲/低流量**，非慢靴（避免误报）"
  fi
else
  say '[i]' "decode 采样不足（<4 行）—— 步时维**未判定**（本项需流量；主判据不依赖它）"
fi

# ---- 4) 可选：canonical 吞吐 ----------------------------------------------
if [ "$DO_BENCH" = "1" ]; then
  if [ -z "$KEY" ]; then say '[!]' "拿不到 API key，跳过 bench"; else
    out="$(timeout 400 python3 "$ROOT/bench/bench_tp.py" --base http://127.0.0.1:8899/v1 \
             --model deepseek-v4.1-flash --key "$KEY" --conc 1 --max-tokens 400 \
             --prompt-type code 2>&1 | tail -3)"
    echo "$out"
    tps="$(echo "$out" | awk '/^ *1 /{print $4}')"
    ttft="$(echo "$out" | awk '/^ *1 /{print $2}')"
    if [ -n "$tps" ] && awk "BEGIN{exit !($tps < 20)}"; then
      say '[✗]' "bench c1=${tps} t/s (TTFT ${ttft}) < 20 ⇒ **判慢靴，重启**（配置不动）"; fail=1
    else
      say '[+]' "bench c1=${tps} t/s (TTFT ${ttft}) ⇒ 吞吐正常"
    fi
  fi
fi

echo
  # DSV41 2026-09-19：无抽签断言（慢靴根因=autotune tactic 彩票）
  _DL=$(docker logs dsv41-head 2>&1 || true)
  if [ "$fail" = 0 ] && grep -q "tuning from scratch" <<<"$_DL"; then
    echo "[!] 检测到 autotune 冷启动重签 —— 本靴 tactic 为新抽，慢靴风险；重启一次再判"
    exit 1
  fi
  if [ "$fail" = 0 ] && grep -q "majority-vote adopted" <<<"$_DL"; then
    echo "[+] autotune tactic 已钉住（多数表决采纳，无重抽）"
  fi
  if [ "$fail" = 0 ]; then echo "[+] BOOT SIGNATURE OK"; else
      echo '[✗] BOOT SIGNATURE FAIL —— 质量门查不出这个；处置见本脚本头部注释'
  fi
  exit "$fail"

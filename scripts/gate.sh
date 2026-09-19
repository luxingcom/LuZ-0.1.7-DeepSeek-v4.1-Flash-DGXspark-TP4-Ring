#!/bin/bash
# gate.sh — 「容器 Up ≠ 服务可信」。一次判定当前引擎是否可交付。
#
# 用法：
#   gate.sh            快档（~2 分钟）：/health + 算术 + 结构化 + 工具 + corruption + code-gate
#   gate.sh --full     全档（~12 分钟）：快档 + 终止性 + needle 梯度(30K/229K/470K)
#   gate.sh --json     机器可读汇总（最后一行 JSON）
#
# 退出码：0 全过 · 1 有失败
#
# 设计取舍：默认快档要能在一次换班/切换后立刻跑完，覆盖「最常被打断的正确性」
# 而非吞吐；吞吐由 bench/ 下的基准负责。

set -uo pipefail

PORT="${SERVER_PORT:-8899}"
KEY_FILE="${API_KEY_FILE:-$HOME/dsv41-flash-dgxsparks/state-tp4/api-key}"
BASE="http://127.0.0.1:${PORT}"
FULL=0
JSON=0
for a in "$@"; do
  case "$a" in
    --full) FULL=1 ;;
    --json) JSON=1 ;;
  esac
done

KEY=""
[[ -f "$KEY_FILE" ]] && KEY="$(cat "$KEY_FILE")"
auth=()
[[ -n "$KEY" ]] && auth=(-H "Authorization: Bearer $KEY")

pass=0; fail=0
declare -a results=()
ok()   { results+=("PASS  $1"); pass=$((pass+1)); echo "[+] $1"; }
bad()  { results+=("FAIL  $1"); fail=$((fail+1)); echo "[x] $1"; }

ask() {  # ask <json-body>
  curl -s --max-time 300 "${auth[@]}" -H 'Content-Type: application/json' \
    -d "$1" "$BASE/v1/chat/completions"
}

# ── 1. 健康 ────────────────────────────────────────────────────────────────
# DSV41 2026-09-19 P2⑥：内核守卫（客户坑 2：7.0.0-1019 打瘫 NCCL 的故障内核）
KERN=$(uname -r)
if [[ "$KERN" == 7.0.* ]]; then
  bad "内核 $KERN = 已知打瘫 NCCL/RoCE 的故障内核（ibv_reg_mr_iova2 ENOMEM）；须回退 6.17.0-1031+"
fi
# 2026-09-19 外部报告借鉴：引擎 /health 写死 1s 延迟，探活改 /v1/models（同 200 判定，快 ~1000×）
if curl -fsS --max-time 10 "${auth[@]}" "$BASE/v1/models" >/dev/null 2>&1 \
   || curl -fsS --max-time 10 "$BASE/v1/models" >/dev/null 2>&1; then
  ok "engine /v1/models 200"
else
  bad "engine /health 非 200 —— 服务不可交付"
fi

# ── 2. 算术（贪心确定性） ──────────────────────────────────────────────────
r=$(ask '{"model":"deepseek-v4.1-flash","temperature":0,"max_tokens":16,
  "chat_template_kwargs":{"thinking":false},
  "messages":[{"role":"user","content":"What is 19 + 23? Reply only the number."}]}')
if printf '%s' "$r" | python3 -c 'import json,sys
try:
    sys.exit(0 if json.load(sys.stdin)["choices"][0]["message"]["content"].strip() == "42" else 1)
except Exception:
    sys.exit(1)' 2>/dev/null; then
  ok "算术 19+23=42"
else
  bad "算术失败: ${r:0:120}"
fi

# ── 3. 结构化输出 ──────────────────────────────────────────────────────────
r=$(ask '{"model":"deepseek-v4.1-flash","temperature":0,"max_tokens":64,
  "chat_template_kwargs":{"thinking":false},
  "response_format":{"type":"json_schema","json_schema":{"name":"a","strict":true,
    "schema":{"type":"object","properties":{"answer":{"type":"integer"}},
              "required":["answer"],"additionalProperties":false}}},
  "messages":[{"role":"user","content":"Return an object whose answer is the integer 42."}]}')
if printf '%s' "$r" | python3 -c 'import json,sys
try:
    c = json.load(sys.stdin)["choices"][0]["message"]["content"]
    sys.exit(0 if json.loads(c) == {"answer": 42} else 1)
except Exception:
    sys.exit(1)' 2>/dev/null; then
  ok "JSON schema 结构化输出"
else
  bad "结构化失败: ${r:0:120}"
fi

# ── 4. 工具调用 ────────────────────────────────────────────────────────────
r=$(ask '{"model":"deepseek-v4.1-flash","temperature":0,"max_tokens":96,
  "chat_template_kwargs":{"thinking":false},
  "tools":[{"type":"function","function":{"name":"lookup","description":"get value",
    "parameters":{"type":"object","properties":{"key":{"type":"string"}},
                  "required":["key"],"additionalProperties":false}}}],
  "messages":[{"role":"user","content":"Use lookup to get the value for key alpha. Do not guess."}]}')
if printf '%s' "$r" | python3 -c 'import json,sys
try:
    t = json.load(sys.stdin)["choices"][0]["message"].get("tool_calls") or []
    sys.exit(0 if (len(t) == 1 and t[0]["function"]["name"] == "lookup"
                   and json.loads(t[0]["function"]["arguments"]) == {"key": "alpha"}) else 1)
except Exception:
    sys.exit(1)' 2>/dev/null; then
  ok "工具调用（tool_calls，参数正确）"
else
  bad "工具调用失败: ${r:0:160}"
fi

# ── 5/6. corruption + code-gate（复用 gates_suite，容器内跑） ───────────────
# gates_suite.py 必须在 /state（= 宿主 state-tp4/）里，否则下面这三档会**静默跳过**。
# 历史教训：那段"跳过"曾经一挂就是很多天——W3 记录里 /state 从来没有过这个工件，而
# gate.sh 照报"GATE PASSED（4 项）"，看不出深档根本没跑。所以：能自动落位就落位，
# 落不了位就判**失败**（判据跑不起来本身就是失败，不是"跳过"）。
SUITE_SRC="$HOME/dsv41-flash-dgxsparks/bench/gates_suite.py"
# ★2026-09-18 布局自适应：/state 的宿主真身有两个时代——state-tp4/（09-17 前）与
# state/（S5/SD-1 会话起）。两个目录都落位，以 docker 实际挂载为准。
if [[ -f "$SUITE_SRC" ]] && ! docker exec dsv41-head test -f /state/gates_suite.py 2>/dev/null; then
  _ST_MNT=$(docker inspect dsv41-head --format '{{range .Mounts}}{{.Source}} {{.Destination}}{{"\n"}}{{end}}' 2>/dev/null | awk '$2=="/state"{print $1}')
  for _d in "$HOME/dsv41-flash-dgxsparks/state-tp4" "$HOME/dsv41-flash-dgxsparks/state" "${_ST_MNT:-}"; do
    [[ -n "$_d" && -d "$_d" ]] && cp "$SUITE_SRC" "$_d/gates_suite.py" 2>/dev/null
  done
  echo "[*] 已把 gates_suite.py 落位（state-tp4/ + state/；容器实际挂载=${_ST_MNT:-?}）"
fi
if docker exec dsv41-head test -f /state/gates_suite.py 2>/dev/null; then
  out=$(docker exec -w /state dsv41-head python3 /state/gates_suite.py --corruption --code --key "$KEY" 2>&1)
  if echo "$out" | grep -q 'U+FFFD=0' && ! echo "$out" | grep -q 'FAIL'; then
    ok "corruption probe 0/0/0"
  else
    bad "corruption 异常: $(echo "$out" | grep -m1 'U+FFFD' || echo 无输出)"
  fi
  if echo "$out" | grep -q 'code-gate total: 12/12'; then
    ok "code-gate 12/12"
  else
    bad "code-gate: $(echo "$out" | grep -m1 'code-gate total' || echo 未完成)"
  fi
else
  bad "gates_suite 不在容器内（深档 corruption/code-gate 跑不了；判据缺失≠通过）"
fi

# ── 全档：终止性 + needle 梯度 ─────────────────────────────────────────────
if [[ "$FULL" -eq 1 ]]; then
  out=$(docker exec -w /state dsv41-head python3 /state/gates_suite.py --termination --key "$KEY" 2>&1)
  if [[ "$(echo "$out" | grep -c '18/18 stop')" -eq 2 ]]; then ok "终止性 18/18 · 18/18"
  else bad "终止性: $(echo "$out" | tr '\n' ' ')"; fi

  out=$(docker exec -w /state dsv41-head python3 /state/gates_suite.py --needle --key "$KEY" 2>&1)
  # 本栈 max_model_len=262144 ⇒ 470K 档**结构性**超出上下文，预期报 HTTP 400（W3 已记录）。
  # 所以判据是"≥2 档 PASS"，而不是"3 档全 PASS"：后者是个永远不可能满足的条件，会把每次
  # 全档门都判失败，训练人忽略门。同时两个方向都留着：3 档全 PASS 也算过（将来 ctx 变大时
  # 成立），而 30K/229K 任一失败、或 470K 既没 PASS 也没报 400，都判失败。
  n_pass=$(printf '%s' "$out" | grep -c ' PASS')
  if [[ "$n_pass" -ge 3 ]]; then
    ok "needle 30K/229K/470K 全 PASS"
  elif [[ "$n_pass" -eq 2 ]] && printf '%s' "$out" | grep -q 'HTTP Error 400'; then
    ok "needle 30K/229K 全 PASS（470K 档 HTTP 400 = 超本栈 ctx 262144，该档不适用）"
  else
    bad "needle: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-160)"
  fi
fi

# ── 汇总 ──────────────────────────────────────────────────────────────────
echo
if [[ "$JSON" -eq 1 ]]; then
  printf '{"pass":%d,"fail":%d,"full":%s,"results":[' "$pass" "$fail" "$([[ $FULL -eq 1 ]] && echo true || echo false)"
  for i in "${!results[@]}"; do
    [[ $i -gt 0 ]] && printf ','
    printf '"%s"' "${results[$i]}"
  done
  printf ']}\n'
fi
if [[ "$fail" -eq 0 ]]; then
  echo "[+] GATE PASSED（$pass 项）—— 引擎可信"
  exit 0
else
  echo "[x] GATE FAILED（$pass 过 / $fail 败）—— 不要交付"
  exit 1
fi

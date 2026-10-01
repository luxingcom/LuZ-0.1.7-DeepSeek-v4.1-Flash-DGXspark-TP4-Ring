#!/usr/bin/env bash
# start.sh — DeepSeek-V4.1-Flash launcher for DGX Spark (GB10 / SM121)
#
# WHICH PROFILE THIS REPO SHIPS — 4x DGX Spark, TP4 / EP2:
#   entry point      ENV_FILE=.env.tp4 ./start.sh serve    (or ./start-tp4.sh serve)
#   config template  .env.tp4.example — the live .env.tp4 stays on the deployment
#                    host, because it holds the API key
#   Every published figure in this repository comes from this profile.
#
# The 3-Spark text below describes start.sh's **legacy dev profile** (.env, TP=3).
# That code path still exists — one checkout can drive either fleet, and the
# profile-selection block further down (search for "Profiles:") explains how the
# two are chosen — but its IPs (10.0.0.1-3) and usernames (mia / zurih) belong to
# an internal dev triangle, not to this repository. Same engine, same flags,
# different fleet. Renaming those hosts in your own .env is expected.
#
# Upstream: https://github.com/0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000
#   4× RTX PRO 6000 Blackwell, TP4/EP4, native weights, NVMe Engram, DSpark.
# This wrapper remaps that stack onto the 3-Spark triangle:
#   spark1 10.0.0.1 (mia)  — rank 0, API :8888
#   spark2 10.0.0.2 (zurih)
#   spark3 10.0.0.3 (zurih)
#   TP=3 EP=3, RoCE NCCL, Engram on NVMe. spark2/spark3 read spark1 weights
#   over NFSv4 on ConnectX (vllm-fn-nfs / dsv41-nfs) — no local 476 GiB copy.
#
# Usage:
#   ./start.sh                 doctor → image → share → serve (default)
#   ./start.sh doctor          connectivity + GPU + checkpoint report
#   ./start.sh pull            pull lmsysorg/sglang:dev-dsv41 on all 3 nodes
#   ./start.sh build           docker build the Engram overlay image everywhere
#   ./start.sh download        hf download the pinned V4.1-Flash revision
#   ./start.sh share           export spark1 checkpoint; NFS volumes on spark2/3
#   ./start.sh mount           alias for share (legacy)
#   ./start.sh serve           launch workers then head
#   ./start.sh stop            tear down all 3 ranks
#   ./start.sh status          containers + API
#   ./start.sh logs [N]        tail head boot logs
#   ./start.sh logs worker<N> [lines]   (worker1, worker2, ...)
#   ./start.sh smoke           arithmetic (+ optional tools/vision)
#   ./start.sh ncclcheck       verify NCCL came up ring-only (patch + algo matrix)
#   ./start.sh gate [--full]   is the engine *trustworthy*, not merely Up
#
set -euo pipefail

print_usage() {
  # Print this script's own header comment block.
  #
  # Was `sed -n '2,28p' "$0"` -- hard-coded line numbers that silently truncated
  # the moment the header grew (by 13 lines, 2026-09-24: the usage list, which
  # starts at line 26, fell outside the range). The first fix used `2,/^$/` and
  # was *also* wrong: the header ends with a bare `#`, not a blank line, so the
  # range ran on and swallowed the `set -euo pipefail` that follows it.
  # "Every consecutive comment line from line 2" is the property we actually mean.
  awk 'NR>1 && /^#/ { print; next } NR>1 { exit }' "$0" | tr -d '#'
}

usage() { print_usage; }

# `help` must be reachable with zero side effects, so it is handled before
# anything else runs. It used to fall through the whole ENV_FILE bootstrap:
# it created .env in your working tree, ran the top-level key lint, and could
# die on the chunk-tier gate before printing a single line -- while the
# "unknown command" error further down tells people to run exactly this.
# (Reported from a clean-clone walkthrough, 2026-09-24.)
case "${1:-}" in
  -h|--help|help)
    print_usage; exit 0 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Profiles: start.sh reads .env (3 Sparks, TP3); start-tp4.sh points ENV_FILE at
# .env.tp4 (4 Sparks, TP4) and gives that profile its own state/log dirs.
# ⚠ 2026-09-21 (batch 7 lesson): calling start.sh WITHOUT ENV_FILE=.env.tp4
# silently sources the stale dev .env (CHUNKED_PREFILL_SIZE=1024 there vs the
# validated 4096/8192 tiers) — the tier gate catches it late. Warn loudly here.
if [[ -z "${ENV_FILE:-}" && -f "$ROOT/.env.tp4" && -f "$ROOT/.env" ]]; then
  _tp4_chunk=$(grep -E '^CHUNKED_PREFILL_SIZE=' "$ROOT/.env.tp4" | tail -1 | cut -d= -f2)
  _dev_chunk=$(grep -E '^CHUNKED_PREFILL_SIZE=' "$ROOT/.env" | tail -1 | cut -d= -f2)
  if [[ -n "${_tp4_chunk:-}" && "${_dev_chunk:-}" != "$_tp4_chunk" ]]; then
    echo "[warn] ENV_FILE 未设置：默认使用 .env（CHUNKED_PREFILL_SIZE=${_dev_chunk:-?}），" >&2
    echo "[warn] 与 .env.tp4（${_tp4_chunk}）分叉。生产四机形态请用：ENV_FILE=.env.tp4 ./start.sh …" >&2
  fi
fi
# 审计 P2 修：stop.sh 无 ENV_FILE 时优先 .env.tp4，start 却默认 .env——不对称陷阱
# （裸 ./start.sh serve 会静默拿 3 机 dev 拓扑）。有 .env.tp4 即默认生产形态。
if [[ -z "${ENV_FILE:-}" && -f "$ROOT/.env.tp4" ]]; then
  ENV_FILE="$ROOT/.env.tp4"
  echo "[dsv41] ENV_FILE 未指定：检测到 .env.tp4，默认按生产四机形态加载（显式指定可覆盖）" >&2
fi
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
ENV_EXAMPLE="${ENV_EXAMPLE:-$ROOT/.env.example}"
if [[ ! -f "$ENV_FILE" ]]; then
  [[ -f "$ENV_EXAMPLE" ]] || { echo "missing $(basename "$ENV_EXAMPLE")" >&2; exit 1; }
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  echo "[dsv41] wrote $(basename "$ENV_FILE") from $(basename "$ENV_EXAMPLE") — edit IPs if needed"
fi
set -a
# ── 遮蔽快照（审计 P1 系统性修复，2026-09-21）──────────────────────────────
# source 会覆盖调用方已导出的同名变量。EXTRA_SGLANG_ARGS 曾是个例修复（_APPEND 口），
# 但 IMAGE/API_KEY/EXTRA_DOCKER_ENV/CHUNKED_PREFILL_SIZE/SKIP_* 同被静默吞——且
# 全部预检会在「被吞后的值」上自洽通过、全绿放行（版本切换 A/B 作废/鉴权轮换失效
# 都无从察觉）。此处先抓快照，source 后比对；被吞即拒绝起栈并给出正确入口。
# 注：HOST 刻意不入观察名单（shell 环境可能自设，误伤面大于价值）。
_SHADOW_WATCH=(IMAGE API_KEY EXTRA_DOCKER_ENV EXTRA_SGLANG_ARGS CHUNKED_PREFILL_SIZE SKIP_SMOKE SKIP_PREPARE NFS_SHARE)
declare -A _CALLER_SNAPSHOT=()
for _k in "${_SHADOW_WATCH[@]}"; do
  _v="${!_k:-}"
  [[ -n "$_v" ]] && _CALLER_SNAPSHOT[$_k]="$_v"
done
unset _k _v
# shellcheck disable=SC1091
source "$ENV_FILE"
set +a
for _k in "${!_CALLER_SNAPSHOT[@]}"; do
  if [[ "${_k:+x}" && "${!_k}" != "${_CALLER_SNAPSHOT[$_k]}" ]]; then
    {
      echo "[x] 环境变量遮蔽拦截：调用方传了 $_k，但 $ENV_FILE 也定义了同名键，source 已把你的传值覆盖为 env 文件值。"
      echo "    你的传值不会生效且无预检能发现——这正是 09-21 SPF 臂实锤的病类（EXTRA_SGLANG_ARGS 传值被吞、引擎仍 fcfs）。"
      echo "    正确入口：①一次性追加引擎参数 → EXTRA_SGLANG_ARGS_APPEND='...'；②版本/整组实验 → cp $ENV_FILE ${ENV_FILE}-xxx 改行后 ENV_FILE=${ENV_FILE}-xxx；③生产变更 → 直接改 $ENV_FILE。"
    } >&2
    exit 1
  fi
done
unset _k
# 一次性实验参数追加口（2026-09-21 SPF 臂白盒实证）：.env.tp4 自身定义
# EXTRA_SGLANG_ARGS（生产集），上面 source 会覆盖调用方在 shell 传入的同名
# 变量——直接传 EXTRA_SGLANG_ARGS 只会静默丢失（首战 SPF 靴实锤 schedule_policy
# 仍 fcfs）。走 _APPEND：追加到生产集之后（argparse 后者胜）；本名不被 env 文件
# 定义故穿过 source 存活，image_arg_preflight 在合并值上校验。
if [[ -n "${EXTRA_SGLANG_ARGS_APPEND:-}" ]]; then
  EXTRA_SGLANG_ARGS="${EXTRA_SGLANG_ARGS:-} ${EXTRA_SGLANG_ARGS_APPEND}"
  export EXTRA_SGLANG_ARGS
fi

HEAD_IP="${HEAD_IP:-10.0.0.1}"
# Workers: WORKER_IPS="10.0.0.2 10.0.0.3 ..." (space or comma separated) and
# optionally WORKER_HOSTS="spark2 spark3 ..." (ssh names); the legacy
# WORKER1_IP/WORKER2_IP/WORKER1_HOST/WORKER2_HOST pairs still work for 3 nodes.
_list() { tr ',' ' ' <<<"$1"; }
if [[ -n "${WORKER_IPS:-}" ]]; then
  read -r -a WORKER_IPS <<<"$(_list "$WORKER_IPS")"
else
  WORKER_IPS=("${WORKER1_IP:-10.0.0.2}" "${WORKER2_IP:-10.0.0.3}")
fi
if [[ -n "${WORKER_HOSTS:-}" ]]; then
  read -r -a WORKER_HOSTS <<<"$(_list "$WORKER_HOSTS")"
else
  WORKER_HOSTS=()
  for _i in "${!WORKER_IPS[@]}"; do
    _v="WORKER$((_i + 1))_HOST"
    WORKER_HOSTS+=("${!_v:-${WORKER_IPS[$_i]}}")
  done
fi
[[ ${#WORKER_HOSTS[@]} -eq ${#WORKER_IPS[@]} ]] || { echo "WORKER_HOSTS and WORKER_IPS differ in length" >&2; exit 1; }
WORKER1_IP="${WORKER_IPS[0]}"; WORKER2_IP="${WORKER_IPS[1]:-}"   # legacy names, still read by files/nfs-share.sh
WORKER_USER="${WORKER_USER:-zurih}"
SSH_IDENTITY="${SSH_IDENTITY:-$HOME/.ssh/id_ed25519_shared}"
FABRIC_IFACE="${FABRIC_IFACE:-enp1s0f1np1}"
GLOO_SOCKET_IFNAME="${GLOO_SOCKET_IFNAME:-enP7s7}"
NCCL_SOCKET_IFNAME="${NCCL_SOCKET_IFNAME:-enP7s7}"
IB_HCA="${IB_HCA:-rocep1s0f0,rocep1s0f1}"
NCCL_NET="${NCCL_NET:-IB}"
NCCL_IB_DISABLE="${NCCL_IB_DISABLE:-0}"
NCCL_P2P_DISABLE="${NCCL_P2P_DISABLE:-1}"
NCCL_SHM_DISABLE="${NCCL_SHM_DISABLE:-1}"
NCCL_DEBUG="${NCCL_DEBUG:-WARN}"
NCCL_HOST_DIR="${NCCL_HOST_DIR:-$HOME/nccl-2.30.7}"
# 仅开发模式（SGLANG_CODE_MOUNTS=1）用：生产模式这四个挂载点全部来自镜像
# （/opt/nccl-ringonly + /opt/libncclpin.so 由 build_optimized_image.sh 烘入）。
NCCL_CONTAINER_DIR="${NCCL_CONTAINER_DIR:-/nccl}"

MODEL_DIR="${MODEL_DIR:-$HOME/NewModels/DeepSeek-V4.1-Flash}"
COMMON_MODEL="${COMMON_MODEL:-/var/tmp/DeepSeek-V4.1-Flash}"
HF_REPO="${HF_REPO:-deepseek-ai/DeepSeek-V4.1-Flash}"
HF_REVISION="${HF_REVISION:-fb2764a5cf321eaa5070ca8f9e892818f477c16d}"
EXPECTED_SHARDS="${EXPECTED_SHARDS:-48}"

BASE_IMAGE="${BASE_IMAGE:-lmsysorg/sglang:dev-dsv41}"
# 默认值必须**跟随生产 pin**（`.env.tp4` 的 IMAGE + `guards.conf` 的 sglang-image envpin）。
# 2026-09-23 修：旧默认长期滞后（0.2.4 → 0.2.7 递进；0.2.4 为 125 层、落后三代），
# 于是任何「忘了带 ENV_FILE」的起栈会静默拿到旧世代镜像 —— 而两处判据查的都是
# .env.tp4，默认值不在任何判据覆盖内，所以这种不一致**没有任何告警面**。
IMAGE="${IMAGE:-dsv41-sglang-optimized:0.2.9-ep1q2-fin2}"
HEAD_CTN="${HEAD_CTN:-dsv41-head}"
WORKER_CTN="${WORKER_CTN:-dsv41-worker}"
WORKER_DIR="${WORKER_DIR:-/home/${WORKER_USER}/dsv41-flash-dgxsparks}"

NNODES="${NNODES:-$(( ${#WORKER_IPS[@]} + 1 ))}"
[[ "$NNODES" -eq $(( ${#WORKER_IPS[@]} + 1 )) ]] || { echo "NNODES=$NNODES but ${#WORKER_IPS[@]} workers are configured" >&2; exit 1; }
TP_SIZE="${TP_SIZE:-3}"
EP_SIZE="${EP_SIZE:-$TP_SIZE}"
DIST_PORT="${DIST_PORT:-20000}"
PORT="${PORT:-8888}"
OFFLOAD_MODE="${OFFLOAD_MODE:-nvme}"
# 默认取 1 而不是 4，与 .env.tp4 / .env.tp4.example / 镜像烘焙值（DSV41_CACHE_GIB=1）一致：
# 这条是**已批准值**（R2 决策：缓存 1GiB 下命中率已 99.1%，而 4GiB 会把 900K 单 prompt 打成
# 失败——地板 3.53→1.50GB）。留一个 4 的默认值等于给"不读台账的人"备了个相反的旋钮。
DSV41_CACHE_GIB="${DSV41_CACHE_GIB:-1}"
# Engram misses are serviced by a pool: the GB10 NVMe does ~3.5k IOPS at QD=1 and
# ~112k at QD=64, and the callback blocks the compute stream the whole time.
DSV41_IO_THREADS="${DSV41_IO_THREADS:-96}"
DSV41_RESIDENT_SCALES="${DSV41_RESIDENT_SCALES:-0}"
DSV41_CACHE_WAYS="${DSV41_CACHE_WAYS:-4}"
DSV41_STATS_SECONDS="${DSV41_STATS_SECONDS:-60}"
# DSpark's ragged-verify scheduler is inert without a profiled SPS cost table.
# Build one against a running server with:
#   python -m sglang.benchmark.dspark_sps_profiler
# and drop it at $STATE_DIR/dspark_sps.json; every rank needs its own copy.
DSPARK_SPS_TABLE="${DSPARK_SPS_TABLE:-/state/dspark_sps.json}"
DSPARK_STS_TABLE="${DSPARK_STS_TABLE:-/state/dspark_sts.json}"
# Node-local repacked Engram shards (see scripts/pack_engram.py). ~68 GiB/node.
ENGRAM_DIR="${ENGRAM_DIR:-$HOME/dsv41-engram}"
WORKER_ENGRAM_DIR="${WORKER_ENGRAM_DIR:-$WORKER_DIR/engram}"
DSV41_PACKED_DIR="${DSV41_PACKED_DIR:-/engram}"
CONTEXT_LENGTH="${CONTEXT_LENGTH:-409600}"
MEM_FRACTION_STATIC="${MEM_FRACTION_STATIC:-0.95}"
# Rank 0 also carries the HTTP server, tokenizer and detokenizer (~1.3 GiB the
# workers never pay) and serves the checkpoint over NFS, so it runs out of host
# RAM first -- and on GB10 host RAM is GPU memory. Give it its own budget.
HEAD_MEM_FRACTION_STATIC="${HEAD_MEM_FRACTION_STATIC:-$MEM_FRACTION_STATIC}"
MAX_RUNNING_REQUESTS="${MAX_RUNNING_REQUESTS:-4}"
CHUNKED_PREFILL_SIZE="${CHUNKED_PREFILL_SIZE:-2048}"

# P3⑤ 2026-09-19：顶层 NCCL_ 键 lint（客户坑 9：白名单外的顶层 NCCL_* 不透传，静默陷阱）
# 2026-09-21 白盒修正：旧 pattern *" $_k ") 是后缀匹配（只有最后一个词条能命中）⇒
# 12 个在单内的键也误警告，警告疲劳后真泄漏反被忽视。改包含匹配 *" $_k "*。
for _k in $(compgen -A variable NCCL_ 2>/dev/null || true); do
  # NCCL_IB_GID_INDEX_FORCE 白盒补记：它是 start.sh 自用的宿主侧键（GID 预检/注入
  # -e NCCL_IB_GID_INDEX=$gid 时消费，见 fabric_gid_preflight 与 cmd_serve），并非
  # 靠透传进容器——所以也入白名单，否则每次启动都假 warn（2026-09-21 T7 白盒抓出）。
  case " NCCL_HOST_DIR NCCL_ALGO NCCL_BUFFSIZE NCCL_CROSS_NIC NCCL_CUMEM_HOST_ENABLE NCCL_DEBUG NCCL_DEBUG_SUBSYS NCCL_IB_DISABLE NCCL_IB_GID_INDEX NCCL_IB_GID_INDEX_FORCE NCCL_IB_HCA NCCL_IB_MERGE_NICS NCCL_IB_RETRY_CNT NCCL_IB_SUBNET_AWARE_ROUTING NCCL_IB_TIMEOUT NCCL_IB_TOS NCCL_IGNORE_CPU_AFFINITY NCCL_MAX_NCHANNELS NCCL_MIN_NCHANNELS NCCL_NET NCCL_NET_PLUGIN NCCL_PROTO NCCL_SET_THREAD_NAME NCCL_SHM_DISABLE NCCL_SOCKET_IFNAME NCCL_TUNER_THRESHOLD " in
    *" $_k "*) ;;
    *) echo "[warn] 顶层 $_k 不在 start.sh 白名单，不会透传到容器——请写入 EXTRA_DOCKER_ENV（客户坑 9）" ;;
  esac
done

# 2026-09-22（同族漏配，600K 首启前白盒抓出）：上面 lint 只覆盖 NCCL_*，但**引擎侧
# 门控键**同样只有 (a) EXTRA_DOCKER_ENV 词条 或 (b) 本脚本硬编码 -e 才进容器——写成
# 顶层变量一样静默无效。实锤：.env.tp4-600k 曾把 DSV41_IDLE_RELEASE=1 写成顶层变量
# ⇒ 容器 os.environ 读不到 ⇒ FIX-B idle-release 静默关闭（不拦住的话 600K 首启即带
# 缺陷跑，且所有预检都会在「以为开着」的假设上全绿）。策展清单=引擎/overlay 从容器
# env 读的键；命中即告警不 die（留应急起栈余地，但每次启动都出声）。新增引擎门控键
# 时请同步此表。
_ENGINE_GATE_KEYS=(
  DSV41_IDLE_RELEASE DSV41_IDLE_RELEASE_MIN_S DSV41_IDLE_RELEASE_MIN_BYTES
  DSV41_SCHED_SNAPSHOT DSV41_SCHED_MEM_HISTORY
  DSV41_DENSE_INDEXER_LOGITS_BUDGET_BYTES DSV41_PREFILL_SHARE_TOKENS DSV41_PREFILL_EMPTY_CACHE_TOKENS
  SGLANG_DSV4_PAGETABLE_PAGES_GRID SGLANG_DSV4_INDEXER_LOGITS_BUDGET_MB
  DSV41_MOE_B12X DSV41_MOE_B12X_CAPS DSV41_MOE_B12X_QUANT DSV41_SKIP_NONFINAL_DECODER
  DSV41_SHARED_PAD_K DSV41_TP_PAD SGLANG_DSV4_KV_LAYOUT SGLANG_RAGGED_VERIFY_MODE
  SGLANG_ENABLE_HEALTH_ENDPOINT_GENERATION SGLANG_QW3_DSPARK_LAUNCH_PARAMS
)
# 本脚本硬编码 -e 转发的键（见 cmd_serve 的 -e 列表）：白名单，命中不告警。
_HOST_FORWARDED_KEYS=(
  DSV41_CACHE_GIB DSV41_IO_THREADS DSV41_RESIDENT_SCALES DSV41_CACHE_WAYS
  DSV41_STATS_SECONDS DSV41_PACKED_DIR DSV41_MXFP8_BACKEND DSV41_TP_PAD
)
for _k in "${_ENGINE_GATE_KEYS[@]}"; do
  _v="${!_k:-}"
  [[ -z "$_v" ]] && continue
  [[ " ${_HOST_FORWARDED_KEYS[*]} " == *" $_k "* ]] && continue
  grep -qE "(^| )$_k=" <<<"${EXTRA_DOCKER_ENV:-}" && continue
  echo "[warn] 顶层 $_k=$_v 不会透传到容器（引擎 os.environ 读不到 ⇒ 该门静默失效）——请写入 EXTRA_DOCKER_ENV（客户坑 9 同族）" >&2
done
unset _k _v

# 引擎门控键「意图==实效」的后半段：上面的 lint 拦「顶层漏配」，这里拦「docker 层
# 吞 token / 拼写漂移」——起栈后把 EXTRA_DOCKER_ENV 里属于策展清单的 token 逐个与
# 容器实际 env 比对。head 与 worker 走同一份期望表、同一段比较逻辑（只有一侧被查
# 是 split-brain 的老坑）。同键后者胜=按 docker 语义去重，避免「EXTRA 里同键两次」
# 造成假失败。
engine_env_expect_tokens() {  # 输出最终生效的 KEY=VALUE 逐行（仅策展清单内）
  local _ed _k
  local -A _last=()
  local -a _order=()
  for _ed in ${EXTRA_DOCKER_ENV:-}; do
    case "$_ed" in *=*) _k="${_ed%%=*}" ;; *) continue ;; esac
    [[ " ${_ENGINE_GATE_KEYS[*]} " == *" $_k "* ]] || continue
    [[ -n "${_last[$_k]:-}" ]] || _order+=("$_k")
    _last[$_k]="$_ed"
  done
  for _k in "${_order[@]}"; do echo "${_last[$_k]}"; done
}
engine_env_assert() {  # engine_env_assert <显示名> <容器env整串>；缺 token 即拒（返回 1）
  local _label="$1" _env="$2" _tok _miss=""
  # remote_on 走 PTY，回传 stdout 是 CRLF（2026-09-22 实测：worker 侧每行尾带 \r，
  # 于是 grep -qxF 对全部 token 都 miss ⇒ 断言把真起栈拦下，还报"全部漏配"的假诊断；
  # 当时用 python text=True 复核反而"看不到 \r"——那是它替我归一了换行）。
  # 先归一化再比：传输形态不是判据，只有内容才是。
  _env="${_env//$'\r'/}"
  while read -r _tok; do
    [[ -z "$_tok" ]] && continue
    grep -qxF -- "$_tok" <<<"$_env" || _miss="$_miss $_tok"
  done < <(engine_env_expect_tokens)
  [[ -z "$_miss" ]] && return 0
  echo "[x] $_label 容器 env 与 EXTRA_DOCKER_ENV 不一致（意图≠实效，缺:$_miss）" >&2
  if [[ -z "$_env" ]]; then
    echo "    env 串为空 ⇒ 先排除 inspect/ssh 本身失败（非漏配）；重跑一次即可分辨。" >&2
  else
    echo "    env 串非空 ⇒ 真漏配：docker 吞 token 或 EXTRA_DOCKER_ENV 拼写漂移。" >&2
  fi
  return 1
}

# ── chunk 三档切换（2026-09-18）：用户改 .env 的 CHUNKED_PREFILL_SIZE 一行即可切换 ──────────
# 已验证档位（GPU 密扫零失败 + 可起栈）：4096（生产基线）/ 6144（W5 密扫 539 值）/ 8192（本日 681 值）。
# 关键约束：adapter 的 _cap_for() 对 m>梯级上限抛 RuntimeError ⇒ chunk 每上一档，MoE 梯级必须
# 同步加同值 rung（W5 判例）。这里自动完成推导：若 EXTRA_DOCKER_ENV 里的 DSV41_MOE_B12X_CAPS
# 不含 CHUNKED_PREFILL_SIZE，则把该值追加为最后一档 —— 切换时只改一行，不会漏梯级。
_chunk_ok=0
for _v in 2048 4096 6144 8192; do [[ "$CHUNKED_PREFILL_SIZE" = "$_v" ]] && _chunk_ok=1; done
if [[ "$_chunk_ok" != 1 ]]; then
  echo "[die] CHUNKED_PREFILL_SIZE=$CHUNKED_PREFILL_SIZE 不在已验证档位 {2048,4096,6144,8192}。先跑 moe 梯级密扫再放行（见 ~/chunk8192-window-20260918/RUNBOOK.md §2）" >&2
  exit 1
fi
if [[ -n "${EXTRA_DOCKER_ENV:-}" ]] && grep -q "DSV41_MOE_B12X_CAPS=" <<<"$EXTRA_DOCKER_ENV"; then
  _caps_val=$(grep -oE 'DSV41_MOE_B12X_CAPS=[0-9,]+' <<<"$EXTRA_DOCKER_ENV" | head -1 | cut -d= -f2)
  if [[ "$_caps_val" != *",$CHUNKED_PREFILL_SIZE" && "$_caps_val" != "$CHUNKED_PREFILL_SIZE" && "$_caps_val" != *" $CHUNKED_PREFILL_SIZE"* ]]; then
    case ",$_caps_val," in
      *",$CHUNKED_PREFILL_SIZE,"*) : ;;  # 已含该档
      *)
        _caps_new=$(echo "$_caps_val,$CHUNKED_PREFILL_SIZE" | tr ',' '\n' | sort -n | uniq | paste -sd,)
        EXTRA_DOCKER_ENV=$(sed "s/DSV41_MOE_B12X_CAPS=$_caps_val/DSV41_MOE_B12X_CAPS=$_caps_new/" <<<"$EXTRA_DOCKER_ENV")
        echo "[info] chunk 切换联动：DSV41_MOE_B12X_CAPS 自动补 $_caps_val → $_caps_new（_cap_for 按表序首匹配，故追加后重排防误用大桶）"
        ;;
    esac
  fi
fi
MAX_TOTAL_TOKENS="${MAX_TOTAL_TOKENS:-320000}"

# --- S5 governance pin (2026-09-17) ---
# The KV pool must cover MAX_RUNNING_REQUESTS x CONTEXT_LENGTH. If not, the
# shortfall is silent (requests just retract more often). Fail closed instead.
if [ -n "${MAX_RUNNING_REQUESTS:-}" ] && [ -n "${CONTEXT_LENGTH:-}" ] && [ -n "${MAX_TOTAL_TOKENS:-}" ]; then
  _need=$(( MAX_RUNNING_REQUESTS * CONTEXT_LENGTH ))
  if [ "$_need" -gt "$MAX_TOTAL_TOKENS" ]; then
    echo "[start.sh] PIN-FAIL: MAX_TOTAL_TOKENS=$MAX_TOTAL_TOKENS < MAX_RUNNING_REQUESTS($MAX_RUNNING_REQUESTS) x CONTEXT_LENGTH($CONTEXT_LENGTH) = $_need" >&2
    exit 1
  fi
  echo "[start.sh] pin-ok: pool $MAX_TOTAL_TOKENS >= concurrency need $_need"
fi
# --- end S5 pin ---
SPEC_ALGO="${SPEC_ALGO:-DSPARK}"
DSPARK_BLOCK_SIZE="${DSPARK_BLOCK_SIZE:-5}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-deepseek-v4.1-flash}"
SKIP_PREPARE="${SKIP_PREPARE:-1}"
SKIP_VERIFY="${SKIP_VERIFY:-1}"
SKIP_SMOKE="${SKIP_SMOKE:-0}"
SMOKE_QUICK="${SMOKE_QUICK:-1}"
API_KEY="${API_KEY:-}"
STATE_DIR="${STATE_DIR:-$ROOT/state}"
LOG_DIR="${LOG_DIR:-$ROOT/logs}"
SERVE_LOG="${SERVE_LOG:-$LOG_DIR/dsv41.log}"
REMOTE_PY="$ROOT/scripts/remote.py"
NFS_VOLUME="${NFS_VOLUME:-dsv41-weights}"
NFS_SHARE="${NFS_SHARE:-1}"
# Ring adaptation (internal mirror dsv41/): local weights on every node — skip the
# NFS export/mount machinery entirely (WEIGHTS_MODE=local). WORKER_MODEL_DIR
# must hold a flat checkpoint (config.json + 48 shards) on each worker.
WEIGHTS_MODE="${WEIGHTS_MODE:-nfs}"
WORKER_MODEL_DIR="${WORKER_MODEL_DIR:-/home/spark/models/DeepSeek-V4.1-Flash}"

_abs() { readlink -f "$1" 2>/dev/null || echo "$1"; }
MODEL_DIR="$(_abs "$MODEL_DIR")"
SSH_IDENTITY="$(_abs "$SSH_IDENTITY")"
NCCL_HOST_DIR="$(_abs "$NCCL_HOST_DIR")"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'
info() { echo "${GREEN}[+]${NC} $*"; }
warn() { echo "${YELLOW}[!]${NC} $*"; }
err()  { echo "${RED}[x]${NC} $*" >&2; }
die()  { err "$@"; exit 1; }

mkdir -p "$LOG_DIR" "$STATE_DIR"

# shellcheck source=files/nfs-share.sh
source "$ROOT/files/nfs-share.sh"

remote_on() {
  local host="$1"; shift
  local to_args=()
  if [[ "${1:-}" == "--timeout" ]]; then
    to_args=(--timeout "$2"); shift 2
  elif [[ -n "${REMOTE_TIMEOUT:-}" ]]; then
    to_args=(--timeout "$REMOTE_TIMEOUT")
  fi
  python3 "$REMOTE_PY" --env-file "$ENV_FILE" \
    --host "$host" --user "$WORKER_USER" \
    --identity "$SSH_IDENTITY" \
    "${to_args[@]}" \
    "bash -lc $(printf '%q' "$*")"
}
remote_ok_on() { remote_on "$@" >/dev/null 2>&1; }

ssh_rsync_e() {
  printf 'ssh -i %q -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new' \
    "$SSH_IDENTITY"
}

ensure_ssh_keys() {
  local pub host
  pub=$(cat "${SSH_IDENTITY}.pub" 2>/dev/null || true)
  [[ -n "$pub" ]] || die "Missing ${SSH_IDENTITY}.pub"
  for host in "${WORKER_HOSTS[@]}"; do
    remote_on "$host" "mkdir -p ~/.ssh && chmod 700 ~/.ssh
      touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
      grep -qxF '$pub' ~/.ssh/authorized_keys || echo '$pub' >> ~/.ssh/authorized_keys"
  done
}

model_src() {
  local src
  if [[ -L "$COMMON_MODEL" ]]; then
    src="$(readlink -f "$COMMON_MODEL")"
  elif [[ -d "$COMMON_MODEL" ]]; then
    src="$COMMON_MODEL"
  else
    src="$MODEL_DIR"
  fi
  # Ring adaptation: never silently return a path with no checkpoint. A missing
  # dir here made `pack` mount an empty tree, write zero shards and still
  # report success (workers stayed on the 2-read unpacked Engram path).
  [[ -f "$src/config.json" ]] || die "no checkpoint at $src (config.json missing) — set MODEL_DIR"
  echo "$src"
}

api_key() {
  # Empty / dummy / off → no --api-key (Spark 1 / Pi probe /v1/models without auth).
  local v="${API_KEY:-}"
  case "${v,,}" in
    ''|none|off|dummy|0) echo "" ;;
    *) echo "$v" ;;
  esac
}

gid_index_local() {
  local ip="$1" hex hca g i
  hex=$(printf '%02x%02x:%02x%02x' $(echo "$ip" | tr . ' '))
  local IFS=','
  for hca in $IB_HCA; do
    hca="${hca// /}"
    [[ -d /sys/class/infiniband/"$hca" ]] || continue
    for g in /sys/class/infiniband/"$hca"/ports/1/gids/*; do
      i=${g##*/}
      [[ "$(cat /sys/class/infiniband/"$hca"/ports/1/gid_attrs/types/"$i" 2>/dev/null)" == "RoCE v2" ]] || continue
      case "$(cat "$g")" in *ffff:"$hex") echo "$i"; return 0;; esac
    done
  done
  return 1
}

# ── 2026-09-21 断电事故防线：fabric GID 洞预检 ──────────────────────────────
# 病：断电重启后接口初始化乱序 ⇒ RoCE GID 表出洞（v2-IPv4 落到 idx4，idx3 空）。
# NCCL_IB_GID_INDEX_FORCE=3 时 NCCL 在洞口 modify_qp RTR 必挂（errno 61）——
# 表现=容器起 2-3 分钟后 NCCL bootstrap 崩，自愈单元空转 20 次撞 start-limit。
# 修法=对洞口做 IP 环回（ip addr del/add 同地址）逼 rdma_cm 重建紧凑 GID 表。
# 详见 ~/w6-kit/FABRIC-GID-REPAIR-RUNBOOK.md。此函数把 13 分钟崩环变 5 秒定向 abort。
_gid_holes_local() {  # 打印洞口 HCA 名（idx 无 RoCE v2 GID 即洞）
  local idx hca t; idx="${NCCL_IB_GID_INDEX_FORCE:-${NCCL_IB_GID_INDEX:-3}}"
  local IFS=','
  for hca in $IB_HCA; do
    hca="${hca// /}"
    [[ -d /sys/class/infiniband/$hca ]] || continue
    t=$(cat /sys/class/infiniband/$hca/ports/1/gid_attrs/types/$idx 2>/dev/null)
    [[ "$t" == "RoCE v2" ]] || echo "$hca"
  done
}

# ── 2026-09-21 版本切换防线（三路子代理白盒审计落地）───────────────────────
# 雷 1：EXTRA_SGLANG_ARGS 带新镜像独有的 flag/choice（如 --schedule-policy
#   shortest-prefill-first）配到旧镜像 ⇒ argparse 崩在 3 分钟容器引导后。
#   这里在起栈前用镜像内 server_args.py 做存在性预检（5 秒死胜过 3 分钟死）。
# 雷 2：换 IMAGE 起栈后没人知道在跑的是哪版（state/ 跨版本共享、launch.json
#   不记 IMAGE）⇒ 启动横幅 + launch-banner.log 留痕，gate/守卫可断言。
# ── 镜像-参数预检（2026-09-21 版本切换防雷，v2=parser 自省）────────────────
# ★v1 字面量提取法已被白盒证伪废弃：0.2.7 fork 的 server_args.py 是 attrs 新式
#   声明（schedule_policy: A[str, Arg(...)]），CLI flag 名是运行时从属性名派生，
#   字面 `--schedule-policy` 根本不出现在源文本 ⇒ 字面量法对新式声明全盲、必假拦。
#   v2 改让镜像自己的 argparse 说话：认哪些 flag、每个 choice flag 合法值是什么。
# ★判别力实证（本日四臂白盒）：--schedule-policy 在 0.2.6/0.2.7 都在（老 flag），
#   版本雷在 choice——"shortest-prefill-first" 只有 0.2.7+ 认（#40024 正式版合入）。
#   所以 choice 级检查是拦雷主力，不是 flag 级的附属。
# 结果按镜像 content_id 缓存于 state/flagpreflight/（每镜像只付一次 ~30s 自省）。
image_arg_preflight() {
  [[ -z "${EXTRA_SGLANG_ARGS:-}" ]] && return 0
  local -a _flags=()
  local _t _f _v _ch _miss=0
  for _t in $EXTRA_SGLANG_ARGS; do
    [[ "$_t" == --* ]] && _flags+=("$_t")
  done
  [[ ${#_flags[@]} -eq 0 ]] && return 0
  local _cid _cache
  _cid=$(img_content_id "$IMAGE")
  mkdir -p "$STATE_DIR/flagpreflight" 2>/dev/null || true
  _cache="$STATE_DIR/flagpreflight/${_cid:-uncached}.txt"
  if [[ -n "$_cid" && -s "$_cache" ]]; then
    info "flag 清单命中缓存（镜像 $IMAGE content_id=$_cid）"
  else
    # 一次 python 自省：FLAGS:行=flag 名；CHOICES:行=值型 flag 的合法值(逗号串)
    timeout 120 docker run --rm --entrypoint python "$IMAGE" -c '
import argparse
from sglang.srt.server_args import ServerArgs
p = argparse.ArgumentParser(prog="x", add_help=False)
ServerArgs.add_cli_args(p)
for a in p._actions:
    for s in a.option_strings:
        print("FLAGS:" + s)
        if getattr(a, "choices", None):
            print("CHOICES:%s:%s" % (s, ",".join(str(c) for c in a.choices)))
' > "$_cache" 2>/dev/null || true
    if [[ ! -s "$_cache" ]]; then
      rm -f "$_cache"
      warn "镜像 parser 自省失败（import 慢/镜像无 python 入口？），flag 预检降级跳过（弱化态）"
      return 0
    fi
  fi
  for _f in "${_flags[@]}"; do
    grep -qx "FLAGS:$_f" "$_cache" || {
      err "EXTRA_SGLANG_ARGS 的 $_f 不被镜像 $IMAGE 识别（版本切换雷：新 flag 配旧镜像）"
      _miss=1
    }
  done
  # choice 级泛化检查：任何带 choices 的值型 flag，值不在 choices 即拦
  for _f in "${_flags[@]}"; do
    _v="${EXTRA_SGLANG_ARGS##*$_f }"; _v="${_v%% *}"
    [[ -z "$_v" || "$_v" == --* ]] && continue   # 尾置 flag / 后面跟另一 flag：无数可查
    _ch=$(grep -x "CHOICES:$_f:.*" "$_cache" | head -1 | cut -d: -f3-)
    [[ -z "$_ch" ]] && continue                  # 该 flag 无 choices 约束：跳过
    grep -qx -- "$_v" <(tr ',' '\n' <<<"$_ch") || {
      err "$_f 的值 '$_v' 不在镜像 $IMAGE 的 choices[$_ch]（版本切换雷：新值配旧镜像）"
      _miss=1
    }
  done
  [[ $_miss -eq 1 ]] && return 1
  info "镜像-参数预检过：${#_flags[@]} 个 flag + choice 值全部被 $IMAGE 识别"
  return 0
}

# ── 四机 GPU 时钟 burn 预检（2026-09-21 门禁统筹⑥；栈停态专用）──────────────
# PD 安全模式病（runbook §7）：断电/OOM 后某机 SM 钉 513-728MHz，起栈=半速栈。
# 探针=生产镜像跑 6s matmul 并采负载时钟，健康 ≥1500MHz。GPU 被占（栈已在跑）
# 时跳过该机并 warn——本预检只该在栈停时被调到。
gpu_clock_preflight() {
  local -a _pids=()
  local _h _out _mhz _w _bad=0
  for _h in head "${WORKER_HOSTS[@]}"; do
    (
      if [ "$_h" = head ]; then
        if nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -q '[0-9]'; then echo "BUSY"; exit 0; fi
        docker run --rm --gpus all --entrypoint python "$IMAGE" -c '
import torch,time
a=torch.randn(8192,8192,device="cuda");b=torch.randn(8192,8192,device="cuda")
t0=time.time()
while time.time()-t0<12: c=a@b; torch.cuda.synchronize()
' >/dev/null 2>&1 &
        p=$!
        # 审计 P2 修：冷 page cache 时 import torch 可 >4s，固定 sleep 4 会采到 idle
        # ~351MHz → 误报楔死 die → 把人推向无谓物理断电。等负载真建立（时钟 ≥1000）
        # 再取读数；楔死机等不到 → 超时后取到低值 → 正确 FAIL。
        _w=0
        while [ $_w -lt 14 ]; do
          _cl=$(nvidia-smi --query-gpu=clocks.sm --format=csv,noheader,nounits 2>/dev/null | tr -d ' ' | grep -oE '^[0-9]+' || echo 0)
          [ "${_cl:-0}" -ge 1000 ] && break
          sleep 2; _w=$((_w+1))
        done
        nvidia-smi --query-gpu=clocks.sm,power.draw --format=csv,noheader,nounits | tr -d ' '
        wait $p 2>/dev/null
      else
        ssh "$_h" "
nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -q '[0-9]' && { echo BUSY; exit 0; }
docker run --rm --gpus all --entrypoint python $IMAGE -c \"
import torch,time
a=torch.randn(8192,8192,device='cuda');b=torch.randn(8192,8192,device='cuda')
t0=time.time()
while time.time()-t0<12: c=a@b; torch.cuda.synchronize()
\" >/dev/null 2>&1 &
p=\$!
_w=0
while [ \$_w -lt 14 ]; do
  _cl=\$(nvidia-smi --query-gpu=clocks.sm --format=csv,noheader,nounits 2>/dev/null | tr -d ' ' | grep -oE '^[0-9]+' || echo 0)
  [ "\${_cl:-0}" -ge 1000 ] && break
  sleep 2; _w=\$((_w+1))
done
nvidia-smi --query-gpu=clocks.sm,power.draw --format=csv,noheader,nounits | tr -d ' '
wait \$p 2>/dev/null" 2>/dev/null
      fi
    ) > "/tmp/gpuclk-$_h.preflight" 2>/dev/null &
    _pids+=($!)
  done
  for _p in "${_pids[@]}"; do wait "$_p" 2>/dev/null; done
  for _h in head "${WORKER_HOSTS[@]}"; do
    _out=$(cat "/tmp/gpuclk-$_h.preflight" 2>/dev/null | head -1)
    _mhz=$(printf '%s' "$_out" | cut -d',' -f1 | grep -oE '^[0-9]+' || echo 0)
    _w=$(printf '%s' "$_out" | cut -d',' -f2 | grep -oE '^[0-9]+' || echo '?')
    rm -f "/tmp/gpuclk-$_h.preflight"
    case "$_out" in
      BUSY|"") warn "gpu-clock 预检跳过 $_h（GPU 被占或探针跑不了——若栈确已停则人工查）" ;;
      *) if [ "${_mhz:-0}" -ge 1500 ]; then
           info "gpu-clock 预检过 $_h：burn=${_mhz}MHz/${_w}W"
         else
           err "gpu-clock 楔死 $_h：burn=${_mhz}MHz/${_w}W（PD 安全模式；修复=拔墙上 AC 冷断电，runbook §7）"
           _bad=1
         fi ;;
    esac
  done
  [[ $_bad -eq 0 ]] || return 1
  info "gpu-clock 预检过：四机负载时钟健康"
  return 0
}

fabric_gid_preflight() {
  local _idx="${NCCL_IB_GID_INDEX_FORCE:-${NCCL_IB_GID_INDEX:-3}}"
  local holes="$(_gid_holes_local)"
  [[ -n "$holes" ]] && { warn "head GID 洞(idx${_idx}): $(echo $holes | tr '\n' ' ')"; return 1; }
  local h rholes
  for h in "${WORKER_HOSTS[@]}"; do
    # idx 在本地展开后嵌入（白盒审计修正：旧写法 \${NCCL_IB_GID_INDEX_FORCE:-3} 在远端
    # 展开而远端无此 env ⇒ 恒 3，FORCE≠3 时本地/worker 口径错位——与下方 IB_HCA 同款嵌入法）
    # 审计 P1 修：ssh 不通（断电后高发窗）时旧写法输出空→判「无洞」放行——
    # 5 秒定向拦截在故障场景静默作废。remote_on 的 rc 会被管道吃掉，先单独收。
    if ! _rg=$(remote_on "$h" "for c in \$(echo '$IB_HCA' | tr ',' ' '); do [ -d /sys/class/infiniband/\$c ] || continue; [ \"\$(cat /sys/class/infiniband/\$c/ports/1/gid_attrs/types/$_idx 2>/dev/null)\" = 'RoCE v2' ] || echo \$c; done" 2>/dev/null); then
      warn "worker $h ssh 失败——GID 无法核验（fail-closed：宁拦勿放；机器没起完/网络未稳，稍候重试）"
      return 1
    fi
    rholes=$(printf '%s' "$_rg" | tr -d '\r')
    if [[ -n "$rholes" ]]; then
      warn "worker $h GID 洞(idx${_idx}): $rholes"
      return 1
    fi
  done
  return 0
}

gid_index_remote() {
  local host="$1" ip="$2" hex
  hex=$(printf '%02x%02x:%02x%02x' $(echo "$ip" | tr . ' '))
  remote_on "$host" "for hca in \$(echo $IB_HCA | tr ',' ' '); do
    [ -d /sys/class/infiniband/\$hca ] || continue;
    for g in /sys/class/infiniband/\$hca/ports/1/gids/*; do
      i=\${g##*/};
      [ \"\$(cat /sys/class/infiniband/\$hca/ports/1/gid_attrs/types/\$i 2>/dev/null)\" = 'RoCE v2' ] || continue;
      case \$(cat \$g) in *ffff:$hex) echo \$i; exit 0;; esac;
    done;
  done"
}

# sglang source overlay: graft-style per-file bind mounts (no image layers).
# Each present file in SGLANG_OVERLAY_DIR is mounted over its in-container
# path; md5 discipline applies (scp the same file to every worker host).
SGLANG_OVERLAY_DIR="${SGLANG_OVERLAY_DIR:-$HOME/dsv41-flash-dgxsparks/sglang-overlay}"
# autotune golden 锁定（2026-09-21 用户指令）：见 docker_common_args 里的挂载注释。
# 存在即挂（四机 rsync 对齐）；不存在=未启用（行为与旧版完全一致）。
AUTOTUNE_GOLDEN_DATA="${AUTOTUNE_GOLDEN_DATA:-$ROOT/autotune-golden/data}"
declare -A SGLANG_OVERLAY_MAP=(
  # 2026-09-21 A/B 臂：#39482 UE8M0(121 in tuple) 回退嫌疑——文件存在即挂载（dev 模式）
  [configurer.py]=python/sglang/srt/layers/deep_gemm_wrapper/configurer.py
  [decode_cuda_graph_runner.py]=python/sglang/srt/model_executor/runner/decode_cuda_graph_runner.py
  # DSV41 (2026-09-19): scheduler prefill share cap (L1186 idea, #34554); env DSV41_PREFILL_SHARE_TOKENS
  [schedule_policy.py]=python/sglang/srt/managers/schedule_policy.py
  # DSV41 2026-09-19: autotune discard→majority-vote (kill the per-boot tactic lottery = slow-boot root cause)
  [flashinfer_autotune.py]=python/sglang/srt/model_executor/runner/flashinfer_autotune.py
  # DSV41 2026-09-19: tool-call truncation semantics (vLLM #52645 port)
  # v41 is identical to base (105 lines, zero parse override) — overlay for completeness
  [deepseekv32_detector.py]=python/sglang/srt/function_call/deepseekv32_detector.py
  [deepseekv41_detector.py]=python/sglang/srt/function_call/deepseekv41_detector.py
  # --- Lane D Wave 1 (2026-09-15, r9-ops): PR38409 + PR39370-sub1 + PR39138 ---
  [main_norm_rope.cuh]=python/sglang/kernels/jit/csrc/deepseek_v4/main_norm_rope.cuh
  [dspark_accept.py]=python/sglang/kernels/ops/speculative/dspark/dspark_accept.py
  [dflash_info_v2.py]=python/sglang/srt/speculative/dflash_info_v2.py
  [dspark_draft.py]=python/sglang/srt/speculative/dspark_components/dspark_draft.py
  [fast_argmax.py]=python/sglang/kernels/ops/speculative/dspark/fast_argmax.py
  [ops_embeddings__init__.py]=python/sglang/kernels/ops/embeddings/__init__.py
  [engram_hash.py]=python/sglang/kernels/ops/embeddings/engram_hash.py
  [engram.py]=python/sglang/srt/layers/engram.py
  # --- CED opt1 (2026-09-15, r9-ops): skip late layers on non-final chunks ---
  [schedule_batch.py]=python/sglang/srt/managers/schedule_batch.py
  [forward_batch_info.py]=python/sglang/srt/model_executor/forward_batch_info.py
  [deepseek_v4_backend.py]=python/sglang/srt/layers/attention/deepseek_v4_backend.py
  [deepseek_v4_model.py]=python/sglang/srt/models/deepseek_v4.py
  # --- Lane D Wave 2 (2026-09-15, r9-ops): PR39420 side-stream/graph single-stream ---
  [deepseek_v2.py]=python/sglang/srt/models/deepseek_v2.py
  [deepseek_v4_dspark.py]=python/sglang/srt/models/deepseek_v4_dspark.py
  # --- Lane D Wave 3 (2026-09-15, r9-ops): PR39187 bounded dense indexer + PR38979 prefill reuse (env-gated OFF) ---
  [server_args.py]=python/sglang/srt/server_args.py
  [environ.py]=python/sglang/srt/environ.py
  [dsv4_indexer.py]=python/sglang/srt/layers/attention/dsv4/indexer.py
  [dsv4_prefill_reuse.py]=python/sglang/srt/layers/attention/dsv4/prefill_reuse.py
  # --- FP4 main KV M0+M1 (2026-09-15, r9-ops): #39123 fork-v4-fp4 pool + repack bridge ---
  [c1.cuh]=python/sglang/kernels/jit/csrc/deepseek_v4/c1.cuh
  [c2.cuh]=python/sglang/kernels/jit/csrc/deepseek_v4/c2.cuh
  [fused_norm_rope_v2.cuh]=python/sglang/kernels/jit/csrc/deepseek_v4/fused_norm_rope_v2.cuh
  [store.cuh]=python/sglang/kernels/jit/csrc/deepseek_v4/store.cuh
  [kv_layout.cuh]=python/sglang/kernels/jit/include/sgl_kernel/deepseek_v4/kv_layout.cuh
  [attn.py]=python/sglang/kernels/ops/attention/dsv4/attn.py
  [c1.py]=python/sglang/kernels/ops/attention/dsv4/c1.py
  [c2.py]=python/sglang/kernels/ops/attention/dsv4/c2.py
  [compress.py]=python/sglang/kernels/ops/attention/dsv4/compress.py
  [dequant_k_cache.py]=python/sglang/kernels/ops/attention/dsv4/dequant_k_cache.py
  [elementwise.py]=python/sglang/kernels/ops/attention/dsv4/elementwise.py
  [kv_layout.py]=python/sglang/kernels/ops/attention/dsv4/kv_layout.py
  [repack_fp4_to_v4.py]=python/sglang/kernels/ops/attention/dsv4/repack_fp4_to_v4.py
  [overrides.py]=python/sglang/srt/arg_groups/overrides.py
  [npu_dsv4_memory_pool.py]=python/sglang/srt/hardware_backend/npu/dsv4/dsv4_memory_pool.py
  [compressor_v2.py]=python/sglang/srt/layers/attention/dsv4/compressor_v2.py
  [torch_quant.py]=python/sglang/srt/layers/attention/dsv4/torch_quant.py
  [deepseek_v4_memory_pool.py]=python/sglang/srt/mem_cache/deepseek_v4_memory_pool.py
  [dsv41_request_window.py]=python/sglang/srt/mem_cache/dsv41_request_window.py
  [hybrid_pool_assembler.py]=python/sglang/srt/mem_cache/hybrid_cache/hybrid_pool_assembler.py
  [kv_cache_configurator.py]=python/sglang/srt/mem_cache/kv_cache_configurator.py
  [pool_configurator.py]=python/sglang/srt/model_executor/pool_configurator.py
  # CTX600K R1/R2 (2026-09-21 窗口)：indexer logits 尺寸稳定化（宽度网格+行预算，
  # 单请求 nonpaged prefill 的 O(N) strand 根治）+ page_table 分配宽度网格。
  # 逃生口：SGLANG_DSV4_INDEXER_LOGITS_BUDGET_MB=0 / SGLANG_DSV4_PAGETABLE_PAGES_GRID=1
  # （文件经 sglang-overlay.ctx600k/ 专用目录挂载，生产 0 模式不受影响）
  [indexer.py]=python/sglang/srt/layers/attention/dsv4/indexer.py
  # DSV41 #40352 语义级回移（2026-09-23）：候选协议层。backend 惰性导入 ⇒ 缺件时
  # DSV41_IDX_PROTOCOL=0 的路径零影响；镜像也烘了同三份（见 build-0.2.8.sh PAYLOAD）。
  [candidate_indexer.py]=python/sglang/srt/layers/attention/dsv4/candidate_indexer.py
  [dense_prefill_indexer.py]=python/sglang/srt/layers/attention/dsv4/dense_prefill_indexer.py
  [mqa_logits_utils.py]=python/sglang/srt/layers/attention/mqa_logits_utils.py
  [dsv4_attn_metadata_kernels.py]=python/sglang/kernels/ops/attention/dsv4_attn_metadata_kernels.py
  # 诊断 overlay（sglang-overlay.diag/）：SIGUSR1→CUDA memory_snapshot 落 /state/ctxsnap。
  # 门=DSV41_SCHED_SNAPSHOT=1（缺省关闭，生产 0 模式零影响）。
  [scheduler.py]=python/sglang/srt/managers/scheduler.py
)
# 审计 P2：declare -A 重复键静默 last-wins——一个挂载会在所有消费点（
# _wov_expect / sglang_overlay_mounts / want_files）同时无声消失。源文本
# 级检测一次，命中即喊（不拦启：三处消费同源自洽，坏的是「静默」本身）。
_sov_dupes=$(awk '/^declare -A SGLANG_OVERLAY_MAP=\(/,/^\)/' "$0" \
  | sed -n 's/^[[:space:]]*\[\([^]]*\)\]=.*/\1/p' | sort | uniq -d)
[[ -n "$_sov_dupes" ]] && warn "SGLANG_OVERLAY_MAP 存在重复键（后者静默胜出）: $_sov_dupes"
unset _sov_dupes
# 2026-09-23 QA 补：**重复键查不到"两个键指向同一目标"**。实测本表有 2 个键
#   （`dsv4_indexer.py` 与 `indexer.py`）都映射到 `.../dsv4/indexer.py`，这是
#   **刻意的跨谱系兼容**：两个名字各只在各自谱系里存在——
#     sglang-overlay.stale-20260921/ 有 dsv4_indexer.py、无 indexer.py
#     sglang-overlay.ctx600k-probe/  有 indexer.py、无 dsv4_indexer.py
#   所以"两个键"不是错误，**不能删任一个**。但它是两类静默的温床，故这里喊：
#     ① 若某目录同时有两者 ⇒ dev 模式两条 `-v` 打同一目标，docker 静默 last-wins；
#     ② 挂载数 ≠ 映射数时（源缺失被下面的 `-f` 跳过），现在由 sglang_overlay_mounts
#        出声报数，不再让"只挂到一半"无声通过。
_sov_dupt=$(awk '/^declare -A SGLANG_OVERLAY_MAP=\(/,/^\)/' "$0" \
  | sed -n 's/^[[:space:]]*\[\([^]]*\)\]=\(.*\)$/\2/p' | sort | uniq -d)
[[ -n "$_sov_dupt" ]] && warn "SGLANG_OVERLAY_MAP 多个键指向同一目标（dev 模式 -v last-wins；若为跨谱系兼容别名可忽略，但请确认两源不同时存在）: $_sov_dupt"
unset _sov_dupt
# 代码来源（2026-09-16 起）：镜像内 vs 宿主逐文件 bind-mount。
#   0（默认，生产）＝ overlay 与 adapter/b12x/NCCL shim 都在镜像里 ⇒ 容器只剩**数据挂载**。
#     好处是结构清楚，且"改了盘上、容器仍看旧 inode"这一类漂移**从结构上消失**
#     （overlay-drift-check 报 drift=0 成为常态而不是例外）。
#   1（开发）＝ 逐文件覆盖，改完重启即可，不必重建镜像。代价：必须重建容器才看得到新字节
#     （逐文件 bind-mount 钉住 inode），且这类失效**任何缓存检查都看不出来**。
SGLANG_CODE_MOUNTS="${SGLANG_CODE_MOUNTS:-0}"
sglang_overlay_mounts() {   # $1 = nameref array to append -v args to
  local -n _o=$1
  local f n=0 miss=()
  [[ "$SGLANG_CODE_MOUNTS" = 1 ]] || return 0
  for f in "${!SGLANG_OVERLAY_MAP[@]}"; do
    if [[ -f "$SGLANG_OVERLAY_DIR/$f" ]]; then
      _o+=( -v "$SGLANG_OVERLAY_DIR/$f:/sgl-workspace/sglang/${SGLANG_OVERLAY_MAP[$f]}:ro" )
      n=$((n+1))
    else
      # 源缺失 ⇒ 跳过。跳过本身是对的（docker `-v` 对缺失源会**静默建成空目录**，
      # 那会把目标文件变成目录），但"跳过多少"必须出声：否则指向错谱系的目录时，
      # 你会以为覆盖了 49 个文件、实际只挂了 1 个（跨谱系别名那两条就是这样）。
      miss+=("$f")
    fi
  done
  local total=${#SGLANG_OVERLAY_MAP[@]}
  if (( ${#miss[@]} )); then
    warn "overlay 挂载 $n/$total（源缺失被跳过：${miss[*]}）—— dir=$SGLANG_OVERLAY_DIR；若这不符合预期，说明指向了别的谱系"
  else
    info "overlay 挂载 $n/$total（全部命中）"
  fi
}

docker_common_args() {
  local -n _a=$1
  local src hip gid
  src=$(model_src)
  hip="$2"
  gid="$3"
  [[ -d "$src" ]] || die "model mount src missing: $src"
  # 开发模式才挂逐文件覆盖（生产用镜像内的代码，见 SGLANG_CODE_MOUNTS 说明）
  local -a code_mounts=()
  if [[ "$SGLANG_CODE_MOUNTS" = 1 ]]; then
    sglang_overlay_mounts code_mounts
    local _pair _src_dev _tgt_dev
    for _pair in "$HOME/dsv41-flash-dgxsparks/adapter /opt/dsv41/adapter" \
                 "$HOME/dsv41-flash-dgxsparks/b12x-site /opt/b12x"; do
      _src_dev="${_pair%% *}"; _tgt_dev="${_pair#* }"
      if [[ -d "$_src_dev" ]]; then
        code_mounts+=(-v "$_src_dev:$_tgt_dev:ro")
      else
        # 源不在就**不要挂**：docker 会替你造一个空目录盖住镜像里烘好的那份
        # （/opt/dsv41/adapter 是 PYTHONPATH 首段、/opt/b12x 是 MoE 取件），
        # 于是"开发模式"悄悄把生产资产换成空壳，而容器里看不出原因。
        warn "开发模式：$_src_dev 不存在 → 不挂它（容器用镜像内的 $_tgt_dev）"
      fi
    done
  fi
  # 同一条开关管 JIT 缓存：开发挂宿主 ~/.cache，生产用镜像里烘的那份。
  local -a cache_mounts=()
  [[ "$SGLANG_CODE_MOUNTS" = 1 ]] && cache_mounts=(-v "$HOME/.cache:/root/.cache")
  # ── autotune golden 锁（2026-09-21 用户指令：健康缓存+锁定+重建带质量门）──
  # 现状取证：0.2.x 的 FlashInfer autotune 战术表=9/19 v13 抽签烘进镜像（digest
  # ebf68191，rank_tp0 独一份），每靴 3 个 worker rank 找不到自己的 rank 文件→
  # 空票，1/4「多数」表决把 rank0 表覆写过去——锁定是烘镜像的偶然产物：无质量
  # 验证（BASELINE.md 自证「钉住表不保证每区间最优」）、容器重建即丢覆写、配置
  # 一变（缓存键变）就回冷签彩票。golden 改成设计行为：宿主目录钉住容器 autotune
  # 根，四 rank 各自命中预置的同表 rank 文件 ⇒ 表决自然 no-op、跨靴跨机确定。
  # 新配置键冷签会写进宿主目录 ⇒ 由 gate 的 MANIFEST 一致性断言拦截（质量门在
  # ~/dsv41-flash-dgxsparks/AUTOTUNE-GOLDEN-RUNBOOK.md 的重建规程里）。
  local -a golden_mounts=()
  [[ -d "$AUTOTUNE_GOLDEN_DATA" ]] && golden_mounts=(-v "$AUTOTUNE_GOLDEN_DATA:/root/.cache/sglang/flashinfer/autotune")
  _a+=(
    --network host --ipc host --privileged --cap-add IPC_LOCK --gpus all
    # 无 --shm-size：--ipc host 之下 /dev/shm 就是宿主的（实测容器内 df=61G），
    # docker 会忽略 --shm-size（旧值 32g 从未生效）。若将来去掉 --ipc host，
    # 必须显式补上 --shm-size，否则会退回 docker 默认的 64MB —— NCCL/torch 会失败。
    # --memory 保持 24g（2026-09-16 实测复核，**不要**顺手抬高）：
    #   稳态 memory.current 8.60GiB（36% 上限，anon 6.74GiB）；四机 memory.peak 全部
    #   顶在上限（head 超 1 页、三 worker 精确相等），memory.events 的 max 计数
    #   2.7-3.0 万次 —— 但 oom_kill **四机全 0**。能一直顶在上限而不被杀，说明被压住的
    #   是**可回收页缓存**（加载期 476GB 检查点的 read() 路径，pgsteal 累计 721GiB），
    #   不是 anon（anon 峰值 11GiB，距上限还有 13GiB）。⇒ 这道上限的实际职能是
    #   **给加载期的页缓存上闸**：宿主 MemFree 只有 1.16GiB，而 GPU 的 ~99GiB
    #   统一内存分配正是从这个池子里拿 —— 抬高上限等于让页缓存去抢 GPU 的口粮。
    # --memory-swap 与 memory 取同值 = 禁 swap（有意）：GB10 是统一内存，换出会把
    # 权重/Engram 通路拖进 swap 抖动，宁可让它硬失败。
    --memory "${CTN_MEMORY:-24g}" --memory-swap "${CTN_MEMORY:-24g}"
    --ulimit "memlock=-1:-1" --ulimit stack=67108864
    --device /dev/infiniband:/dev/infiniband
    -v "$src:/models/DeepSeek-V4.1-Flash:ro"
    -v "$STATE_DIR:/state"
    # JIT 缓存：生产用**镜像里烘的那份**（/root/.cache，构建时由 build_optimized_image.sh
    # 的 2b 步对着同一份 overlay 树刷新过），容器只往自己的可写层写新产物。
    # 过去无条件挂宿主 ~/.cache，会把 544MB 里的 pip(428M)/uv(38M)/fontconfig/ibus/
    # tracker3 等桌面缓存一起塞进生产容器，并且容器以 root 往里写 ⇒ 宿主属主读不了
    # （实测 ~/.cache/sglang/nv EACCES）。开发模式才挂（改完即生效，见 SGLANG_CODE_MOUNTS）。
    # 回退旋钮：若首启出现大面积 JIT 重编（`docker diff` 里 .cache 新增以万计），
    # 就把这里换成按需挂三个子目录（sglang/b12x/flashinfer），理由与验法见
    # V41-SGLANG-SESSION-DOSSIER §6。
    "${cache_mounts[@]}"
    "${golden_mounts[@]}"
    "${code_mounts[@]}"
    -e "PYTHONPATH=/opt/dsv41/adapter:/opt/b12x"
    -e "OFFLOAD_MODE=$OFFLOAD_MODE"
    -e "DSV41_CACHE_GIB=$DSV41_CACHE_GIB"
    -e "DSV41_IO_THREADS=$DSV41_IO_THREADS"
    -e "DSV41_RESIDENT_SCALES=$DSV41_RESIDENT_SCALES"
    -e "DSV41_CACHE_WAYS=$DSV41_CACHE_WAYS"
    -e "DSV41_STATS_SECONDS=$DSV41_STATS_SECONDS"
    -v "$ENGRAM_DIR:/engram"
    -e "DSV41_PACKED_DIR=$DSV41_PACKED_DIR"
    -e "DSPARK_SPS_TABLE=$DSPARK_SPS_TABLE"
    -e "DSPARK_STS_TABLE=$DSPARK_STS_TABLE"
    -e "DSV41_SOURCE=/models/DeepSeek-V4.1-Flash"
    -e "MODEL_PATH=/models/DeepSeek-V4.1-Flash"
    -e "STATE_PATH=/state"
    -e "SERVER_PORT=$PORT"
    -e "NNODES=$NNODES"
    -e "TP_SIZE=$TP_SIZE"
    -e "EP_SIZE=$EP_SIZE"
    -e "DIST_INIT_ADDR=${HEAD_IP}:${DIST_PORT}"
    -e "CONTEXT_LENGTH=$CONTEXT_LENGTH"
    -e "MEM_FRACTION_STATIC=$HEAD_MEM_FRACTION_STATIC"
    -e "MAX_RUNNING_REQUESTS=$MAX_RUNNING_REQUESTS"
    -e "CHUNKED_PREFILL_SIZE=$CHUNKED_PREFILL_SIZE"
    -e "MAX_TOTAL_TOKENS=$MAX_TOTAL_TOKENS"
    -e "CUDA_GRAPH_MAX_BS_DECODE=$MAX_RUNNING_REQUESTS"
    -e "SPEC_ALGO=$SPEC_ALGO"
    -e "DSPARK_BLOCK_SIZE=$DSPARK_BLOCK_SIZE"
    -e "SERVED_MODEL_NAME=$SERVED_MODEL_NAME"
    -e "SKIP_PREPARE=$SKIP_PREPARE"
    -e "SKIP_VERIFY=$SKIP_VERIFY"
    -e "WARMUP=${WARMUP:-1}"
    -e "HOST=${HOST:-0.0.0.0}"
    -e "NCCL_NET=$NCCL_NET"
    -e "NCCL_IB_DISABLE=$NCCL_IB_DISABLE"
    -e "NCCL_IB_HCA=$IB_HCA"
    -e "NCCL_SOCKET_IFNAME=$NCCL_SOCKET_IFNAME"
    -e "GLOO_SOCKET_IFNAME=$GLOO_SOCKET_IFNAME"
    -e "NCCL_P2P_DISABLE=$NCCL_P2P_DISABLE"
    -e "NCCL_SHM_DISABLE=$NCCL_SHM_DISABLE"
    -e "NCCL_CROSS_NIC=${NCCL_CROSS_NIC:-1}"
    -e "NCCL_IB_MERGE_NICS=${NCCL_IB_MERGE_NICS:-0}"
    -e "NCCL_IB_SUBNET_AWARE_ROUTING=${NCCL_IB_SUBNET_AWARE_ROUTING:-1}"
    -e "NCCL_CUMEM_ENABLE=0"
    -e "NCCL_DEBUG=$NCCL_DEBUG"
    -e "NCCL_BUFFSIZE=${NCCL_BUFFSIZE:-4194304}"
    -e "NCCL_LL128_BUFFSIZE=${NCCL_LL128_BUFFSIZE:--2}"
    -e "NCCL_PROTO=${NCCL_PROTO:-LL,LL128,Simple}"
    -e "NCCL_MAX_NCHANNELS=${NCCL_MAX_NCHANNELS:-32}"
    -e "NCCL_DEBUG_SUBSYS=${NCCL_DEBUG_SUBSYS:-INIT}"
    -e "DSV41_MXFP8_BACKEND=${DSV41_MXFP8_BACKEND:-b12x}"
    -e "SGLANG_FLASHINFER_MOE_FUSED_FINALIZE=${SGLANG_FLASHINFER_MOE_FUSED_FINALIZE:-1}"
    -e "PYTORCH_CUDA_ALLOC_CONF=${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:False}"
    -e "CUDA_DEVICE_ORDER=PCI_BUS_ID"
    -e "SGLANG_ENABLE_DSV41_ENGRAM_HOST_TABLE=0"
    -e "DSV41_TP_PAD=${DSV41_TP_PAD:-1}"
    -e "VLLM_HOST_IP=$hip"
    -e "HOST_IP=$hip"
    -e "NCCL_IB_GID_INDEX=$gid"
  )
  if [[ -n "${API_KEY}" ]]; then
    _a+=(-e "API_KEY=$API_KEY")
  fi
  if [[ -n "${EXTRA_SGLANG_ARGS:-}" ]]; then
    _a+=(-e "EXTRA_SGLANG_ARGS=$EXTRA_SGLANG_ARGS")
  fi
  # Ring 适配：定制 RING-only NCCL 2.30.7 + 核绑定 shim（与 vLLM 生产栈同一对 LD_PRELOAD）。
  # 这两个库**已烘进镜像**（/opt/nccl-ringonly、/opt/libncclpin.so），所以生产模式不再挂载；
  # 但 env 仍由启动器显式给 —— 镜像刻意**不烘 LD_PRELOAD**：libncclpin.so 会全局拦截
  # pthread_create/pthread_setname_np（按线程名只钉 NCCL 线程），写进镜像 ENV 就等于让它对
  # 每个 `docker exec` 的调试工具也生效。临时关掉用 NCCLPIN_DISABLE=1。
  if [[ "$SGLANG_CODE_MOUNTS" = 1 ]]; then
    if [[ -f "$NCCL_HOST_DIR/libnccl.so.2.30.7" || -f "$NCCL_HOST_DIR/libnccl.so.2" ]]; then
      _a+=(-v "$NCCL_HOST_DIR:$NCCL_CONTAINER_DIR:ro")
    fi
    if [[ -f /opt/aicad-prod/lib/libncclpin.so && -d /opt/nccl-ringonly ]]; then
      mkdir -p "$HOME/nccl-debug"
      _a+=(-v "/opt/aicad-prod/lib/libncclpin.so:/opt/libncclpin.so:ro"
           -v "/opt/nccl-ringonly:/opt/nccl-ringonly:ro"
           -v "$HOME/nccl-debug:/nccl-debug:rw")
    fi
  fi
  _a+=(-e "LD_LIBRARY_PATH=/opt/nccl-ringonly"
       -e 'LD_PRELOAD=/opt/libncclpin.so /opt/nccl-ringonly/libnccl.so.2')
  # Ring adaptation: per-rank PEER_HCA for rank 0 (workers get theirs in
  # worker_env_lines via PEER_HCA_RANK<n>).
  if [[ -n "${PEER_HCA_RANK0:-}" ]]; then
    _a+=(-e "NCCL_IB_PEER_HCA=${PEER_HCA_RANK0}")
  fi
  # Ring adaptation: generic passthrough, appended last so it overrides any
  # default set above (docker keeps the last -e for a duplicated key).
  if [[ -n "${EXTRA_DOCKER_ENV:-}" ]]; then
    local _ed
    for _ed in ${EXTRA_DOCKER_ENV}; do
      [[ -z "$_ed" ]] && continue
      _a+=(-e "$_ed")
    done
  fi
}

# Every rank builds its own planner, so the SPS/STS calibration has to exist on
# every node -- the head's copy in $STATE_DIR is the source of truth.
push_spec_tables() {
  local name local_path host
  for name in dspark_sps.json dspark_sts.json; do
    local_path="$STATE_DIR/$name"
    for host in "${WORKER_IPS[@]}"; do
      if [[ -f "$local_path" ]]; then
        local payload
        payload=$(base64 -w0 <"$local_path")
        # Every rank derives its verify schedule from its own copy of this file.
        # A rank that disagrees with the others builds a different verify shape
        # and the TP collective hangs, so a failed push is fatal, not a warning.
        remote_on "$host" "mkdir -p $WORKER_DIR/state && echo $payload | base64 -d > $WORKER_DIR/state/$name" \
          || die "could not push $name to $host: ranks would disagree on the DSpark verify schedule"
        info "pushed $name to $host"
      else
        # Likewise for a stale copy left from an earlier run.
        remote_on "$host" "rm -f $WORKER_DIR/state/$name" \
          || die "could not clear a stale $name on $host"
      fi
    done
  done
}

worker_env_lines() {
  local wip="$1" wgid="$2" rank="$3"
  # Ring adaptation: generic env passthrough + per-rank PEER_HCA
  # (PEER_HCA_RANK<n> from .env). Emitted as single-quoted lines so values
  # with commas/semicolons survive the remote bash -lc round trip.
  local _ed _extra=""
  # LD_PRELOAD must be a literal single-quoted line here: embedding it in a
  # remote variable (SHIM_VOL) breaks word splitting (quotes are not
  # re-parsed after variable expansion).
  _extra+="        -e 'LD_PRELOAD=${LD_PRELOAD_SHIM:-/opt/libncclpin.so /opt/nccl-ringonly/libnccl.so.2}' \\"$'\n'
  for _ed in ${EXTRA_DOCKER_ENV:-}; do
    [[ -z "$_ed" ]] && continue
    _extra+="        -e '$_ed' \\"$'\n'
  done
  local _ph_var="PEER_HCA_RANK${rank}"
  local _ph="${!_ph_var:-}"
  if [[ -n "$_ph" ]]; then
    _extra+="        -e 'NCCL_IB_PEER_HCA=$_ph' \\"$'\n'
  fi
  cat <<EOF
        -e NODE_RANK=$rank -e NNODES=$NNODES \\
        -e TP_SIZE=$TP_SIZE -e EP_SIZE=$EP_SIZE \\
        -e DIST_INIT_ADDR=$HEAD_IP:$DIST_PORT \\
        -e OFFLOAD_MODE=$OFFLOAD_MODE -e DSV41_CACHE_GIB=$DSV41_CACHE_GIB \\
        -e DSV41_IO_THREADS=$DSV41_IO_THREADS \\
        -e DSV41_RESIDENT_SCALES=$DSV41_RESIDENT_SCALES \\
        -e DSV41_CACHE_WAYS=$DSV41_CACHE_WAYS \\
        -e DSV41_STATS_SECONDS=$DSV41_STATS_SECONDS \\
        -v $WORKER_ENGRAM_DIR:/engram \\
        -e DSV41_PACKED_DIR=$DSV41_PACKED_DIR \\
        -e DSPARK_SPS_TABLE=$DSPARK_SPS_TABLE \\
        -e DSPARK_STS_TABLE=$DSPARK_STS_TABLE \\
        -e DSV41_SOURCE=/models/DeepSeek-V4.1-Flash \\
        -e MODEL_PATH=/models/DeepSeek-V4.1-Flash -e STATE_PATH=/state \\
        -e SERVER_PORT=$PORT -e HOST=${HOST:-0.0.0.0} \\
        -e CONTEXT_LENGTH=$CONTEXT_LENGTH \\
        -e MEM_FRACTION_STATIC=$MEM_FRACTION_STATIC \\
        -e MAX_RUNNING_REQUESTS=$MAX_RUNNING_REQUESTS \\
        -e CHUNKED_PREFILL_SIZE=$CHUNKED_PREFILL_SIZE \\
        -e MAX_TOTAL_TOKENS=$MAX_TOTAL_TOKENS \\
        -e CUDA_GRAPH_MAX_BS_DECODE=$MAX_RUNNING_REQUESTS \\
        -e SPEC_ALGO=$SPEC_ALGO -e DSPARK_BLOCK_SIZE=$DSPARK_BLOCK_SIZE \\
        -e SERVED_MODEL_NAME=$SERVED_MODEL_NAME \\
        -e SKIP_PREPARE=1 -e SKIP_VERIFY=1 -e SKIP_SMOKE=1 \\
        -e NCCL_NET=$NCCL_NET -e NCCL_IB_DISABLE=$NCCL_IB_DISABLE \\
        -e NCCL_IB_HCA=$IB_HCA -e NCCL_SOCKET_IFNAME=$NCCL_SOCKET_IFNAME \\
        -e GLOO_SOCKET_IFNAME=$GLOO_SOCKET_IFNAME \\
        -e NCCL_P2P_DISABLE=$NCCL_P2P_DISABLE -e NCCL_SHM_DISABLE=$NCCL_SHM_DISABLE \\
        -e NCCL_CROSS_NIC=${NCCL_CROSS_NIC:-1} \\
        -e NCCL_IB_MERGE_NICS=${NCCL_IB_MERGE_NICS:-0} \\
        -e NCCL_IB_SUBNET_AWARE_ROUTING=${NCCL_IB_SUBNET_AWARE_ROUTING:-1} \\
        -e NCCL_CUMEM_ENABLE=0 -e NCCL_DEBUG=$NCCL_DEBUG \\
        -e NCCL_BUFFSIZE=${NCCL_BUFFSIZE:-4194304} -e NCCL_LL128_BUFFSIZE=${NCCL_LL128_BUFFSIZE:--2} \\
        -e NCCL_PROTO=${NCCL_PROTO:-LL,LL128,Simple} -e NCCL_MAX_NCHANNELS=${NCCL_MAX_NCHANNELS:-32} \\
        -e NCCL_DEBUG_SUBSYS=${NCCL_DEBUG_SUBSYS:-INIT} \\
        -e DSV41_MXFP8_BACKEND=${DSV41_MXFP8_BACKEND:-b12x} \\
        -e SGLANG_FLASHINFER_MOE_FUSED_FINALIZE=${SGLANG_FLASHINFER_MOE_FUSED_FINALIZE:-1} \\
        -e PYTORCH_CUDA_ALLOC_CONF=${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:False} \\
        -e NCCL_IB_GID_INDEX=$wgid \\
        -e CUDA_DEVICE_ORDER=PCI_BUS_ID \\
        -e SGLANG_ENABLE_DSV41_ENGRAM_HOST_TABLE=0 \\
        -e DSV41_TP_PAD=${DSV41_TP_PAD:-1} \\
        -e HOST_IP=$wip -e VLLM_HOST_IP=$wip \\
${_extra}
EOF
}

cmd_doctor() {
  echo "=== doctor (DeepSeek-V4.1-Flash · ${NNODES}× Spark · TP${TP_SIZE} · SGLang) ==="
  echo "head:     $(hostname) / $(whoami) @ $HEAD_IP"
  echo "workers:  ${WORKER_USER}@${WORKER_HOSTS[*]}  (${WORKER_IPS[*]})"
  echo "image:    $IMAGE  (base $BASE_IMAGE)"
  echo "model:    $MODEL_DIR"
  echo "parallel: nnodes=$NNODES TP=$TP_SIZE EP=$EP_SIZE  ctx=$CONTEXT_LENGTH  util=$MEM_FRACTION_STATIC (head $HEAD_MEM_FRACTION_STATIC)"
  echo "offload:  $OFFLOAD_MODE  cache=${DSV41_CACHE_GIB}GiB  spec=$SPEC_ALGO-$DSPARK_BLOCK_SIZE  port=$PORT"
  echo
  local ok=0
  command -v docker >/dev/null || { warn "docker missing on head"; ok=1; }
  command -v nvidia-smi >/dev/null && info "GPU: $(nvidia-smi -L | head -1)" || { warn "nvidia-smi missing"; ok=1; }
  [[ -f "$SSH_IDENTITY" ]] && info "SSH key $SSH_IDENTITY" || { warn "SSH key missing"; ok=1; }
  local host_arch
  host_arch=$(uname -m)
  info "host arch: $host_arch (GB10 expects aarch64)"

  if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    info "overlay image present ($(docker image inspect -f '{{.Architecture}}' "$IMAGE"))"
  else
    warn "image $IMAGE missing — ./start.sh build (pulls $BASE_IMAGE)"
  fi

  if [[ -f "$MODEL_DIR/config.json" ]]; then
    local n
    n=$(find "$MODEL_DIR" -maxdepth 1 -name 'model-*-of-*.safetensors' 2>/dev/null | wc -l | tr -d ' ')
    if [[ "${n:-0}" -ge "$EXPECTED_SHARDS" ]]; then
      info "checkpoint OK ($n / $EXPECTED_SHARDS shards, $(du -sh "$MODEL_DIR" | awk '{print $1}'))"
    else
      warn "partial checkpoint ($n / $EXPECTED_SHARDS) — ./start.sh download"
      ok=1
    fi
  else
    warn "checkpoint missing — ./start.sh download"
    ok=1
  fi

  if [[ "$OFFLOAD_MODE" == "ram" ]]; then
    warn "RAM Engram mode pins ~189 GiB into unified memory — will not fit on Spark. Use nvme."
    ok=1
  fi
  if nfs_rpc_ready 127.0.0.1; then
    local _mounts="" _i
    for _i in "${!WORKER_HOSTS[@]}"; do _mounts+=" ${WORKER_HOSTS[$_i]}→$(nfs_server_ip_for "${WORKER_HOSTS[$_i]}" "$_i" 2>/dev/null || echo '?')"; done
    info "NFSv4 listening on this host (workers should mount CX7:${_mounts})"
  else
    warn "NFSv4 not listening yet — ./start.sh share will start or reuse the exporter"
  fi
  info "weights: spark2/spark3 use docker NFS volume $NFS_VOLUME (head $MODEL_DIR); no rsync/SSHFS"
  if [[ "$TP_SIZE" -eq 3 ]]; then
    info "TP3 note: heads=64, o_groups=8, vocab=129280 are not divisible by 3; adapter/tp3_pad.py pads them"
    info "  (heads 64→96, groups 8→12, draft experts 128→129). experts=384 divides. Rank 2 holds padded shards only."
    info "  2 Sparks cannot hold the MXFP4 experts (290 GiB / 2 = 145 GiB > 121 GiB)."
  elif [[ "$TP_SIZE" -eq 4 ]]; then
    info "TP4 note: heads, o_groups, draft experts and vocab all divide by 4; no padding (DSV41_TP_PAD=${DSV41_TP_PAD:-0})."
  fi

  if nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null | grep -q .; then
    warn "GPU already has compute apps:"
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
    warn "Stop the other stack (e.g. ./start.sh stop in glm-5.3-flash-sm120) before serving, or FORCE=1"
  fi

  local h
  for h in "${WORKER_HOSTS[@]}"; do
    if remote_on "$h" "hostname" >/tmp/dsv41-host-"$h".txt 2>/tmp/dsv41-ssh-"$h".err; then
      info "SSH $h OK → $(tr -d '\r' </tmp/dsv41-host-"$h".txt)"
      remote_on "$h" "command -v docker >/dev/null && nvidia-smi -L | head -1 && test -d /dev/infiniband && echo IB_OK" \
        || { warn "docker/GPU/IB check failed on $h"; ok=1; }
    else
      err "SSH to $h FAILED"
      cat /tmp/dsv41-ssh-"$h".err || true
      ok=1
    fi
  done

  if [[ "$ok" -ne 0 ]]; then
    if [[ "${DOCTOR_STRICT:-1}" == "1" && "${1:-}" == "strict" ]]; then
      die "doctor found blocking issues"
    fi
    warn "doctor: issues found"
    return 1
  fi
  info "doctor: ready"
}

cmd_download() {
  info "=== download $HF_REPO @$HF_REVISION → $MODEL_DIR ==="
  mkdir -p "$MODEL_DIR"
  local n
  n=$(find "$MODEL_DIR" -maxdepth 1 -name 'model-*-of-*.safetensors' 2>/dev/null | wc -l | tr -d ' ')
  if [[ -f "$MODEL_DIR/config.json" && "${n:-0}" -ge "$EXPECTED_SHARDS" ]]; then
    info "checkpoint already present ($n safetensors) — skip"
  else
    command -v hf >/dev/null || die "hf CLI missing (pip install -U huggingface_hub[cli])"
    hf download "$HF_REPO" --revision "$HF_REVISION" --local-dir "$MODEL_DIR"
  fi
  ln -sfn "$MODEL_DIR" "$COMMON_MODEL"
  info "head: $COMMON_MODEL → $MODEL_DIR"
}

cmd_pull() {
  info "=== pull $BASE_IMAGE on all nodes ==="
  ensure_ssh_keys
  docker pull --platform linux/arm64 "$BASE_IMAGE"
  local h
  for h in "${WORKER_HOSTS[@]}"; do
    info "pulling on $h ..."
    remote_on "$h" --timeout "${PULL_TIMEOUT:-0}" \
      "docker pull --platform linux/arm64 $(printf '%q' "$BASE_IMAGE")"
  done
  info "base image present on all nodes"
}

cmd_build() {
  info "=== build $IMAGE from $ROOT ==="
  if ! docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
    cmd_pull
  fi
  docker build -t "$IMAGE" "$ROOT"
  local img_arch
  img_arch=$(docker image inspect -f '{{.Architecture}}' "$IMAGE")
  [[ "$img_arch" == "arm64" ]] || die "expected arm64 image, got $img_arch"
  info "head built $IMAGE arch=$img_arch"

  ensure_ssh_keys
  local h
  for h in "${WORKER_HOSTS[@]}"; do
    info "rsync recipe → $h:$WORKER_DIR"
    remote_on "$h" "mkdir -p $(printf '%q' "$WORKER_DIR")"
    rsync -aH --delete --exclude '.env' --exclude '.env.tp4' --exclude 'state' --exclude 'state-tp4' \
      --exclude 'logs' --exclude 'logs-tp4' --exclude 'models' \
      --exclude 'engram' \
      -e "$(ssh_rsync_e)" \
      "$ROOT/" "${WORKER_USER}@${h}:${WORKER_DIR}/"
    info "docker build on $h ..."
    remote_on "$h" --timeout "${BUILD_TIMEOUT:-0}" \
      "docker image inspect $(printf '%q' "$BASE_IMAGE") >/dev/null || docker pull --platform linux/arm64 $(printf '%q' "$BASE_IMAGE")
       cd $(printf '%q' "$WORKER_DIR") && docker build -t $(printf '%q' "$IMAGE") ."
  done
  info "overlay image on all 3 nodes"
}

cmd_share() {
  info "=== share spark1 checkpoint over NFSv4 on ConnectX ==="
  [[ -f "$MODEL_DIR/config.json" ]] || die "no checkpoint — ./start.sh download"
  ln -sfn "$MODEL_DIR" "$COMMON_MODEL"
  ensure_ssh_keys
  nfs_ensure_server
  nfs_publish_model
  local i=0 h
  for h in "${WORKER_HOSTS[@]}"; do
    nfs_ensure_worker_volume "$h" "$i"
    if nfs_worker_has_model "$h"; then
      info "$h: $NFS_VOLUME has config.json"
    else
      die "$h cannot see the checkpoint over NFS. Check ACL (10.0.23.0/24 for spark3) and docker logs of the nfs exporter."
    fi
    i=$((i + 1))
  done
  info "spark2 + spark3 read $MODEL_DIR from spark1 over NFS (no local copy)"
}
cmd_mount() { cmd_share; }

cmd_sync() {
  die "rsync of this 476 GiB checkpoint will not fit spark3. Use ./start.sh share (NFSv4 from spark1)."
}

_busy_gpu() {
  nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -q '[0-9]'
}

# --- 生产模式镜像守卫 --------------------------------------------------------
# SGLANG_CODE_MOUNTS=0 时，代码/资产**只来自镜像**（没有 bind-mount 兜底）。三类失效都无声：
#   ① 本机缺镜像 → 旧代码会**自动 build**：那是本地现造的另一份东西，四机里只要有一台缺，
#     栈照样起来，但四机跑的不是同一份代码/资产；
#   ② 镜像里没烘那几项资产 → 容器照起，静默丢 ring-only NCCL / b12x / 入口，性能与行为一起变；
#   ③ 四机 image ID 不同 → "四机同栈"只是名义上的（同一个 tag 指向不同内容）。
# 所以这三条放在启动路径上硬断言，且生产模式**不自动 build**。
PROD_IMAGE_ASSETS="/opt/dsv41/boot.py /opt/dsv41/adapter/librow_store.so /opt/b12x \
/opt/nccl-ringonly/libnccl.so.2 /opt/libncclpin.so \
/sgl-workspace/sglang/python/sglang/kernels/jit/include/sgl_kernel/deepseek_v4/kv_layout.cuh"

# 镜像的**内容身份**：RootFS 层清单（diffID 序列）的哈希。
# ★为什么不能用 `docker image inspect -f '{{.Id}}'`：本集群两种镜像存储并存 ——
#   head（rank 0）是 containerd 的 overlayfs 快照器（Driver=overlayfs），02-04 是经典
#   overlay2；同一份内容在两边报出的 .Id 不同（实测 03587ce92d08… vs 9e1036bc6a10…），
#   而**层清单完全相同**（123 层；内容身份由下方 IMGID_TPL 定义 ⇒ 4ebef21b6aedbd70）。
#   拿 .Id 当身份 = 让 serve 永远被自己拦住，而且拦得莫名其妙。
#   2026-09-18 四机实测佐证：.Config=77799e6ce3de5824、.RootFS=cdd980943dfe9e6b、
#   .Created=0203e92cacf2a896、org.dsv41.* 标签 —— 逐字段哈希四机全等，只有 .Id 不同。
# ⚠ 层清单哈希必须连**字节精确的管道**一起引用。同一条 123 项 diffID 清单，序列化
#   不同就得到不同的值（2026-09-18 由发布包离线复现，见 scripts/verify_release_artifact.py）：
#     空格连接 + 尾换行（{{join .RootFS.Layers " "}} 经 sha256sum）⇒ 4ebef21b6aedbd70 ★权威
#     空格连接、无尾换行                                          ⇒ bb7c2d4b38af0514
#     换行连接、无尾换行                                          ⇒ c8751accc458138c
#     换行连接 + 尾换行                                           ⇒ 38bbe8265458f328
#     换行连接 + 两个尾换行                                       ⇒ 0050285e87c6f408
#   本注释旧版引用的就是 38bbe8265458…，它**不是幽灵值**，而是「换行连接 + 尾换行」
#   这一口径的正确结果——错的只是没标出口径。下方 IMGID_TPL 对应的才是权威值。
IMGID_TPL='{{join .RootFS.Layers " "}}'
img_content_id() { docker image inspect -f "$IMGID_TPL" "$1" 2>/dev/null | sha256sum | cut -c1-16; }

image_preflight() {
  local h want_id got_id got_files want_files missing
  docker image inspect "$IMAGE" >/dev/null 2>&1 \
    || die "本机缺镜像 $IMAGE。生产模式不自动 build（那会造出另一份镜像）；请先 build+分发，或临时 SGLANG_CODE_MOUNTS=1 走宿主代码"
  if [[ "$SGLANG_CODE_MOUNTS" = 1 ]]; then
    warn "代码来源=宿主逐文件 bind-mount（开发模式）：只查镜像在场，跳过自足性/四机一致性断言"
    for h in "${WORKER_HOSTS[@]}"; do
      remote_ok_on "$h" "docker image inspect $(printf '%q' "$IMAGE") >/dev/null 2>&1" \
        || die "$h 上没有 $IMAGE（开发模式也需要它——逐文件挂载只覆盖代码，容器本体仍来自镜像）"
    done
    return 0
  fi
  # ② 自足性：这些路径缺任一个，容器仍能起，但会静默降级
  local probe_rc=0
  missing=$(docker run --rm --network none --entrypoint sh "$IMAGE" -c '
    m=""
    for p in '"$PROD_IMAGE_ASSETS"'; do [ -e "$p" ] || m="$m $p"; done
    printf "%s" "$m"' 2>/dev/null) || probe_rc=$?
  # ★探针自身跑不起来 ≠ 镜像自足。旧版把 `docker run` 的失败（例如 rc=125）也当成
  #   "missing 为空 ⇒ 通过"，于是这条闸门在最需要它的时候（镜像根本起不来）静默放行
  #   （2026-09-17 交叉审核实测）。
  [[ "$probe_rc" = 0 ]] || die "自足性探针自身失败（docker run rc=$probe_rc）⇒ **无法证明镜像自足**，按失败处理。
     先手工核对：docker run --rm --network none --entrypoint sh $IMAGE -c 'ls -d $PROD_IMAGE_ASSETS'"
  [[ -z "$missing" ]] || die "镜像 $IMAGE **不自足**，缺：$missing
   生产模式不会 bind-mount 它们 ⇒ 会静默丢 ring-only NCCL/b12x/入口/kv_layout 头。重建镜像再上线"
  # ③ 四机同一份（按内容身份比，见 img_content_id 的说明）
  want_id=$(img_content_id "$IMAGE")
  [[ -n "$want_id" ]] || die "取不到本机镜像的内容身份（$IMAGE）"
  got_files=$(docker image inspect -f '{{index .Config.Labels "org.dsv41.overlay_files"}}' "$IMAGE" 2>/dev/null || true)
  want_files="${#SGLANG_OVERLAY_MAP[@]}"
  [[ "$got_files" = "$want_files" ]] \
    || warn "镜像标注 overlay_files=${got_files:-无} 而本机 start.sh 映射为 $want_files 条 ⇒ 镜像不是按当前映射烘的（内容可能旧），核对后再上线"
  info "镜像 $IMAGE  内容身份=$(printf '%s' "$want_id")…  overlay_files=${got_files:-?}  map_md5=$(docker image inspect -f '{{index .Config.Labels "org.dsv41.overlay_map_md5"}}' "$IMAGE" 2>/dev/null || echo '?')"
  for h in "${WORKER_HOSTS[@]}"; do
    # ★必须先确认"镜像在不在"，再算内容身份：空输入的 sha256sum 恒为 e3b0c44298fc1c14（**非空**），
    #   旧写法因此永远走不到"这台没有该镜像"分支，把"缺镜像"误诊成"四机内容不一致"
    #   （方向仍是 fail-closed，但报错把人引向错误的排查路径 —— 2026-09-17 交叉审核实测）。
    # ⚠ 用两次调用，**不要**把 `if…then…fi` 塞进一条远端命令：远端命令经 python 助手传参，
    #   复合语句在那里不可靠（实测：同一条命令直接 ssh 跑得出 4ebef21b…，经助手却返回空 ⇒
    #   假报"没有该镜像"并拦住起栈）。存在性判定复用 dev 分支已在用的 `remote_ok_on`。
    if remote_ok_on "$h" "docker image inspect $(printf '%q' "$IMAGE") >/dev/null 2>&1"; then
      got_id=$(remote_on "$h" "docker image inspect -f '$IMGID_TPL' $(printf '%q' "$IMAGE") 2>/dev/null | sha256sum | cut -c1-16" 2>/dev/null | tr -d '\r' | tail -1)
    else
      got_id=""
    fi
    [[ -n "$got_id" ]] || die "$h 上没有 $IMAGE —— 生产模式不自动 build。先在四机就位同一份（docker save | ssh … docker load），或临时 SGLANG_CODE_MOUNTS=1"
    [[ "$got_id" = "$want_id" ]] \
      || die "四机镜像内容不一致：$h=$got_id vs 本机=$want_id —— 同一个 tag 指向不同内容，先统一再起栈"
    info "  $h 同一份内容（$got_id）"
  done
}

cmd_serve() {
  DOCTOR_STRICT=0 cmd_doctor || true
  # Pre-start guard check, before any container is created. Motivated by the
  # 2026-09-15 incident: a window went ahead with no oom_gate monitor on any node,
  # so the prefill transient of the raised KV pin had nothing to catch it and the
  # host OOM-killed the scheduler. That failure is silent -- a missing guard raises
  # no error -- so it belongs on the start path, not in memory. The hook is
  # read-only and returns 0 unconditionally, so it can never block a launch;
  # GUARD_ONSTART=0 skips it.
  if [[ -f "$HOME/w6-kit/guard/guard-onstart.sh" && "${GUARD_ONSTART:-1}" == "1" ]]; then
    bash "$HOME/w6-kit/guard/guard-onstart.sh" || true
  fi
  [[ -f "$MODEL_DIR/config.json" ]] || cmd_download
  ln -sfn "$MODEL_DIR" "$COMMON_MODEL"

  if _busy_gpu && [[ "${FORCE:-0}" != "1" ]]; then
    die "GPU is busy (glm53-exl3 or similar). Stop the other stack, or FORCE=1 ./start.sh serve"
  fi

  # 开发模式且本机缺镜像时才允许自动 build（生产模式绝不：见 image_preflight 的说明）。
  if [[ "$SGLANG_CODE_MOUNTS" = 1 ]] && ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    warn "开发模式：本机缺镜像 $IMAGE → 自动 build"
    cmd_build
  fi
  # 存在性 + 自足性 + 四机同一份（生产模式三条硬断言）
  image_preflight

  # 2026-09-21 版本切换两防线：参数-镜像兼容预检 + 启动横幅留痕（launch-banner.log
  # 供 gate/守卫断言「在跑的是哪版」；自愈单元把栈拉回别的镜像时可据此发现）
  image_arg_preflight || die "EXTRA_SGLANG_ARGS 与镜像 $IMAGE 不兼容（见上方 [x] 明细）——版本切换配错，拒绝起栈"
  # share/ec 真值在 EXTRA_DOCKER_ENV 串里（不是顶层 shell 变量——188 行死键教训），
  # 直接 ${VAR:-?} 会永远打 ?（T9 白盒抓出），必须从串里抠。
  _share=$(grep -o 'DSV41_PREFILL_SHARE_TOKENS=[0-9]*' <<<"$EXTRA_DOCKER_ENV" | head -1 | cut -d= -f2)
  _ec=$(grep -o 'DSV41_PREFILL_EMPTY_CACHE_TOKENS=[0-9]*' <<<"$EXTRA_DOCKER_ENV" | head -1 | cut -d= -f2)
  # 审计 P2 修：banner 无 golden 状态——本靴没锁运维无从而知（锁被静默绕过）
  local _gstat=OFF
  [[ -d "$AUTOTUNE_GOLDEN_DATA" ]] && _gstat=locked
  [ "$_gstat" = OFF ] && warn "autotune golden 未挂载（本靴不锁定：镜像烘焙表+每靴票决形态——非有意停用请排查 $AUTOTUNE_GOLDEN_DATA）"
  _banner="ENV_FILE=$(basename "$ENV_FILE") env_md5=$(md5sum "$ENV_FILE" 2>/dev/null | cut -c1-8) IMAGE=$IMAGE content_id=$(img_content_id "$IMAGE") chunk=$CHUNKED_PREFILL_SIZE ctx=$CONTEXT_LENGTH share=${_share:-?} ec=${_ec:-?} golden=$_gstat"
  info "启动横幅: $_banner"
  mkdir -p "$STATE_DIR" && echo "$(date -Is) serve $_banner" >> "$STATE_DIR/launch-banner.log"
  # 审计 P2 修：head 有 golden 树而 worker 缺 → 该 rank 静默冷签、表决把空票覆写
  # 回去（票决病理复活）——起栈前四机在场强一致断言。
  if [[ -d "$AUTOTUNE_GOLDEN_DATA" ]]; then
    for _wh in "${WORKER_HOSTS[@]}"; do
      remote_on "$_wh" "test -d '$AUTOTUNE_GOLDEN_DATA'" >/dev/null 2>&1 \
        || die "worker $_wh 缺 golden 树 $AUTOTUNE_GOLDEN_DATA（四 rank 表不一致=票决病理复活；先按 AUTOTUNE-GOLDEN-RUNBOOK.md rsync 对齐再起栈）"
    done
  fi

  # 2026-09-21：fabric GID 洞预检（断电后 NCCL 崩环的 5 秒定向拦截；
  # 修复步骤见 ~/w6-kit/FABRIC-GID-REPAIR-RUNBOOK.md，勿反复试靴）
  if ! fabric_gid_preflight; then
    die "fabric GID 洞在案（见上方 warn 明细）：NCCL 将在 modify_qp RTR 处崩（errno 61）。
  修复=对洞口做 IP 环回重建（runbook §2 有逐口命令），修完 bash ~/w6-kit/s4_bench.sh verify 全绿再起栈。"
  fi

  # 2026-09-21 门禁统筹⑥：四机 GPU 时钟 burn 预检（PD 安全模式楔死拦截）。
  # 02 实锤：断电后 SM 钉 721MHz ⇒ TP4 全体 prefill 减半（5000→2500），起栈 11 分钟
  # + 全套 gate 都过了才发现。楔死机 warm reboot 修不了，必须拔墙上 AC 冷断电
  # （runbook §7）。预检=栈停态跑 6s matmul，四机并行 ~15s，负载时钟 <1500MHz 即拦。
  if ! gpu_clock_preflight; then
    die "GPU 时钟楔死在案（见上方 warn 明细）：起栈只会得到半速栈。
  修复=关机 → 拔墙上 AC 插座 1-2 分钟（拔机箱端 USB-C 无效；warm reboot 无效）→ 回线后
  bash ~/w6-kit/powercycle_check.sh 全绿再起栈（GID 可能随断电再出洞）。"
  fi

  local h need_share=0
  if [[ "$WEIGHTS_MODE" == "local" ]]; then
    info "WEIGHTS_MODE=local — workers read node-local weights, NFS skipped"
    local _wi _wm _ov
    for _wi in "${!WORKER_HOSTS[@]}"; do
      _wm="${WORKER_MODEL_DIR:-}"
      _ov="WORKER_MODEL_DIR_$((_wi + 1))"
      [ -n "${!_ov:-}" ] && _wm="${!_ov}"
      remote_ok_on "${WORKER_HOSTS[$_wi]}" "test -f $_wm/config.json" \
        || die "missing local weights on ${WORKER_HOSTS[$_wi]}: $_wm"
    done
  else
    for h in "${WORKER_HOSTS[@]}"; do
      if ! nfs_worker_has_model "$h"; then
        need_share=1
      fi
    done
  fi
  # 原先这里是"哪台缺镜像就在本机 build 一遍"——本机 build 修不了 worker 的缺失，
  # 只会把同一个 tag 在不同节点指向不同内容。现在统一由 image_preflight 断言四机同一份。
  if [[ "$WEIGHTS_MODE" != "local" && ( "$need_share" -eq 1 || "$NFS_SHARE" == "1" ) ]]; then
    cmd_share
  fi

  API_KEY="$(api_key)"
  export API_KEY
  if [[ -n "$API_KEY" ]]; then
    echo "$API_KEY" > "$STATE_DIR/api-key"
    chmod 600 "$STATE_DIR/api-key"
  else
    rm -f "$STATE_DIR/api-key"
  fi

  local GID_HEAD gi g
  local -a WORKER_GIDS=()
  # Ring adaptation: kernel-1031 GID-table reorder makes auto-detection
  # untrustworthy here; the fleet runs NCCL_IB_GID_INDEX=-1 as a hard rule.
  if [[ -n "${NCCL_IB_GID_INDEX_FORCE:-}" ]]; then
    GID_HEAD="$NCCL_IB_GID_INDEX_FORCE"
    for gi in "${!WORKER_IPS[@]}"; do WORKER_GIDS+=("$NCCL_IB_GID_INDEX_FORCE"); done
    info "RoCEv2 GID indexes: FORCED head=$GID_HEAD workers=${WORKER_GIDS[*]} (NCCL_IB_GID_INDEX_FORCE)"
  else
    GID_HEAD=$(gid_index_local "$HEAD_IP" 2>/dev/null || true)
    GID_HEAD="${GID_HEAD:-${NCCL_IB_GID_INDEX:-3}}"
    for gi in "${!WORKER_IPS[@]}"; do
      g=$(gid_index_remote "${WORKER_HOSTS[$gi]}" "${WORKER_IPS[$gi]}" | tr -d '\r' || true)
      WORKER_GIDS+=("${g:-${NCCL_IB_GID_INDEX:-3}}")
    done
    info "RoCEv2 GID indexes: head=$GID_HEAD workers=${WORKER_GIDS[*]}"
  fi

  docker rm -f "$HEAD_CTN" >/dev/null 2>&1 || true
  for h in "${WORKER_HOSTS[@]}"; do
    remote_on "$h" "docker rm -f $WORKER_CTN >/dev/null 2>&1 || true" || true
  done

  push_spec_tables
  info "Starting workers (ranks 1..${#WORKER_IPS[@]}) first..."
  local idx=0 wip wgid rank wmodel wextra _ov _ev _wov_expect _f
  for h in "${WORKER_HOSTS[@]}"; do
    wip="${WORKER_IPS[$idx]}"
    wgid="${WORKER_GIDS[$idx]}"
    rank=$((idx + 1))
    # Cluster adaptation (2026-09-14, our fleet): workers may have per-rank
    # model dirs (02 holds full local weights; 03/04 read 46 shards over NFS)
    # and per-rank extra file binds (03/04 pin the two Engram shards to the
    # LOCAL files so the row-store never reads Engram over the network).
    # WORKER_MODEL_DIR_<rank> / WORKER_EXTRA_MOUNTS_<rank> override the
    # single-value defaults from the env file.
    wmodel="${WORKER_MODEL_DIR:-}"
    _ov="WORKER_MODEL_DIR_${rank}"
    [ -n "${!_ov:-}" ] && wmodel="${!_ov}"
    wextra="${WORKER_EXTRA_MOUNTS:-}"
    _ev="WORKER_EXTRA_MOUNTS_${rank}"
    [ -n "${!_ev:-}" ] && wextra="${!_ev}"
    # Prebuild overlay pairs locally (map keys/values only; no remote $vars).
    # 2026-09-22 审计 P1-1：同时数出 head 侧预期挂载数，worker 必须精确等于它
    # （覆盖三个盲区：worker 目录整体缺失 / 部分子集挂载 / 0 命中静默）。
    wov=""
    _wov_expect=0
    for _f in "${!SGLANG_OVERLAY_MAP[@]}"; do
      # 审计 P2：wov 用空格分词传递，key/value 带空格或冒号会截断值侧——
      # 与其让远端报错误导的分叉计数，不如起跑前当面拒掉。
      [[ "$_f" =~ [:\ ] || "${SGLANG_OVERLAY_MAP[$_f]}" =~ [:\ ] ]] &&
        die "overlay map 条目 '$_f: ${SGLANG_OVERLAY_MAP[$_f]}' 含空格/冒号——wov 协议不支持，请改文件名或映射路径"
      wov+=" $_f:${SGLANG_OVERLAY_MAP[$_f]}"
      [[ -f "$SGLANG_OVERLAY_DIR/$_f" ]] && _wov_expect=$((_wov_expect + 1))
    done
    # 2026-09-20 H7：worker 起败即停。旧版不检查退出码 ⇒ head 照常启动、干等
    # peer 直到 idle 超时（默认 600s），根因被超时掩埋。remote.py 传播远端 rc，
    # 远端脚本自带 set -e（卷/权重/镜像缺失即败）。
    if ! remote_on "$h" "
      set -e
      if [ '$WEIGHTS_MODE' != 'local' ]; then
        docker volume inspect $NFS_VOLUME >/dev/null || { echo 'MISSING docker volume $NFS_VOLUME on $h — run ./start.sh share'; exit 1; }
      fi
      test -d /dev/infiniband || { echo 'MISSING /dev/infiniband on $h'; exit 1; }
      mkdir -p $WORKER_DIR/state $WORKER_DIR/logs $WORKER_DIR/engram
      # 生产（代码在镜像里）：NCCL 库/shim 与 overlay 都已在镜像内 ⇒ 全部不挂载，
      # 容器只剩数据挂载。env 仍显式给（镜像刻意不烘 LD_PRELOAD）。
      NCCL_VOL=''
      NCCL_ENV='-e LD_LIBRARY_PATH=/opt/nccl-ringonly'
      if [ '${SGLANG_CODE_MOUNTS}' = 1 ]; then
        if [ -f $NCCL_HOST_DIR/libnccl.so.2.30.7 ] || [ -f $NCCL_HOST_DIR/libnccl.so.2 ]; then
          NCCL_VOL=\"-v $NCCL_HOST_DIR:$NCCL_CONTAINER_DIR:ro\"
        fi
      fi
      SHIM_VOL=''
      if [ '${SGLANG_CODE_MOUNTS}' = 1 ] && [ -f /opt/aicad-prod/lib/libncclpin.so ] && [ -d /opt/nccl-ringonly ]; then
        mkdir -p \$HOME/nccl-debug
        SHIM_VOL=\"-v /opt/aicad-prod/lib/libncclpin.so:/opt/libncclpin.so:ro -v /opt/nccl-ringonly:/opt/nccl-ringonly:ro -v \$HOME/nccl-debug:/nccl-debug:rw\"
      fi
      CODE_VOL=''
      if [ '${SGLANG_CODE_MOUNTS}' = 1 ]; then
        # 2026-09-20 F4：dev 挂载源存在性前置——docker -v 对不存在的宿主目录会
        # 静默建空目录，容器拿到空 adapter 后报错点离根因极远。缺目录直接拒启。
        for _cd in \$HOME/dsv41-flash-dgxsparks/adapter \$HOME/dsv41-flash-dgxsparks/b12x-site; do
          [ -d \"\$_cd\" ] || { echo \"SGLANG_CODE_MOUNTS=1 but \$_cd missing on $h — 拒启（空挂载会在容器内造成误导性错误）\"; exit 1; }
        done
        CODE_VOL=\"-v \$HOME/dsv41-flash-dgxsparks/adapter:/opt/dsv41/adapter:ro -v \$HOME/dsv41-flash-dgxsparks/b12x-site:/opt/b12x:ro\"
      fi
      CACHE_VOL=''
      if [ '${SGLANG_CODE_MOUNTS}' = 1 ]; then
        CACHE_VOL=\"-v \$HOME/.cache:/root/.cache\"
      fi
      # autotune golden 锁（审计 P1 修：与 head 的 golden_mounts 同一变量同一棵树——
      # 旧硬编码 \$HOME 路径在 head 用 AUTOTUNE_GOLDEN_DATA 指 staging 树时会
      # split-brain：head 冷签进 staging、worker 仍挂/写生产树）
      GOLDEN_VOL=''
      if [ -d '$AUTOTUNE_GOLDEN_DATA' ]; then
        GOLDEN_VOL=\"-v $AUTOTUNE_GOLDEN_DATA:/root/.cache/sglang/flashinfer/autotune\"
      fi
      MODEL_SRC='$NFS_VOLUME'
      if [ '$WEIGHTS_MODE' = 'local' ]; then MODEL_SRC='$wmodel'; fi
      WEXTRA='$wextra'
      OVERLAY_VOL=''
      if [ '${SGLANG_CODE_MOUNTS}' = 1 ]; then
        # worker 侧 overlay 挂载（split-brain 双防线）：
        # ① 2026-09-22 实锤修：2026-09-21 版把 \$wf 写进单引号（'$SGLANG_OVERLAY_DIR/\$wf'）
        #   ⇒ 远端永远测试字面文件名“\$wf”⇒ worker 全部静默裸镜像（head 带补丁、
        #   worker 不带），FIX-B/快照钩子在 worker 形同虚设、宿主侧 md5 验证还查不出。
        #   修法=去内层单引号，\$wf/\$wrel 落到远端双引号内正常展开；路径无空格，
        #   docker -v 裸传安全（与上方 CODE_VOL/GOLDEN_VOL 同风格）。
        # ② 0 命中熔断：目录非空但 map 零命中=拒启，杜绝再次静默分叉。
        _wov_n=0
        for wpair in $wov; do
          wf=\${wpair%%:*}; wrel=\${wpair#*:}
          if [ -f \"$SGLANG_OVERLAY_DIR/\$wf\" ]; then
            OVERLAY_VOL=\"\$OVERLAY_VOL -v $SGLANG_OVERLAY_DIR/\$wf:/sgl-workspace/sglang/\$wrel:ro\"
            _wov_n=\$((\$_wov_n+1))
          fi
        done
        _wov_have=\$(ls -1 \"$SGLANG_OVERLAY_DIR\" 2>/dev/null | wc -l)
        if [ \"\$_wov_n\" -ne ${_wov_expect} ]; then
          echo \"OVERLAY SPLIT-BRAIN: worker 挂载 \$_wov_n 个 != head 预期 ${_wov_expect} 个（目录缺失/子集/漂移；dir 内共 \$_wov_have 文件）— 拒启\" >&2
          exit 1
        fi
      fi
      docker run -d --name $WORKER_CTN \
        --network host --ipc host --privileged --cap-add IPC_LOCK --gpus all \
        --memory ${CTN_MEMORY:-24g} --memory-swap ${CTN_MEMORY:-24g} \
        --ulimit memlock=-1:-1 --ulimit stack=67108864 \
        --device /dev/infiniband:/dev/infiniband \
        \$OVERLAY_VOL \$CODE_VOL \
        -e PYTHONPATH=/opt/dsv41/adapter:/opt/b12x \
        -v \$MODEL_SRC:/models/DeepSeek-V4.1-Flash:ro \
        \$WEXTRA \
        -v $WORKER_DIR/state:/state \
        \$CACHE_VOL \$GOLDEN_VOL \
        \$NCCL_VOL \$NCCL_ENV \$SHIM_VOL \\
$(worker_env_lines "$wip" "$wgid" "$rank")
        -e API_KEY=$(printf '%q' "$API_KEY") \\
        -e EXTRA_SGLANG_ARGS=$(printf '%q' "${EXTRA_SGLANG_ARGS:-}") \\
        $(printf '%q' "$IMAGE") run
        # 审计 P2 修：远端 set -e 只拦 docker run 自身失败；容器创建成功后数秒内死
        # （argparse/NCCL 崩）时 rc=0 照判过，head 干等 READY 超时才见尸。补 8s 存活断言。
        sleep 8
        docker inspect -f '{{.State.Running}}' $WORKER_CTN 2>/dev/null | grep -q true || { echo 'WORKER 容器起后即死（argparse/NCCL 崩？）尾 20 行：'; docker logs --tail 20 $WORKER_CTN 2>&1; exit 1; }
    "; then
      err "── worker rank $rank ($h) 启动失败（上方为远端输出）— 追抓容器现场辅助定位："
      remote_on "$h" "docker ps -a --filter name=$WORKER_CTN --format 'table {{.Names}}\t{{.Status}}'; \
docker inspect -f 'State.Error={{.State.Error}} ExitCode={{.State.ExitCode}}' $WORKER_CTN 2>/dev/null; \
docker logs --tail 30 $WORKER_CTN 2>&1 || echo '(no container logs)'" || true
      die "worker rank $rank ($h) 起败 ⇒ 停止启动（旧版会照常起 head 后干等 peer 至 idle 超时，根因被超时掩埋）"
    fi
    # 引擎门控键「意图==实效」断言（worker 侧，与 head 同一份期望表+同一段比较逻辑）：
    # 从 head 侧 inspect 远端容器 env 再本地比对——远端 env 与 head 分叉（split-brain）
    # 时立刻拒启，而不是等 FIX-B 在 worker 上静默不生效。
    if ! engine_env_assert "worker rank $rank ($h)" \
      "$(remote_on "$h" "docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' $WORKER_CTN 2>/dev/null")"; then
      die "worker rank $rank ($h) 引擎门控键未送达容器 ⇒ 拒启（head/worker env 分叉或漏配）"
    fi
    idx=$((idx + 1))
  done

  info "Starting head (rank 0, API :$PORT)..."
  local -a head_args=()
  docker_common_args head_args "$HEAD_IP" "$GID_HEAD"
  local head_cid=""
  head_cid=$(docker run -d --name "$HEAD_CTN" --restart=no \
    "${head_args[@]}" \
    -e NODE_RANK=0 \
    -e SKIP_SMOKE="$SKIP_SMOKE" \
    -e SMOKE_QUICK="$SMOKE_QUICK" \
    "$IMAGE" run)
  [[ -n "$head_cid" ]] || die "docker run produced no container id"
  info "head cid=${head_cid:0:12}"
  # 引擎门控键「意图==实效」断言（2026-09-22）：EXTRA_DOCKER_ENV 里带门控键的 token
  # 必须真的出现在容器 env 里，否则 FIX-B 这类门会在「以为开着」的假设下静默关闭。
  engine_env_assert "head" \
    "$(docker inspect "$HEAD_CTN" --format '{{range .Config.Env}}{{println .}}{{end}}')" \
    || die "head 引擎门控键未送达容器 ⇒ 拒启（先看上面缺哪个 token；不改 env 就起=带缺陷跑）"

  mkdir -p "$LOG_DIR"
  : >"$SERVE_LOG"

  _stop_logtail() {
    local p
    p=$(cat "$LOG_DIR/logtail.pid" 2>/dev/null || true)
    rm -f "$LOG_DIR/logtail.pid"
    if [[ -n "${p:-}" ]]; then
      # Children first (docker logs + tee), while they are still parented to the
      # subshell; killing the subshell first reparents them and they outlive us,
      # which kept the log streaming onto the terminal after "this script is done".
      pkill -TERM -P "$p" 2>/dev/null || true
      kill -TERM "$p" 2>/dev/null || true
    fi
    # Only the follower started by this script (exact command lines); never the engine.
    pkill -TERM -f "docker logs -f --tail=20 ${HEAD_CTN}" 2>/dev/null || true
    pkill -TERM -f "tee -a ${SERVE_LOG}" 2>/dev/null || true
  }

  # Live engine log on this TTY, also copied to $SERVE_LOG. Stopped when we
  # return to the shell (ready or fail) — the container keeps running.
  info "streaming engine log (returns to shell when the engine is up, smoke-tested and warmed up, or the head dies)..."
  ( docker logs -f --tail=20 "$HEAD_CTN" 2>&1 | tee -a "$SERVE_LOG" ) &
  echo $! >"$LOG_DIR/logtail.pid"
  trap '_stop_logtail' EXIT

  _dump_head_fail() {
    _stop_logtail
    trap - EXIT
    local st oom errstr
    st=$(docker inspect -f '{{.State.Status}}' "$HEAD_CTN" 2>/dev/null || echo missing)
    oom=$(docker inspect -f '{{.State.OOMKilled}}' "$HEAD_CTN" 2>/dev/null || echo '?')
    errstr=$(docker inspect -f '{{.State.Error}}' "$HEAD_CTN" 2>/dev/null || echo '')
    echo
    err "head is ${st} (oom=${oom}) cid=${head_cid:0:12}"
    [[ -n "$errstr" ]] && err "docker: $errstr"
    echo "---- $SERVE_LOG (tail) ----"
    tail -n 120 "$SERVE_LOG" 2>/dev/null || true
    echo "---- workers ----"
    local wh
    for wh in "${WORKER_HOSTS[@]}"; do
      echo "== $wh =="
      remote_on "$wh" "docker ps -a --filter name=$WORKER_CTN --format '{{.Names}} {{.Status}}'; docker logs --tail=40 $WORKER_CTN 2>/dev/null | tail -40" || true
    done
  }

  local i=0 st
  # 审计 P2 修：实测起栈可达 11 分钟（楔死靴曾实锤），旧默认 360s 会把慢而健康的
  # 引导 die 掉再被 Restart=always 拉起循环。抬到 900s（可在 env 文件钉 READY_TIMEOUT 覆盖）。
  while (( i < ${READY_TIMEOUT:-900} )); do
    # Ready = boot.py printed its banner, i.e. /health answered AND the smoke test
    # and warm-up passed (WARMUP=0 / SKIP_SMOKE=1 skip them; then it is /health alone).
    if docker logs "$HEAD_CTN" 2>&1 | grep -q "^Ready: API on port ${PORT}" \
       || { [[ "${SKIP_SMOKE:-0}" == "1" ]] && curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; }; then
      _stop_logtail
      trap - EXIT
      # Keep the engine log flowing into $SERVE_LOG after we return, detached from
      # this terminal (the TTY follower above is what was stopped). Without this the
      # file ends at readiness and a later failure leaves no trace once the
      # container is removed.
      ( setsid docker logs -f --since 1s "$HEAD_CTN" >>"$SERVE_LOG" 2>&1 </dev/null & ) 2>/dev/null
      echo
      info "API is up on :$PORT (smoke + warm-up passed) — engine keeps running, this script is done."
      # Ring adaptation: verify NCCL came up ring-only (RING-ONLY patch present,
      # Tree disabled in the algorithm matrix, expected RoCE devices in use).
      # Non-fatal: a report is printed, the engine keeps running either way.
      "$ROOT/scripts/nccl_selfcheck.sh" || warn "NCCL 自检未通过 — 见上（./start.sh ncclcheck 可重跑）"
      cmd_status
      echo
      echo "  curl http://$HEAD_IP:$PORT/v1/chat/completions \\"
      if [[ -n "$API_KEY" ]]; then
        echo "    -H 'Authorization: Bearer $API_KEY' -H 'Content-Type: application/json' \\"
      else
        echo "    -H 'Content-Type: application/json' \\"
      fi
      echo "    -d '{\"model\":\"$SERVED_MODEL_NAME\",\"messages\":[{\"role\":\"user\",\"content\":\"What is 19 + 23?\"}],\"chat_template_kwargs\":{\"thinking\":false}}'"
      echo
      [[ -n "$API_KEY" ]] && echo "  key:  $STATE_DIR/api-key" || echo "  auth: none (no API key)"
      echo "  logs: ./start.sh logs | ./start.sh logs -f | ./start.sh logs worker1"
      echo "  stop: ./stop.sh"
      return 0
    fi
    st=$(docker inspect -f '{{.State.Status}}' "$HEAD_CTN" 2>/dev/null || echo missing)
    case "$st" in
      running|created|restarting) ;;
      *)
        _dump_head_fail
        exit 1
        ;;
    esac
    i=$((i + 1))
    sleep 10
  done
  _stop_logtail
  trap - EXIT
  die "timed out waiting for :$PORT — ./start.sh logs"
}

cmd_stop() {
  exec "$ROOT/stop.sh" "$@"
}

cmd_status() {
  echo "== head =="
  docker ps --filter "name=$HEAD_CTN" --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' || true
  echo
  # 2026-09-20 F2：权重检测与 serve/pack 同源取真路径。旧版一律测 $COMMON_MODEL
  # （head 侧 NFS 导出视图）——local 模式下 02 的本地全量目录/03-04 的 NFS 视图
  # 目录被误报 MISSING（假阴性）。rank 编号与 serve 段一致（idx+1，1 基）。
  local h _wi _wov wsrc
  _wi=1
  for h in "${WORKER_HOSTS[@]}"; do
    echo "== worker $h (rank $_wi) =="
    if [[ "$WEIGHTS_MODE" == "local" ]]; then
      _wov="WORKER_MODEL_DIR_${_wi}"
      wsrc="${!_wov:-$WORKER_MODEL_DIR}"
    else
      wsrc="$COMMON_MODEL"
    fi
    remote_on "$h" "docker ps --filter name=$WORKER_CTN --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' ; test -f $wsrc/config.json && echo weights:OK || echo weights:MISSING" || warn "status SSH $h failed"
    echo
    _wi=$((_wi + 1))
  done
  echo "== API =="
  local key
  key=$(cat "$STATE_DIR/api-key" 2>/dev/null || true)
  if curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/v1/models" \
     || { [[ -n "$key" ]] && curl -fsS --max-time 5 -H "Authorization: Bearer $key" "http://127.0.0.1:${PORT}/v1/models"; }; then
    echo
  else
    echo "(not responding on :$PORT)"
  fi
}

cmd_logs() {
  local who="${1:-head}" lines="${2:-120}"
  case "$who" in
    ''|head|[0-9]*)
      [[ "$who" =~ ^[0-9]+$ ]] && lines="$who"
      docker logs --tail="$lines" "$HEAD_CTN" 2>&1 || tail -n "$lines" "$SERVE_LOG"
      ;;
    worker*|w[0-9]*)
      local n="${who#worker}"; n="${n#w}"; n="${n:-1}"
      [[ "$n" =~ ^[0-9]+$ && "$n" -ge 1 && "$n" -le ${#WORKER_HOSTS[@]} ]] || die "no such worker: $who (1..${#WORKER_HOSTS[@]})"
      remote_on "${WORKER_HOSTS[$((n - 1))]}" "docker logs --tail=$lines $WORKER_CTN" || true
      ;;
    -f|follow)
      docker logs -f "$HEAD_CTN"
      ;;
    *)
      docker logs --tail="$lines" "$HEAD_CTN" 2>&1 || true
      ;;
  esac
}

cmd_smoke() {
  local key auth=()
  key=$(cat "$STATE_DIR/api-key" 2>/dev/null || true)
  [[ -n "$key" ]] && auth=(-H "Authorization: Bearer $key")
  info "smoke: 19+23 (thinking off)"
  curl -fsS --max-time 180 "http://127.0.0.1:${PORT}/v1/chat/completions" \
    "${auth[@]}" -H 'Content-Type: application/json' \
    -d "{\"model\":\"$SERVED_MODEL_NAME\",\"temperature\":0,\"chat_template_kwargs\":{\"thinking\":false},\"messages\":[{\"role\":\"user\",\"content\":\"What is 19 + 23? Reply only with the number.\"}]}"
  echo
}

# Ring adaptation: one command that answers "may this engine be trusted?",
# not merely "is the container Up" (alexellis's gate discipline).
cmd_gate() {
  SERVER_PORT="$PORT" API_KEY_FILE="$STATE_DIR/api-key" \
    "$ROOT/scripts/gate.sh" "$@"
}

CMD="${1:-serve}"
shift || true
# Repack each rank's owned Engram rows onto node-local NVMe (~68 GiB/node).
# A miss then costs one local read instead of two, and on a worker it stops
# being an NFS round trip to the head. Idempotent: complete shards are skipped.
cmd_pack() {
  local src
  src=$(model_src)
  info "packing Engram shards: head $ENGRAM_DIR, workers $WORKER_ENGRAM_DIR"
  mkdir -p "$ENGRAM_DIR"
  docker run --rm --network host \
    -v "$src:/models/DeepSeek-V4.1-Flash:ro" \
    -v "$ENGRAM_DIR:/engram" \
    -e DSV41_SOURCE=/models/DeepSeek-V4.1-Flash \
    --entrypoint python3 "$IMAGE" \
    /opt/dsv41/scripts/pack_engram.py --rank 0 --tp "$TP_SIZE" --out /engram \
    || die "pack failed on head"
  local idx=1 host wsrc
  for host in "${WORKER_IPS[@]}"; do
    info "packing rank $idx on $host..."
    # Ring adaptation: in local-weights mode the worker's checkpoint lives at
    # WORKER_MODEL_DIR; the NFS volume only exists in nfs mode. Without this the
    # mount silently resolves to a non-existent path and pack writes nothing,
    # leaving the worker on the 2-read unpacked path.
    if [[ "$WEIGHTS_MODE" == "local" ]]; then
      _ov="WORKER_MODEL_DIR_${idx}"
      wsrc="${!_ov:-$WORKER_MODEL_DIR}"
    else
      wsrc="$NFS_VOLUME"
    fi
    # Same per-rank Engram local-file binds as serve: on 03/04 the model view
    # is the NFS one, and pack must read the Engram tables from the LOCAL
    # shard files (Engram never crosses the network).
    _ev="WORKER_EXTRA_MOUNTS_${idx}"
    wpack_extra="${!_ev:-}"
    remote_on "$host" "test -f $wsrc/config.json || { echo 'MISSING checkpoint on $host: $wsrc'; exit 1; }
      mkdir -p $WORKER_ENGRAM_DIR && docker run --rm --network host \
      -v $wsrc:/models/DeepSeek-V4.1-Flash:ro \
      $wpack_extra \
      -v $WORKER_ENGRAM_DIR:/engram \
      -e DSV41_SOURCE=/models/DeepSeek-V4.1-Flash \
      --entrypoint python3 $IMAGE \
      /opt/dsv41/scripts/pack_engram.py --rank $idx --tp $TP_SIZE --out /engram" \
      || die "pack failed on $host"
    idx=$((idx + 1))
  done
  info "Engram shards packed on all 3 nodes"
}

case "$CMD" in
  serve|start|"") cmd_serve "$@" ;;
  doctor) cmd_doctor strict ;;
  pull) cmd_pull ;;
  build) cmd_build ;;
  pack) cmd_pack ;;
  download) cmd_download ;;
  share|mount) cmd_share ;;
  sync) cmd_sync ;;
  stop) cmd_stop "$@" ;;
  status) cmd_status ;;
  logs) cmd_logs "$@" ;;
  smoke) cmd_smoke ;;
  ncclcheck) "$ROOT/scripts/nccl_selfcheck.sh" "$@" ;;
  gate) cmd_gate "$@" ;;
  -h|--help|help) usage ;;
  *) die "unknown command: $CMD (try ./start.sh help)" ;;
esac

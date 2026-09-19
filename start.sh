#!/usr/bin/env bash
# start.sh — DeepSeek-V4.1-Flash on 3× DGX Spark (GB10 / SM121)
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

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Profiles: start.sh reads .env (3 Sparks, TP3); start-tp4.sh points ENV_FILE at
# .env.tp4 (4 Sparks, TP4) and gives that profile its own state/log dirs.
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
ENV_EXAMPLE="${ENV_EXAMPLE:-$ROOT/.env.example}"
if [[ ! -f "$ENV_FILE" ]]; then
  [[ -f "$ENV_EXAMPLE" ]] || { echo "missing $(basename "$ENV_EXAMPLE")" >&2; exit 1; }
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  echo "[dsv41] wrote $(basename "$ENV_FILE") from $(basename "$ENV_EXAMPLE") — edit IPs if needed"
fi
set -a
# shellcheck disable=SC1091
source "$ENV_FILE"
set +a

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
IMAGE="${IMAGE:-dsv41-3x-spark:local}"
HEAD_CTN="${HEAD_CTN:-dsv41-head}"
WORKER_CTN="${WORKER_CTN:-dsv41-worker}"
WORKER_DIR="${WORKER_DIR:-/home/${WORKER_USER}/dsv41-3x-spark}"

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
for _k in $(compgen -A variable NCCL_ 2>/dev/null || true); do
  case " NCCL_ALGO NCCL_BUFFSIZE NCCL_CROSS_NIC NCCL_CUMEM_HOST_ENABLE NCCL_DEBUG NCCL_DEBUG_SUBSYS NCCL_IB_DISABLE NCCL_IB_GID_INDEX NCCL_IB_HCA NCCL_IB_MERGE_NICS NCCL_IB_RETRY_CNT NCCL_IB_SUBNET_AWARE_ROUTING NCCL_IB_TIMEOUT NCCL_IB_TOS NCCL_IGNORE_CPU_AFFINITY NCCL_MAX_NCHANNELS NCCL_MIN_NCHANNELS NCCL_NET NCCL_NET_PLUGIN NCCL_PROTO NCCL_SET_THREAD_NAME NCCL_SHM_DISABLE NCCL_SOCKET_IFNAME NCCL_TUNER_THRESHOLD " in
    *" $_k ") ;;
    *) echo "[warn] 顶层 $_k 不在 start.sh 白名单，不会透传到容器——请写入 EXTRA_DOCKER_ENV（客户坑 9）" ;;
  esac
done

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
declare -A SGLANG_OVERLAY_MAP=(
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
)
# 代码来源（2026-09-16 起）：镜像内 vs 宿主逐文件 bind-mount。
#   0（默认，生产）＝ overlay 与 adapter/b12x/NCCL shim 都在镜像里 ⇒ 容器只剩**数据挂载**。
#     好处是结构清楚，且"改了盘上、容器仍看旧 inode"这一类漂移**从结构上消失**
#     （overlay-drift-check 报 drift=0 成为常态而不是例外）。
#   1（开发）＝ 逐文件覆盖，改完重启即可，不必重建镜像。代价：必须重建容器才看得到新字节
#     （逐文件 bind-mount 钉住 inode），且这类失效**任何缓存检查都看不出来**。
SGLANG_CODE_MOUNTS="${SGLANG_CODE_MOUNTS:-0}"
sglang_overlay_mounts() {   # $1 = nameref array to append -v args to
  local -n _o=$1
  local f
  [[ "$SGLANG_CODE_MOUNTS" = 1 ]] || return 0
  for f in "${!SGLANG_OVERLAY_MAP[@]}"; do
    if [[ -f "$SGLANG_OVERLAY_DIR/$f" ]]; then
      _o+=( -v "$SGLANG_OVERLAY_DIR/$f:/sgl-workspace/sglang/${SGLANG_OVERLAY_MAP[$f]}:ro" )
    fi
  done
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
  local idx=0 wip wgid rank wmodel wextra _ov _ev
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
    wov=""
    for _f in "${!SGLANG_OVERLAY_MAP[@]}"; do
      wov+=" $_f:${SGLANG_OVERLAY_MAP[$_f]}"
    done
    remote_on "$h" "
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
        CODE_VOL=\"-v \$HOME/dsv41-flash-dgxsparks/adapter:/opt/dsv41/adapter:ro -v \$HOME/dsv41-flash-dgxsparks/b12x-site:/opt/b12x:ro\"
      fi
      CACHE_VOL=''
      if [ '${SGLANG_CODE_MOUNTS}' = 1 ]; then
        CACHE_VOL=\"-v \$HOME/.cache:/root/.cache\"
      fi
      MODEL_SRC='$NFS_VOLUME'
      if [ '$WEIGHTS_MODE' = 'local' ]; then MODEL_SRC='$wmodel'; fi
      WEXTRA='$wextra'
      OVERLAY_VOL=''
      if [ '${SGLANG_CODE_MOUNTS}' = 1 ]; then
        for wpair in $wov; do
          wf=\${wpair%%:*}; wrel=\${wpair#*:}
          if [ -f \$HOME/dsv41-flash-dgxsparks/sglang-overlay/\$wf ]; then
            OVERLAY_VOL=\"\$OVERLAY_VOL -v \$HOME/dsv41-flash-dgxsparks/sglang-overlay/\$wf:/sgl-workspace/sglang/\$wrel:ro\"
          fi
        done
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
        \$CACHE_VOL \
        \$NCCL_VOL \$NCCL_ENV \$SHIM_VOL \\
$(worker_env_lines "$wip" "$wgid" "$rank")
        -e API_KEY=$(printf '%q' "$API_KEY") \\
        -e EXTRA_SGLANG_ARGS=$(printf '%q' "${EXTRA_SGLANG_ARGS:-}") \\
        $(printf '%q' "$IMAGE") run
    "
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
  while (( i < ${READY_TIMEOUT:-360} )); do
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
  local h
  for h in "${WORKER_HOSTS[@]}"; do
    echo "== worker $h =="
    remote_on "$h" "docker ps --filter name=$WORKER_CTN --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' ; test -f $COMMON_MODEL/config.json && echo weights:OK || echo weights:MISSING" || warn "status SSH $h failed"
    echo
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

usage() {
  sed -n '2,24p' "$0" | tr -d '#'
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

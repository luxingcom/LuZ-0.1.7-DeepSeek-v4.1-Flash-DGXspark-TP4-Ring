#!/usr/bin/env bash
# run_sd1_all.sh -- SD-1 full re-measurement chain, staged and logged.
#
# Runs on the head node. Each stage is a separate `docker exec` so a stage
# failure does not take the chain down with it, and each stage writes its own
# log plus a COMPLETE marker. Peak memory is sampled throughout: this is a GB10
# UMA box, so device pages and host pages come out of the same pool, and the
# only way to notice the pool filling is to watch it rather than the container.
#
# Stages are ordered shortest-headline-first:
#   de        the decode table this whole exercise is about
#   grammar   the guided-decoding cost, same channel
#   fp4_256   short-output arm for the indexer A/B (indexer currently ON)
#   gw        gateway vs direct, three arms
#   pr        the 30-cell prompt-rate matrix -- longest, runs last
#
# Subset and resume
# -----------------
#   STAGES=pr bash run_sd1_all.sh              run only the PR matrix
#   TAG=sd1-... STAGES=pr bash run_sd1_all.sh  ... into an existing run directory
#
# Both exist because a harness change invalidates exactly one stage, and re-running
# five to refresh one is not a trade anyone should have to make. Naming the same
# TAG puts the new stage next to the others so `render_report_tables.py` still
# finds every stage in one place; the run log is then **appended to**, never
# truncated, because the earlier stages' exit codes and timings are the record of
# the run being extended.
set -uo pipefail

STAGES="${STAGES:-de,grammar,fp4_256,gw,pr}"
TAG="${TAG:-sd1-$(date +%Y%m%dT%H%M%S)}"
SB="${DSV41_STATE:-$HOME/dsv41-flash-dgxsparks/state}"
RUNDIR="$SB/bench-results/$TAG"
CT=dsv41-head
mkdir -p "$RUNDIR"

if [ -f "$RUNDIR/run.log" ]; then
  echo "run_tag=$TAG (resumed) stages=$STAGES started=$(date -Is)" >> "$RUNDIR/run.log"
else
  echo "run_tag=$TAG" > "$RUNDIR/run.log"
  echo "host=$(hostname) started=$(date -Is)" >> "$RUNDIR/run.log"
fi

# --- memory sampler (host side; the pool is shared, so /proc/meminfo is the truth)
(
  while :; do
    awk -v t="$(date +%s)" '
      /MemTotal|MemFree|Cached:|SReclaimable:|Shmem:/ {
        v[$1]=$2
      }
      END {
        eff=v["MemFree:"]+v["Cached:"]+v["SReclaimable:"]-v["Shmem:"]
        printf "%s eff_free_kb=%d free_kb=%d cached_kb=%d shmem_kb=%d\n", t, eff, v["MemFree:"], v["Cached:"], v["SReclaimable:"], v["Shmem:"]
      }' /proc/meminfo >> "$RUNDIR/mem.log"
    sleep 30
  done
) & SAMPLER=$!
echo "sampler_pid=$SAMPLER" >> "$RUNDIR/run.log"

stage () {
  local name="$1"; local script="$2"; shift 2
  local t0=$(date +%s)
  echo "===== STAGE $name ($script) start $(date -Is) =====" | tee -a "$RUNDIR/run.log"
  docker exec \
    -e OUT_DIR="/state/bench-results/$TAG/$name" \
    -e RUN_TAG="$TAG" \
    "$@" "$CT" python3 "/state/sdbench/$script" >> "$RUNDIR/$name.log" 2>&1
  local rc=$?
  echo "===== STAGE $name exit=$rc elapsed=$(( $(date +%s) - t0 ))s $(date -Is) =====" \
    | tee -a "$RUNDIR/run.log"
  return $rc
}

want () {
  case ",$STAGES," in
    *",$1,"*) return 0 ;;
    *) echo "  (skipping stage $1: not in STAGES=$STAGES)" >> "$RUNDIR/run.log" ;;
  esac
  return 1
}

# stage name / script / env. Two stages share de_matrix_v3.py: the 256-token arm
# is the same measurement at a shorter budget, which is the point of an A/B.
want de       && stage de       de_matrix_v3.py -e TYPES=structured,prose,code,json -e CONCURRENCIES=1,2,4,8,16 -e WAVES=3 -e MAXTOK=2048
want grammar  && stage grammar  grammar_ab.py   -e CONCURRENCIES=1,2,4,8,16 -e WAVES=3 -e MAXTOK=2048
want fp4_256  && stage fp4_256  de_matrix_v3.py -e TYPES=code -e CONCURRENCIES=1,8,16 -e WAVES=3 -e MAXTOK=256
want gw       && stage gw       gw_ab_v2.py     -e ROUNDS=2
# The PR matrix is the one stage that needs REQUEST_TIMEOUT raised above the
# 3600 s default: prefill is one request at a time above CHUNKED_PREFILL_SIZE, so
# the 524288 row's 16th stream does not see its first token until ~5000 s.
# CHUNKED_PREFILL_SIZE is passed through so the harness can predict
# prefills-per-step from the same number the engine was launched with.
want pr       && stage pr       pr_matrix_v2.py -e PREFILL_SIZES=512,2048,8192,32768,131072,524288 -e CONCURRENCIES=1,2,4,8,16 -e WAVES=1 -e MAXNEW=1024 -e REQUEST_TIMEOUT=7200 -e CHUNKED_PREFILL_SIZE=4096 -e SAMPLES=512

kill $SAMPLER 2>/dev/null
echo "STAGES DONE ($STAGES) $(date -Is)" | tee -a "$RUNDIR/run.log"
echo "RUNDIR=$RUNDIR" | tee -a "$RUNDIR/run.log"

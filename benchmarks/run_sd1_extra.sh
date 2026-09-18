#!/usr/bin/env bash
# run_sd1_extra.sh -- the closure stages that run *after* the main chain.
#
# Three stages, shortest first:
#
#   cache     what a repeated prompt is actually worth, at 2k/32k/131k tokens. The
#             instrument that *prices* prefix reuse instead of asserting it exists.
#             Must not overlap a matrix: a 131k-token prefill injected into a C=1
#             cell is a contamination, not a diagnostic.
#   channel   chat vs native on an identical unconstrained prompt, interleaved. The
#             grammar A/B found the constrained arm faster at every concurrency, and
#             this stage removes the one remaining confound: whether the native
#             channel is simply slower for the same unconstrained request.
#   grammar2  the grammar A/B re-run. Unlike the first pass this one writes the
#             per-stream records, so the result is auditable below cell level.
#
# Usage:  TAG=sd1-... bash run_sd1_extra.sh      (defaults to a fresh tag)
set -uo pipefail

TAG="${TAG:-extra-$(date +%Y%m%dT%H%M%S)}"
SB="${DSV41_STATE:-$HOME/dsv41-flash-dgxsparks/state}"
RUNDIR="$SB/bench-results/$TAG"
CT=dsv41-head
mkdir -p "$RUNDIR"

# Append, never truncate: this script is normally pointed at the *same* RUNDIR as
# the main chain (`TAG=<main tag>`) so the renderer can find every stage in one
# place. A `>` here would overwrite run.log and destroy the main chain's stage
# timings and exit codes -- the record of the run it is meant to extend. The
# sampler below therefore also appends.
echo "run_tag=$TAG (extra stages) started=$(date -Is)" >> "$RUNDIR/run.log"
echo "host=$(hostname) extra_started=$(date -Is)" >> "$RUNDIR/run-extra.log"

# memory sampler -- a GB10 UMA box keeps device and host pages in one pool
(
  while :; do
    awk -v t="$(date +%s)" '
      /MemTotal|MemFree|Cached:|SReclaimable:|Shmem:/ { v[$1]=$2 }
      END { printf "%s eff_free_kb=%d free_kb=%d cached_kb=%d shmem_kb=%d\n", t,
            v["MemFree:"]+v["Cached:"]+v["SReclaimable:"]-v["Shmem:"],
            v["MemFree:"], v["Cached:"], v["SReclaimable:"], v["Shmem:"] }' \
      /proc/meminfo >> "$RUNDIR/mem.log"
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

stage cache    cache_effect_probe.py -e SIZES=2048,32768,131072
stage channel  channel_ab.py         -e CONCURRENCIES=1,16 -e WAVES=3 -e MAXTOK=2048
stage grammar2 grammar_ab.py         -e CONCURRENCIES=1,2,4,8,16 -e WAVES=3 -e MAXTOK=2048

kill $SAMPLER 2>/dev/null
echo "ALL DONE $(date -Is)" | tee -a "$RUNDIR/run.log"
echo "RUNDIR=$RUNDIR" | tee -a "$RUNDIR/run.log"

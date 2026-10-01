#!/usr/bin/env bash
# verify_fleet_distribution.sh -- prove the serving image is present, intact and
# IDENTICAL on all four nodes, before you trust a single benchmark number.
#
# Why this exists
# ---------------
# Three specific failures this script is built to catch, each of which has bitten
# this deployment:
#
#  1. **The empty-hash false green.** `docker image inspect … | sha256sum` on a
#     node where the image is ABSENT does not fail — it prints a perfectly
#     plausible constant, because it hashes empty input. Two nodes missing the
#     image agree with each other and the check passes. So the existence test runs
#     FIRST and the identity is never computed from a missing image.
#
#  2. **Verifying by a number that legitimately differs.** `docker images SIZE`,
#     `.Id` and `{{.Config}}` all differ between the head and the workers while the
#     content is identical (containerd's shared-layer accounting, and a config that
#     carries wall-clock). The only fleet-comparable value is the content identity:
#     sha256 of the layer list serialized exactly as
#     `{{join .RootFS.Layers " "}}` emits it, INCLUDING the trailing newline.
#     Drop the newline and you get a different, equally stable-looking value.
#
#  3. **A transport that "succeeded" on a truncated file.** scp/rsync exit 0 more
#     often than you would like. The sha256 of the tar is checked on each node, not
#     just at the destination you copied from.
#
# It is fail-closed: any node that cannot be reached, cannot answer, or disagrees
# makes the script exit non-zero. A check that cannot fail is not a check.
#
# Usage
#   ./verify_fleet_distribution.sh \
#       --image dsv41-sglang-optimized:0.2.9-ep1q2-fin2 \
#       --identity 355a5e45cb2725ae \
#       --nodes <head-node> <worker-rank1> <worker-rank2> <worker-rank3> \
#       [--tar /path/to/image.tar --tar-sha256 <hex>] \
#       [--user APP_USER]
#
#   --nodes takes a variadic list (one or more hostnames) and must be the LAST
#   option you pass, or be followed by another --flag; it consumes every following
#   token that does not start with --.
#
#   --identity is REQUIRED unless --expect-layer-count is given. This script will
#   not print a verdict from an inferred expectation.
#   --tar/--tar-sha256 are optional; supply them to also verify the on-disk archive.
#
# Exit codes
#   0  every node has the image, every identity matches, and it matches the expectation
#   1  a verification failure (absent image, mismatch, short file, unreachable node)
#   2  usage error, or an expectation that could not be established

set -u
set -o pipefail

IMAGE=""
IDENTITY=""
EXPECT_LAYERS=""
NODES=""
TAR=""
TAR_SHA=""
SSH_USER=""

# Constants that mean "nothing was there". Must never be accepted as an identity
# or as a match. (Kept in sync with scripts/verify_release_artifact.py.)
FALSE_EMPTY_SHA256_EMPTY="e3b0c44298fc1c14"   # sha256(b'')
FALSE_EMPTY_SHA256_NL="01ba4719c80b6fe9"      # sha256(b'\n')

usage() {
    sed -n '2,50p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --image)          IMAGE="${2:-}"; shift 2 ;;
        --identity)       IDENTITY="${2:-}"; shift 2 ;;
        --expect-layer-count) EXPECT_LAYERS="${2:-}"; shift 2 ;;
        --nodes)
            # Variadic: consume every following token that is not another flag.
            shift
            while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do
                NODES="$NODES $1"
                shift
            done
            ;;
        --tar)            TAR="${2:-}"; shift 2 ;;
        --tar-sha256)     TAR_SHA="${2:-}"; shift 2 ;;
        --user)           SSH_USER="${2:-}"; shift 2 ;;
        -h|--help)        usage ;;
        *) echo "unknown argument: $1" >&2; usage ;;
    esac
done
NODES="${NODES# }"

[ -n "$IMAGE" ] || { echo "FATAL: --image is required" >&2; usage; }
[ -n "$NODES" ] || { echo "FATAL: --nodes is required" >&2; usage; }

if [ -z "$IDENTITY" ] && [ -z "$EXPECT_LAYERS" ]; then
    cat >&2 <<'MSG'
FATAL: no expectation to check against.

Pass --identity <16-hex> (the value start.sh's preflight asserts fleet-wide), or
--expect-layer-count <n> if you have not yet established the identity.

This script deliberately refuses to print a verdict from an inferred expectation:
a check whose expected value is derived from the thing it checks cannot fail, and
that is exactly the failure mode it exists to prevent.
MSG
    exit 2
fi

if { [ -n "$TAR" ] && [ -z "$TAR_SHA" ]; } || { [ -z "$TAR" ] && [ -n "$TAR_SHA" ]; }; then
    echo "FATAL: --tar and --tar-sha256 must be given together" >&2
    exit 2
fi

SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new"
[ -n "$SSH_USER" ] && SSH_OPTS="$SSH_OPTS -l $SSH_USER"

PASS=0
FAIL=0
ANSWERED_NODES=""          # newline-separated, in probe order
declare -A SEEN_IDENTITY

note()  { printf '  %s\n' "$*"; }
ok()    { printf '  [ OK ]   %s\n' "$*"; PASS=$((PASS + 1)); }
bad()   { printf '  [FAIL]   %s\n' "$*"; FAIL=$((FAIL + 1)); }
warn()  { printf '  [WARN]   %s\n' "$*"; }

echo "=== fleet image verification ==="
echo "image      : $IMAGE"
echo "identity   : ${IDENTITY:-(not given -- layer count only)}"
echo "nodes      : $NODES"
[ -n "$TAR" ] && echo "tar        : $TAR  (sha256 $TAR_SHA)"
echo

# ---------------------------------------------------------------------------
# Per-node probe. Everything runs remotely in one SSH round-trip.
# ---------------------------------------------------------------------------
probe_node() {
    local node="$1"

    # shellcheck disable=SC2029  # we *want* local expansion of these variables
    ssh $SSH_OPTS "$node" \
        "IMAGE='$IMAGE' EXPECT_LAYERS='$EXPECT_LAYERS' TAR='$TAR' TAR_SHA='$TAR_SHA' bash -s" \
        <<'REMOTE'
set -u

# --- 1. presence, before anything is computed from the image -----------------
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "STATE ABSENT"
    exit 0
fi
echo "STATE PRESENT"

# --- 2. layer count ----------------------------------------------------------
layers=$(docker image inspect -f '{{len .RootFS.Layers}}' "$IMAGE" 2>/dev/null)
echo "LAYERS $layers"

# --- 3. content identity: the ONE fleet-comparable serialization -------------
# Byte-for-byte the formula start.sh's preflight uses: space-joined diffIDs plus
# docker's own trailing newline. The trailing newline is load-bearing -- without
# it the same layer list yields a different, equally stable-looking value.
ident=$(docker image inspect -f '{{join .RootFS.Layers " "}}' "$IMAGE" 2>/dev/null \
        | sha256sum | cut -c1-16)
echo "IDENTITY $ident"

# The newline-stripped variant, printed ONLY so a mismatch can be diagnosed on
# the spot rather than turning into a hunt.
ident_nonl=$(docker image inspect -f '{{join .RootFS.Layers " "}}' "$IMAGE" 2>/dev/null \
        | tr -d '\n' | sha256sum | cut -c1-16)
echo "IDENTITY_NONL $ident_nonl"

# --- 4. the archive on this node, if we were told about one ------------------
if [ -n "$TAR" ]; then
    if [ ! -f "$TAR" ]; then
        echo "TAR MISSING"
    else
        got_sha=$(sha256sum "$TAR" | cut -d' ' -f1)
        got_size=$(stat -c '%s' "$TAR")
        echo "TAR_SHA $got_sha"
        echo "TAR_SIZE $got_size"
    fi
fi
REMOTE
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
for node in $NODES; do
    echo "--- $node ---"

    if ! out=$(probe_node "$node" 2>&1); then
        bad "$node: ssh failed or probe did not complete"
        note "$(printf '%s' "$out" | tail -3 | tr '\n' ' ')"
        echo
        continue
    fi

    state=$(printf '%s\n' "$out" | awk '/^STATE /{print $2}')
    if [ "$state" != "PRESENT" ]; then
        bad "$node: image $IMAGE is ABSENT"
        echo
        continue
    fi

    layers=$(printf '%s\n' "$out"  | awk '/^LAYERS /{print $2}')
    ident=$(printf '%s\n'  "$out"  | awk '/^IDENTITY /{print $2}')
    ident_nl=$(printf '%s\n' "$out" | awk '/^IDENTITY_NONL /{print $2}')

    # 3a. empty-hash double-guard
    if [ -z "$ident" ]; then
        bad "$node: identity could not be computed (empty output)"
        echo; continue
    fi
    if [ "${ident:0:16}" = "$FALSE_EMPTY_SHA256_EMPTY" ] \
    || [ "${ident:0:16}" = "$FALSE_EMPTY_SHA256_NL" ]; then
        bad "$node: identity is a FALSE-EMPTY constant ($ident) -- image is not really there"
        echo; continue
    fi

    # 3b. identity vs expectation
    if [ -n "$IDENTITY" ]; then
        if [ "$ident" = "$IDENTITY" ]; then
            ok "$node: identity $ident matches"
        elif [ "$ident_nl" = "$IDENTITY" ]; then
            bad "$node: identity $ident != $IDENTITY, but the newline-stripped variant MATCHES."
            note "this node's layer list is right; the serialization is not."
            note "check the docker CLI version on this node -- the formula is the one"
            note "that emits a trailing newline."
        else
            bad "$node: identity $ident != expected $IDENTITY"
            note "(and the newline-stripped variant $ident_nl does not match either,"
            note " so this is a genuinely different layer list, not a formatting difference)"
        fi
    fi

    # 3c. layer count cross-check
    if [ -n "$EXPECT_LAYERS" ] && [ "$layers" != "$EXPECT_LAYERS" ]; then
        bad "$node: layer count $layers != expected $EXPECT_LAYERS"
    fi

    # 3d. archive on this node
    if [ -n "$TAR" ]; then
        tar_sha=$(printf '%s\n' "$out" | awk '/^TAR_SHA /{print $2}')
        tar_size=$(printf '%s\n' "$out" | awk '/^TAR_SIZE /{print $2}')
        if [ -z "$tar_sha" ]; then
            bad "$node: archive $TAR not found on this node"
        elif [ "$tar_sha" = "$TAR_SHA" ]; then
            ok "$node: archive sha256 matches ($tar_size bytes)"
        else
            bad "$node: archive sha256 $tar_sha != $TAR_SHA"
            note "the file on this node is not the file you think you copied"
        fi
    fi

    SEEN_IDENTITY["$node"]="$ident"
    ANSWERED_NODES="$ANSWERED_NODES$node
"
    echo
done

# ---------------------------------------------------------------------------
# Cross-node agreement
# ---------------------------------------------------------------------------
echo "=== cross-node agreement ==="
ANSWERED_NODES="${ANSWERED_NODES%
}"
if [ -z "$ANSWERED_NODES" ]; then
    bad "no node answered -- nothing was verified"
else
    n_answered=$(printf '%s\n' "$ANSWERED_NODES" | wc -l)
    distinct=$(for n in $ANSWERED_NODES; do printf '%s\n' "${SEEN_IDENTITY[$n]}"; done | sort -u | wc -l)
    if [ "$distinct" -eq 1 ]; then
        first=$(for n in $ANSWERED_NODES; do printf '%s\n' "${SEEN_IDENTITY[$n]}"; done | head -1)
        ok "all $n_answered answering nodes report one identity: $first"
    else
        bad "$distinct DIFFERENT identities across the fleet:"
        for n in $ANSWERED_NODES; do
            printf '           %-16s %s\n' "$n" "${SEEN_IDENTITY[$n]}"
        done
    fi
fi
# Any node in the request list that never answered is already counted as a FAIL
# above; state it plainly so the summary cannot be read as "all four checked".
for node in $NODES; do
    case "
$ANSWERED_NODES
" in
        *"
$node
"*) : ;;
        *) warn "$node did not answer -- it contributed no evidence either way" ;;
    esac
done

echo
echo "=== result ==="
printf '  checks passed: %d\n  checks failed: %d\n' "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
    echo "  RESULT: FAIL  (exit 1)"
    exit 1
fi
echo "  RESULT: PASS  (exit 0)"
exit 0

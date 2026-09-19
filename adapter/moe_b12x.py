"""Route SGLang's flashinfer_mxfp4 MoE fused op to b12x fused_moe (W4A16, EP).

Gate: DSV41_MOE_B12X=1 (unset/0 keeps SGLang's FlashInfer CUTLASS W4A8 path).

Activation caliber: DSV41_MOE_B12X_QUANT (default a8 = w4a8_mx).

Why b12x at small/mid M (bake-off 2026-09-14, state-tp4/moe-bakeoff.json, real
layer-2 weights, single local shard E=192 K=5120 N=2304 topk=6):
M=6 -10%, M=48 -7.7%, M=256 -8.1% (a8), M=2048 -5.2% (a8). a16 runs behind a8
everywhere measured and at M=2048 is +7.2% SLOWER than FI CUTLASS W4A8 --
the original header claimed "ahead at every M (w4a16)" by misreading this
2048 row (the -5.2% is the a8 figure). W4A8 is also the deployment directive,
so a8 is the default.

Why FI above DSV41_MOE_B12X_MMAX (default 2048): the bake-off never measured
M>2048 (=chunked_prefill_size at the time). When chunk moved to 4096-8192,
prefill rode the extrapolation and a customer long-input benchmark (PR-v3,
2026-09-19) showed FlashInfer CUTLASS W4A8 ahead by a margin that GROWS with
input length (+30% at 8K input, +84% at 128K) -- activation bytes (bf16 in
a16 = 2x W4A8) scale with M while expert weights amortize, plus b12x tiles
are small-M specialized. m>MMAX is therefore delegated to the preserved
original FlashInfer entry (W4A8) instead of a b12x bucket. MMAX=0 disables
b12x entirely (all-FI); MMAX huge restores all-b12x.

Our a2a=none topology is replicated-input EP: every rank sees the same bf16
activations and GLOBAL topk_ids, computes its local expert block, and the
caller all-reduces partial outputs -- exactly the contract of b12x fused_moe
(expert block + partial output, no collectives).

Two hooks (see sitecustomize):
  * quantization.mxfp4_flashinfer_cutlass_moe: snapshot the RAW e8m0 block
    scales before SGLang's process_weights_after_loading interleaves them
    in place (b12x wants the checkpoint-order scales).
  * moe_runner.flashinfer_cutlass: swap FusedOpPool's ("none",
    "flashinfer_mxfp4") entry for ours (dict write; register_fused_func
    refuses duplicates).

Layout note (cross-lib probe, relerr 0.0186): SGLang stacks w13 as
[w1; w3] == b12x W13Layout.W13. Do not "fix" this to W31.
swiglu: ActivationSpec(nonlinearity="silu", swiglu_limit=10.0) matches the
FI Swiglu activation with the per-expert limit tensor.
"""
import logging
import os

import torch

logger = logging.getLogger(__name__)

_FUSED_KEY = ("none", "flashinfer_mxfp4")
_raw_scales = {}      # w13_scale.data_ptr() -> (raw_w13_sf, raw_w2_sf)
_geom_states = {}     # geometry key -> _GeometryState (one per expert geometry)
_layer_states = {}    # w13_weight.data_ptr() -> _LayerState
_swapped = False


def _enabled() -> bool:
    value = os.environ.get("DSV41_MOE_B12X", "").strip().lower()
    return value in ("1", "true", "on", "w4a16", "ep")


def _quant_mode():
    """Activation caliber: a8 (w4a8_mx, default) or a16.

    b12x planning derives the recipe from the source format + activation mode;
    for MXFP4_E8M0_K32 both w4a16 and w4a8_mx are legal (A8 quantizes the
    activations to MXFP8 in-kernel with dynamic per-block scales, no static
    calibration). bake-off M=2048: a8 39.2ms vs a16 44.4ms (-11.7%); a8 is
    also ahead of a16 at every other measured M and matches the W4A8
    deployment directive -- default since 2026-09-19 (was a16).
    """
    value = os.environ.get("DSV41_MOE_B12X_QUANT", "a8").strip().lower()
    if value in ("a8", "w4a8", "w4a8_mx"):
        return "a8"
    if value not in ("a16", "w4a16", ""):
        logger.warning("DSV41 MoE b12x: DSV41_MOE_B12X_QUANT=%r unknown; "
                       "using a16", value)
    return "a16"


_QUANT = _quant_mode()


# --- bucket ladder ----------------------------------------------------------
# m <= _EXACT_MAX takes an exact-M plan. Decode/verify shapes are a closed set
# (the captured graph bs list x (k+1) rows) and must NOT ride a big bucket:
# a capacity-2048 plan at M=1 cost ~24x (boot24: c1 2.4 t/s vs 57.2).
#
# m > _EXACT_MAX rounds UP to the next ladder entry. The ladder is bounded by
# construction. The previous form (1 << (m - 1).bit_length()) minted a fresh
# capacity for every unusual prefill length -- an unbounded JIT-compile surface
# that froze ranks mid-prefill while peers waited in collectives (boot22/23).
# An m above the last entry is a configuration error and raises with a fix-it
# message rather than silently becoming a new plan key.
#
# Production prefill batch tokens measured over every boot log (2026-09-14):
# 256 x652, 512 x20, 768 x19, 1024, 1280 x34, 1536, 1792, 2048 x34 -- zero
# above chunked_prefill_size. Override with DSV41_MOE_B12X_CAPS=256,512,...,N
# when chunked_prefill_size is raised.
#
# 128 is the first rung on purpose: mixed batches (decode rows + a partial
# prefill chunk) land on arbitrary m, so 97..128 is reachable and must not be
# rounded up into 256 -- that would make the kernel slower for exactly the
# m-range the ladder exists to serve.
_EXACT_MAX = 96
# a8 ladder deviation (2026-09-15): b12x re-plans per call with the ACTUAL m
# (b12x_moe_fp4 -> plan_tp_moe_execution(num_tokens=m)) and validates the
# capacity-rung workspace against it. tile_m shrinks at routed-row boundaries
# (16*E / 36*E at topk 6 -> m=512 / m=1152), so tile demand is NON-monotonic
# in m: an m just below a boundary needs more physical tiles than the rung
# above planned. cap 2048 serving m in (1024,1152] crashed (383 < 392 tiles).
# The 2304 rung plans 407 tiles >= the whole band's peak; a16 workspaces plan
# per token-count and are unaffected by this. Verified by dense boundary
# sweep: bench/moe_a8_ladder_sweep.py (493 m values, 0 failures).
_CAPS_A16 = (128, 256, 512, 1024, 2048)
_CAPS_A8 = (128, 256, 512, 1024, 2304, 4096)
_CAPS = _CAPS_A8 if _QUANT == "a8" else _CAPS_A16


def _parse_ladder() -> tuple:
    raw = os.environ.get("DSV41_MOE_B12X_CAPS", "").strip()
    if not raw:
        return _CAPS
    try:
        caps = tuple(sorted({int(v) for v in raw.replace(" ", "").split(",") if v}))
    except ValueError:
        logger.warning("DSV41 MoE b12x: DSV41_MOE_B12X_CAPS=%r unparsable; using %s",
                       raw, _CAPS)
        return _CAPS
    if not caps or caps[0] <= _EXACT_MAX:
        logger.warning("DSV41 MoE b12x: ladder %s must start above _EXACT_MAX=%d; "
                       "using %s", list(caps), _EXACT_MAX, _CAPS)
        return _CAPS
    return caps


_LADDER = _parse_ladder()
_MAX_CAP = _LADDER[-1]

# Hybrid routing: m above this delegates to the preserved FlashInfer CUTLASS
# W4A8 entry. ARMED ONLY under dual-hold: single-hold (default) neutralizes
# the SM120 block_scale_interleave at load time, so the live scale tensors
# stay in CHECKPOINT order -- b12x's format, NOT the interleaved layout the
# FlashInfer CUTLASS kernel consumes. Delegating on those weights computes
# with wrongly-laid-out scales and silently corrupts long-prefill KV
# (needle gate failure, 2026-09-19: needle found but numeric suffix dropped,
# greedy decode degenerating -- every m>MMAX chunk was poisoned).
# Default is therefore effectively all-b12x; a prefill-heavy deployment that
# wants pure FlashInfer W4A8 should set DSV41_MOE_B12X=0 (hook never installs,
# weights interleave normally). MMAX only makes sense with
# DSV41_MOE_B12X_DUAL_HOLD=1 (costs ~4.3GiB/rank) after a window sweep.
_MMAX = int(os.environ.get("DSV41_MOE_B12X_MMAX", "999999") or 999999)
_ORIG_FI_FUNC = None          # preserved ("none","flashinfer_mxfp4") entry
_fallback_logged = set()      # avoid per-call log spam: one line per m seen

# Telemetry: DSV41_MOE_B12X_STATS=<n> logs max_m / bucket set every n calls.
# It exists to prove the ladder bound holds ("no plan key above _MAX_CAP") and
# to size the next ladder step from data instead of guesswork.
_STAT_EVERY = int(os.environ.get("DSV41_MOE_B12X_STATS", "0") or 0)
_calls = 0
_max_m = 0
_caps_seen = set()


def _cap_for(m: int):
    """Smallest ladder bucket that can hold m, or None if m is out of range."""
    if m <= _EXACT_MAX:
        return m
    for cap in _LADDER:
        if m <= cap:
            return cap
    return None


def _note_call(m: int) -> None:
    global _calls, _max_m
    _calls += 1
    if m > _max_m:
        _max_m = m
    cap = _cap_for(m)
    _caps_seen.add(cap if cap is not None else -m)
    if _STAT_EVERY and _calls % _STAT_EVERY == 0:
        logger.info(
            "DSV41 MoE b12x stats: calls=%d max_m=%d buckets=%s over=%d geom=%d",
            _calls, _max_m, sorted(c for c in _caps_seen if c > 0),
            sum(1 for c in _caps_seen if c < 0), len(_geom_states),
        )


def _geometry_key(e_local, k, n, device) -> tuple:
    return (e_local, k, n, torch.device(device).type,
            torch.device(device).index, _QUANT)


# 2026-09-19 single-hold: with b12x enabled it is the SOLE consumer of the
# routed-expert E8M0 scales, so we neutralize the SM120 in-place interleave
# (call-window-scoped identity on flashinfer.block_scale_interleave -- global
# patching is unsafe: fp8.py/mxfp4.py serve other layers through the same
# symbol) and register the LIVE tensors (zero-copy detach alias) instead of
# cloning checkpoint order beside the interleaved copy. Saves the ~212 MiB/layer
# clone pair (~4.5 GB; A/B 2026-09-19: ON boot avail 15.22 vs OFF 20.45 GB).
# Kill-switch: DSV41_MOE_B12X_DUAL_HOLD=1 restores v8-and-earlier dual-hold.
_DUAL_HOLD = os.environ.get("DSV41_MOE_B12X_DUAL_HOLD", "0") == "1"


def _interleave_symbol():
    try:
        import flashinfer
        return flashinfer, getattr(flashinfer, "block_scale_interleave", None)
    except Exception:
        return None, None


def install_scale_snapshot(module):
    """Hook for sglang.srt.layers.quantization.mxfp4_flashinfer_cutlass_moe."""
    if not _enabled():
        return
    original = module.Mxfp4FlashinferCutlassMoEMethod.process_weights_after_loading

    def wrapped(self, layer, *args, **kwargs):
        # Layer stores the E8M0 scales as *_scale_inv; quant_info later passes
        # the SAME tensors as w13/w2_weight_scale (same data_ptr).
        raw13 = getattr(layer, "w13_weight_scale_inv", None)
        raw2 = getattr(layer, "w2_weight_scale_inv", None)
        have = isinstance(raw13, torch.Tensor) and isinstance(raw2, torch.Tensor)
        fi_mod, fi_inter = _interleave_symbol()
        single = have and not _DUAL_HOLD and fi_inter is not None
        if have:
            if single:
                # interleave will be neutralized below: the live tensors stay
                # in checkpoint order, which IS what b12x consumes -- alias.
                pair = (raw13.detach(), raw2.detach())
                if not _raw_scales:  # 诊断：仅首个注册打印物理属性（2026-09-19）
                    for _nm, _t in (("raw13", raw13), ("raw2", raw2)):
                        logger.info(
                            "DIAG %s: shape=%s off=%s stride=%s contig=%s ptr%%256=%s "
                            "leaf=%s grad=%s storage_nbytes=%s tensor_nbytes=%s",
                            _nm, tuple(_t.shape), _t.storage_offset(), tuple(_t.stride()),
                            _t.is_contiguous(), _t.data_ptr() % 256, _t.is_leaf,
                            _t.requires_grad, _t.untyped_storage().nbytes(), _t.numel() * _t.element_size())
            else:
                # dual-hold (v8 behavior, or flashinfer symbol missing): clone
                # checkpoint order, let the SM120 branch interleave in place.
                pair = (raw13.detach().clone(), raw2.detach().clone())
            _raw_scales[raw13.data_ptr()] = pair
            _raw_scales[raw2.data_ptr()] = pair
        if single:
            # Scope the identity strictly to this call: weight loading is
            # single-threaded per rank, and only the MoE method's own w13/w2
            # interleaves can run inside original() here. Other consumers
            # (fp8.py dense path, mxfp4.py) run outside this window.
            fi_mod.block_scale_interleave = lambda t: t
            try:
                return original(self, layer, *args, **kwargs)
            finally:
                fi_mod.block_scale_interleave = fi_inter
        return original(self, layer, *args, **kwargs)

    module.Mxfp4FlashinferCutlassMoEMethod.process_weights_after_loading = wrapped
    logger.info("DSV41 MoE b12x: raw scale snapshots armed (%s, hold=%s); ladder "
                "exact<=%d caps=%s", _QUANT,
                "dual" if _DUAL_HOLD else "single", _EXACT_MAX, list(_LADDER))


class _GeometryState:
    """b12x weight plan and execution buckets shared by one expert geometry.

    b12x's ExecutionPlan is tensor-free by design -- it plans scratch and launch
    variants "without compiling CUDA launches", and the expert weights ride
    along on every bind(). Its bind() only identity-checks the WeightPlan object,
    so one plan per geometry can serve all 37 target layers.

    Scratch is per-call self-clearing by contract: the kernel prologue zeros its
    counters and queues, and the launch wrapper re-zeros the barrier scalars in
    place. Sequential reuse is therefore the intended lifetime, and per-layer
    scratch would cost 199.0 MB at cap 2048 x 37 layers = 8.1 GB of unified
    memory competing with the KV pool.

    Only the scratch/execution plans are shared. Each layer keeps its own output
    buffer (run() returns a view of it), so nothing can be overwritten before the
    caller's combine has consumed it.

    Threading: valid only while two MoE layers never run concurrently. Two-batch
    overlap is not enabled; if it is ever turned on, scratch must go per-layer.
    """

    def __init__(self, weight_plan, key):
        self.weight_plan = weight_plan
        self.key = key
        self.experts = None       # anchor PreparedExperts for plan_execution
        self.buckets = {}         # (cap, topk) -> (exe, scratch)

    def bucket(self, fm, cap, topk, device):
        entry = self.buckets.get((cap, topk))
        if entry is None:
            exe = fm.plan_execution(
                experts=self.experts,
                capacity=fm.ExecutionCapacity(max_tokens=cap, top_k=topk),
            )
            fm.prewarm(exe)
            specs = exe.scratch_specs()
            if len(specs) == 1:
                scratch = torch.empty(specs[0].shape, dtype=specs[0].dtype,
                                      device=specs[0].device)
            else:
                scratch = {s.name: torch.empty(s.shape, dtype=s.dtype,
                                               device=s.device)
                           for s in specs}
            entry = (exe, scratch)
            self.buckets[(cap, topk)] = entry
            logger.info("DSV41 MoE b12x: bucket cap=%d topk=%d ready "
                        "(geometry %s, %d buckets)",
                        cap, topk, self.key, len(self.buckets))
        return entry


class _LayerState:
    """Per-layer expert weights, geometry reference, and output buffers."""

    def __init__(self, quant_info):
        from b12x.moe import fused_moe as fm

        self.fm = fm
        w13 = quant_info.w13_weight                     # [E, 2N, K/2] int8
        w2 = quant_info.w2_weight                       # [E, K, N/2]
        self.e_local = int(w13.shape[0])
        self.n = int(w13.shape[1] // 2)
        self.k = int(w2.shape[1])                  # [E, K, N/2]: dim1 is unpacked K
        self.ep_size = int(getattr(quant_info, "moe_ep_size", 1) or 1)
        self.ep_rank = int(getattr(quant_info, "moe_ep_rank", 0) or 0)
        self.e_global = self.e_local * self.ep_size
        self.device = w13.device
        self.dtype = torch.bfloat16
        raw = _raw_scales.get(quant_info.w13_weight_scale.data_ptr())
        if raw is None:
            raise RuntimeError(
                "moe_b12x: raw scales missing -- process_weights_after_loading "
                "ran before the adapter hook; check sitecustomize wiring"
            )
        raw13, raw2 = raw

        key = _geometry_key(self.e_local, self.k, self.n, self.device)
        geom = _geom_states.get(key)
        if geom is None:
            ones = torch.ones(self.e_local, dtype=torch.float32, device=w13.device)
            source = fm.PackedSource(
                format=fm.PackedSourceFormat.MXFP4_E8M0_K32,
                w13_layout=fm.W13Layout.W13,            # probe-verified vs FI
            )
            act = fm.ActivationSpec(
                mode=fm.ActivationMode.A8 if _QUANT == "a8"
                else fm.ActivationMode.A16,
                nonlinearity="silu",
                io_dtype=torch.bfloat16,
                swiglu_limit=10.0,
            )
            geo = fm.MoEGeometry(
                num_experts=self.e_local,
                hidden_size=self.k,
                intermediate_size=self.n,
            )
            geom = _GeometryState(
                fm.plan_weights(source=source, activation=act, geometry=geo), key)
            _geom_states[key] = geom
            logger.info("DSV41 MoE b12x: geometry registered E=%d K=%d N=%d",
                        self.e_local, self.k, self.n)
        else:
            ones = torch.ones(self.e_local, dtype=torch.float32, device=w13.device)
        packed = fm.PackedWeights(
            w13=w13.view(torch.uint8),
            w2=w2.view(torch.uint8),
            w13_block_scales=raw13,
            w2_block_scales=raw2,
            w13_global_scales=ones,
            w2_global_scales=ones,
        )
        # Every layer of a geometry must share the SAME WeightPlan object: the
        # public bind() identity-checks experts.plan against the plan's experts.
        # Keep the PreparedExperts object itself: plan_execution type-checks it.
        self.experts = fm.prepare_weights(plan=geom.weight_plan, weights=packed)
        if geom.experts is None:
            geom.experts = self.experts
        self.geom = geom
        self.outs = {}                              # cap -> [cap, k] bf16
        # Build every ladder bucket at load time for the target layers: the
        # compiling cost used to land on the first request (~40s of TTFT, which
        # poisons benches) and scratch is shared, so all four are cheap. The 3
        # draft layers (E=64) keep their buckets demand-built.
        if self.e_local > 64:
            for cap in _LADDER:
                self.geom.bucket(self.fm, cap, 6, self.device)
        logger.info(
            "DSV41 MoE b12x: layer ready E=%d K=%d N=%d ep=%d/%d",
            self.e_local, self.k, self.n, self.ep_rank, self.ep_size,
        )

    def run(self, x, topk_ids, topk_weights):
        m, topk = int(topk_ids.shape[0]), int(topk_ids.shape[1])
        cap = _cap_for(m)
        if cap is None:
            raise RuntimeError(
                "moe_b12x: prefill batch of %d tokens exceeds the largest MoE "
                "bucket (%d). Raise DSV41_MOE_B12X_CAPS (now %s) or lower "
                "CHUNKED_PREFILL_SIZE." % (m, _MAX_CAP, list(_LADDER))
            )
        _note_call(m)
        exe, scratch = self.geom.bucket(self.fm, cap, topk, self.device)
        out = self.outs.get(cap)
        if out is None:
            # Caller-owned output: graph capture refuses self-allocated outputs.
            out = torch.empty(cap, self.k, dtype=self.dtype, device=self.device)
            self.outs[cap] = out
        # EP2 with a2a=none: every rank sees GLOBAL topk_ids. Keep this rank's
        # expert block; non-local slots get zero weight so they contribute
        # nothing to the partial output the caller all-reduces.
        lo = self.ep_rank * self.e_local
        local = (topk_ids >= lo) & (topk_ids < lo + self.e_local)
        ids = torch.where(local, topk_ids - lo,
                          torch.zeros_like(topk_ids)).to(torch.int32)
        w = torch.where(local, topk_weights,
                        torch.zeros_like(topk_weights)).to(torch.float32)
        b = self.fm.bind(exe, scratch=scratch, a=x, experts=self.experts,
                         topk_weights=w, topk_ids=ids, output=out[:m])
        self.fm.run(binding=b)
        return out[:m]


def install(module):
    """Hook for sglang.srt.layers.moe.moe_runner.flashinfer_cutlass."""
    if not _enabled():
        return
    global _swapped
    if _swapped:
        return
    from sglang.srt.layers.moe.moe_runner.base import FusedOpPool
    if _FUSED_KEY not in FusedOpPool._fused_funcs:
        logger.warning("DSV41 MoE b12x: fused key %s absent; not installed",
                       _FUSED_KEY)
        return
    global _ORIG_FI_FUNC
    _ORIG_FI_FUNC = FusedOpPool._fused_funcs[_FUSED_KEY]
    FusedOpPool._fused_funcs[_FUSED_KEY] = _b12x_fused_func
    _swapped = True
    logger.info("DSV41 MoE b12x: fused func swapped (%s, ladder=%s, "
                "fi-fallback=%s)", _QUANT, list(_LADDER),
                "mmax=%d" % _MMAX if _DUAL_HOLD else "off (single-hold "
                "scales are checkpoint-order; FI would misread them)")


def _b12x_fused_func(dispatch_output, quant_info, runner_config):
    from sglang.srt.layers.moe.token_dispatcher.standard import (
        StandardCombineInput,
    )
    from sglang.srt.layers.moe.topk import TopKOutputChecker

    x = dispatch_output.hidden_states
    topk_output = dispatch_output.topk_output
    if TopKOutputChecker.format_is_bypassed(topk_output):
        topk_output = topk_output.to_standard()

    # Hybrid routing (2026-09-19): ONLY under dual-hold. Single-hold leaves
    # the live scales in checkpoint order (see _MMAX comment) -- delegating to
    # the FlashInfer entry then corrupts long-prefill KV. Under single-hold
    # every m rides the b12x ladder (start.sh auto-extends CAPS to chunk).
    m = int(topk_output.topk_ids.shape[0])
    if m > _MMAX and _DUAL_HOLD:
        if _ORIG_FI_FUNC is not None:
            if m not in _fallback_logged:
                _fallback_logged.add(m)
                logger.info(
                    "DSV41 MoE b12x: m=%d > MMAX=%d -> FlashInfer CUTLASS "
                    "W4A8 entry (a8 ladder caps at %d)", m, _MMAX, _MAX_CAP,
                )
            return _ORIG_FI_FUNC(dispatch_output, quant_info, runner_config)
        # No preserved entry (install raced?): refuse to bucket beyond the
        # measured range rather than silently regress.
        raise RuntimeError(
            "moe_b12x: m=%d > MMAX=%d and the original FlashInfer entry was "
            "not preserved at install time; set DSV41_MOE_B12X=0 or "
            "DSV41_MOE_B12X_MMAX >= %d" % (m, _MMAX, m)
        )

    state = _layer_states.get(quant_info.w13_weight.data_ptr())
    if state is None:
        state = _LayerState(quant_info)
        _layer_states[quant_info.w13_weight.data_ptr()] = state
    out = state.run(x, topk_output.topk_ids, topk_output.topk_weights)
    return StandardCombineInput(hidden_states=out)

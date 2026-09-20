# Release Notes — v0.2.4 (2026-09-20)

Appended-form release report. All other documents in this release are overwritten
in place, per repo convention.

**Baseline:** the previously published repo state (`main` @ `db8c572`, tag `v0.2.3`,
image content identity `4ebef21b6aedbd70`). This release does **not** change the
image — the two engineering commits land on `main` and the operator documentation
is refreshed. The headline change is a **correction**: the MoE b12x default that
v0.2.2-era docs described as "b12x ahead at every M" was based on a mislabeled
bake-off reading, and is now documented with the full per-M table and the
regression it caused.

## 1. Engineering commits landed (2)

| commit | area | what changed |
|---|---|---|
| `89a74f7` | function-call | **Port of vLLM #52645 truncation semantics to the DSML detectors** (`sglang-overlay/deepseekv32_detector.py`, new; `deepseekv41_detector.py`, v41 subclass with zero parse override; `start.sh` overlay map +2 entries). Three guarantees for DeepSeek-V3.2/V4.1 DSML tool-call streaming: (1) **no half-commit** — the invoke name is emitted only when its block completes, so a `max_tokens` truncation yields zero tool_calls instead of an empty-args call; (2) **finish() flush** — un-parsed buffer at stream end returns to content (was silently discarded) with full DSML structural-token stripping; (3) **anti-double-emit** — the preamble offset resets after buffer consumption so it never slices into the trailing closer. Offline stub suite 13/13. |
| `7161bc7` | MoE | **`adapter/moe_b12x.py`: W4A8 default + safe hybrid fallback gating.** The production default stays `DSV41_MOE_B12X_QUANT=a8` with the full-b12x MMAX, but the docstring now carries the real per-M bake-off numbers (see §2), and the MMAX→FlashInfer hybrid route is **gated behind `DSV41_MOE_B12X_DUAL_HOLD=1`** — it must not arm under single-hold, where it silently corrupts large-M KV (§2). |

## 2. The large-M b12x correction (why two docs changed)

A third-party PR-v3 evaluation on this repo's image found that disabling b12x
(`DSV41_MOE_B12X=0`, i.e. all-FlashInfer CUTLASS W4A8) **increases long-input
prefill throughput monotonically with length**: ≈0 % at 2 K, +30–42 % at 8 K,
+56–73 % at 32 K, +84–89 % at 128 K (vs upstream-equivalent accounting).
Root cause chain, all three links verified on 2026-09-19:

1. **The crossover is in our own bake-off data.** With real layer-2 weights
   ([`docs/operators/moe-bakeoff-20260914.json`](../operators/moe-bakeoff-20260914.json)),
   b12x W4A16 is −10 % vs FI at M=6 but **+7.2 % at M=2048** (already slower);
   b12x W4A8 is −10 % → −5.2 % over the same span. The bake-off's M range
   stopped at 2048 — which equaled the chunk size *at the time*.
2. **The adapter docstring mislabeled a8 numbers as a16**, making "W4A16 ahead at
   every M" the documented justification for the b12x default. That claim only
   holds for M ≤ 256 (a16) / the small-M decode regime (a8).
3. **Production chunk moved past the measured range** (three-way chunk switch
   → 8192), so prefill m=4096–8192 ran in an unmeasured region — exactly where
   the third-party long-input benchmark landed.

**Why not "turn b12x off everywhere":** decode/verify (m ≤ 96 exact ladder,
graph bs ≤ 12) is b12x's *verified* winning regime (−8–12 %), and decode
dominates this deployment's traffic. The correct split is workload-shaped:

- **prefill-heavy workloads:** `DSV41_MOE_B12X=0` (hook chain not installed,
  weights interleave normally, all-FI W4A8). This is the immediate,
  layout-conflict-free mitigation — the one the third-party evaluation used.
- **this deployment (decode-heavy):** keep full b12x-a8; the hybrid MMAX route
  is allowed **only** under `DSV41_MOE_B12X_DUAL_HOLD=1` (~4.3 GiB/rank cost;
  dual-hold keeps `block_scale_interleave` in place so both consumers see a
  valid layout).

An earlier same-day attempt to enable the hybrid under single-hold was caught
by the needle quality gate (large-M chunk KV pollution; see
[the regression analysis](../operators/V41-B12X-LARGEM-REGRESSION-ANALYSIS-20260919.md))
and is the direct reason for the dual-hold gate in `7161bc7`.

## 3. Operator documentation (new)

Two server-side documents are published under `docs/operators/` (sanitized,
internal phrasing neutralized):

- [`V41-OPERATOR-INVENTORY-AND-ROLLBACK-LEDGER-20260919.md`](../operators/V41-OPERATOR-INVENTORY-AND-ROLLBACK-LEDGER-20260919.md) —
  the full operator landscape of the weight compute path: lineage & licenses per
  component (§0), per-path operator inventory with effect/efficiency/status
  (§1: sparse MLA, MoE routing incl. the large-M incident, shared experts,
  communication/Engram/spec-decode/KV pool), the complete reject/rollback
  ledger with reasons and dates (§2, 17 entries), alignment check against the
  stated directives (§3), remaining optimization headroom O1–O6 (§4), and the
  current production board (§5).
- [`V41-B12X-LARGEM-REGRESSION-ANALYSIS-20260919.md`](../operators/V41-B12X-LARGEM-REGRESSION-ANALYSIS-20260919.md) —
  the incident write-up behind §2 above: evidence chain, why the mixed route
  failed under single-hold, and the v18 fix.
- [`moe-bakeoff-20260914.json`](../operators/moe-bakeoff-20260914.json) — the raw
  per-M bake-off measurements (M = 6…2048, FI CUTLASS W4A8 vs b12x W4A8/W4A16),
  so every percentage quoted in the two documents is re-derivable.

## 4. README corrections in this release

- §4 Layer 1: the "b12x ahead at every M" sentence is replaced by the true
  per-M summary (small-M win, crossover at ~2048 for a16) with a pointer to
  the regression analysis; the MoE bullet now states the a8 default and the
  dual-hold-only hybrid gate.
- §4 risks: added the single-hold layout-conflict risk (KV pollution if the
  hybrid route is armed without dual-hold).
- Both READMEs note the two new commits in the version line.

## 5. Compatibility

- No image change; `BUILD-IDENTITY.md` values are unchanged. Repo-only release.
- `DSV41_MOE_B12X_MMAX` semantics changed: it is now **inert unless
  `DSV41_MOE_B12X_DUAL_HOLD=1`**. Deployments that set MMAX before this release
  and relied on single-hold hybrid routing were running the corruption-prone
  configuration — switch to dual-hold or drop MMAX.
- PR numbers are unaffected (no engine/image change).
- Compliance notes carried in the ledger (§4-O6): b12x's own "not intended for
  production" self-description and the LuZ NCCL shim's missing license text
  remain open items for any redistribution scenario.

## 6. Distribution artifact updated (2026-09-20, post-release)

The cloud-drive distribution file was re-issued under the v0.2.4 name. Same image
content as before (content identity `4ebef21b6aedbd70` unchanged; §5 above remains
true), **new filename and new checksums**:

| | value |
|---|---|
| File | `LuZ-0.2.4-dsv41-tp4-dgxspark.tar.zst` |
| Size | 14,462,447,532 bytes (13.5 GiB) |
| MD5 | `9daeb2ba314a1380988ed6f8afbe4657` |
| SHA256 | `f98af3b5a40ad83150b3f0e0fd3b373fad50e34cbfbc4b7b8786324b36818a3d` |
| Source | Baidu Netdisk link in [README §7](../../README.md#7-image-download-release-artifact) |

The 2026-09-18 audit under [`data/release-artifact-20260918/`](../../data/release-artifact-20260918/)
was performed against the v0.2.2-era file and remains valid for what it tested
(123-blob self-consistency and the offline identity reproduction). Checksums above were
recomputed over the distributed copy; the offline verifier reproduces content identity
`4ebef21b6aedbd70` on the new file identically.

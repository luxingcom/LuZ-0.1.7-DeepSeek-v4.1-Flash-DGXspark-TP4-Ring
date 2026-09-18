# LuZ-0.1.7-DSV41F · DeepSeek-V4.1-Flash on 4× DGX Spark · TP4 switchless RoCE ring

Production recipe for serving **deepseek-ai/DeepSeek-V4.1-Flash** — a ~550 B-parameter
MoE (40 layers, 384 routed experts/layer, top-6 routing + 1 shared expert, MXFP4
expert weights, 1 M native context, DSpark speculative decoding) — with **SGLang TP4
/ EP2** across **4× NVIDIA DGX Spark (GB10)** wired as a **switchless RoCE ring**
(no 400 G switch).

This repo is a **ring adaptation + operations layer + kernel overlay** on top of the
upstream SGLang recipe. It ships launcher scripts, SGLang monkey-patches / fused
decode operators, a self-heal monitor, the benchmark gate suite, and the raw
benchmark archives. **No weights, no images, no NCCL binaries.**

中文说明 → **[README.zh-CN.md](README.zh-CN.md)** · 完整部署与基准文档 → **[docs/](docs/)** ·
基准口径与全部原始归档 → **[benchmarks/README.md](benchmarks/README.md)** / **[data/](data/)**

---

## 1. What is running right now

Every number below is tagged with the **build form it was measured on**. Two forms
appear in this repo and they are *not* interchangeable — read the tag before quoting.

| | **Form A — current production** | **Form B — tuned reference (2026-09-13)** |
|---|---|---|
| context / KV pool | **600,000** / 9,600,000 tokens | 1,048,576 / 4,999,936 tokens |
| max concurrency | **16** | 12 |
| fp4 indexer | **enabled** | disabled (evaluated, then off) |
| `EP_SIZE` | 2 | 2 |
| board | §2 below | §5 below |
| full doc | [docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md) | [docs/4DGX-dsv41-基准测试-横向对比-20260912.md](docs/4DGX-dsv41-基准测试-横向对比-20260912.md) |

Exact image IDs, SGLang commit, component versions and the release-artifact hashes:
**[BUILD-IDENTITY.md](BUILD-IDENTITY.md)**.
Thinking mode is written as `OFF · ON` where both were measured.

**One measurement convention, stated once.** Every performance table in this repo is
**SD-1**: chat channel + prompt-label output types (no guided decoding) + the output
budget force-filled + a fresh nonce on every request + one aggregation rule. It is
defined and justified in [FINAL-METRICS §1](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)
and implemented once, in [`benchmarks/sd_protocol.py`](benchmarks/sd_protocol.py).
Every archive records the convention and the wave count that produced it, so a file is
self-describing. **Read [FINAL-METRICS §1.3](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)
before comparing two rows: each table carries its own error bar, and a difference
smaller than that error bar is not a result.**

---

## 2. Form A — 600K production board

Measured on the running production build. Full tables, per-cell aggregates and the
raw archives: [docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)
and [`data/sd1-20260918/`](data/sd1-20260918/).

### DE decode, per stream (4 prompt-label types, no grammar, force-filled budget)

4 types × 5 concurrencies × 3 waves; cell value = `statistics.median` over every ok
stream of every wave. Full 20-cell table with aggregates and TTFT in
[FINAL-METRICS §4](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md).

| Type | C=1 | C=2 | C=4 | C=8 | C=16 | wave spread |
|---|---:|---:|---:|---:|---:|---:|
| code | **83.59** | 65.39 | 56.41 | 41.34 | **34.97** | ±2.2–±6.1% |
| json | 76.20 | 64.85 | 50.18 | 33.64 | 29.90 | ±0.5–±4.0% |
| structured | 56.41 | 44.41 | 42.25 | 27.42 | 21.31 | **±17.7–±45.0%** |
| prose | 45.84 | 35.74 | 27.20 | 17.89 | 14.80 | ±0.8–±7.4% |

> **`structured` here is a prompt label, not a grammar constraint.** Ranking
> `code > json > structured > prose` holds at all five concurrencies, but only **11 of the 15**
> adjacent gaps clear their own error bar — at C1/C2 only `code` vs `prose` resolves.
> **Read the spread column before comparing two rows.** The cause of `structured`'s
> spread is *not identified*, and no table here claims one.

### PR prompt-rate matrix (7 input sizes × 5 concurrencies, incl. the 4096 supplement) — [FINAL-METRICS §3](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)

Aggregate prefill rate at and above 8192 input tokens is **flat in concurrency** —
524288 holds 1323–1409 tok/s from C=1 to C=16, and the 16th stream's TTFT is
**5955 s** — because the engine admits prefill one request at a time above the
4096-token chunk size. Three independent evidence channels (client dispatch spread
0–697 ms with `peak_client_overlap == C` everywhere, the engine's own running/queue
gauges, and the scheduler's per-step `#new-seq`) agree: **27/30 cells match the
admission law `min(C, floor(4096/input))` exactly, and the 3 exceptions are page-size
seam steps, not violations.**

> ⚠️ **This is the one table whose column names invite a wrong reading, so read
> [benchmarks/README.md §3.2](benchmarks/README.md) first.** The engine runs
> `--chunked-prefill-size 4096`, and above that prompt length the scheduler gives the
> in-flight chunked request the whole step's prefill budget. Prefill therefore advances
> **one request at a time** for any input > 4096 tokens — the aggregate prompt-rate column
> collapses to the single-stream chunked rate, and `median TTFT` at C>1 is a
> queue-position figure, not an engine latency. The matrix carries the engine's own
> running/queue counters per cell so this is measured rather than asserted.

### Gateway and short-output arms

| metric | value | note |
|---|---|---|
| `:8001` gateway vs direct `:8899` | prefill **+0.9 %** · decode **−0.2 %** · wall **+0.3 %** | n=2 per arm — enough to exclude an order-of-magnitude penalty, **not** enough to exclude a single-digit-percent one ([§6](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)) |
| fp4-indexer, 256-token budget, `code` | C1 **88.58** · C8 44.52 · C16 36.99 tok/s/req | **one arm only** — the indexer is on; the off arm needs a restart. Not an A/B ([§7](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)) |

### Headline figures

**Total throughput (the two numbers to quote): aggregate decode peak DE 537.5 t/s
(code, C16) · PR union decode peak 320.2 t/s (512-token prompts, C16).**

| metric | value |
|---|---|
| **DE aggregate decode peak (total throughput)** | **537.5 t/s** (code, C16) |
| **PR aggregate decode peak, union window (total throughput)** | **320.2 t/s** (512 C16) · 4096-token prompts **235.5 t/s** (C16) |
| prefill peak | **3,327.2 t/s** (8192 C1); 4096-token row 2,300–3,234 t/s (C1→C16, peak 3,233.8 at C4) |
| single-stream decode peak | **83.59 t/s** (code, C1) |
| aggregate decode peak | **537.5 t/s** (code, C16) |
| GSM8K, 200 questions | **0.9600** (192/200) · temp 0.6, 8-shot · indexer off |
| engine cold start | **345.7 s ≈ 5.8 min** (`tokenizer_e2e`) |

Guided decoding, the chat-vs-native channel comparison and what a repeated prompt is
worth are measured as their own arms in
[FINAL-METRICS §5](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md) and
[§8](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md), with the archives beside
them under [`data/sd1-20260918/`](data/sd1-20260918/).

**Two structured-output traps** — passing `sampling_params.json_schema` as a **dict**
kills the engine, and under a grammar `ignore_eos=True` stops guaranteeing a full
budget. Both reproduce on the native `/generate` path; the mechanism and the workaround
are in [benchmarks/README.md §3.1](benchmarks/README.md).

---

## 3. Ring adaptation delta (vs the upstream TP4 profile)

**Transport / topology**

- Ring-only NCCL 2.30.7 + `libncclpin` core-pinning shim via `LD_PRELOAD`;
  per-rank `PEER_HCA` for the 4-edge wiring (`./start-tp4.sh ncclcheck` verifies the
  ring-only path came up). The library is the **LuZ lineage** build (ring-only via
  NCCL's algorithm matrix, `Tree=0 / Ring=1`), *not* a SparkRing patched library —
  see [BUILD-IDENTITY.md](BUILD-IDENTITY.md)
- Node-local weights (no NFS), loopback engine behind a concurrency proxy, multiple
  served-model aliases (old name kept for zero-touch consumers)

**Tuned for the ring** (each A/B'd in isolation; measured deltas in the config header)

| setting | why |
|---|---|
| `EP_SIZE=2` (was 4) | kills the expert-parallel straggler; long-context prefill 595 s → 345 s at 500 K |
| `MAX_RUNNING_REQUESTS=16` (was 12, originally 8) | with `--min-free-slots-delay 1` the upper slots actually run: c12 271 → 398 on the 12-way board; 16-way is the current production form |
| `DSV41_CACHE_GIB=1` / 16-way | Engram row cache: hit rate 0 → 99.1 %, c12 +6 %, prefill 100 K +10.5 % |
| `DSV41_SHARED_PAD_K=1` | upstream PR #17: keeps the shared expert's K=576 shape eligible for b12x (bit-identical) |
| static verify mode | upstream compact/ragged mode trips an engram target-verify assertion on V4.1 (sgl-project/sglang#39173) |
| `CHUNKED_PREFILL_SIZE=4096` | what makes a 524288-token prompt fit at all — and the reason long-prompt prefill is serialized one request at a time. See [benchmarks/README.md §3.2](benchmarks/README.md) |

**fp4 indexer (`--enable-deepseek-v4-fp4-indexer`) is ON** in Form A. It is an
env-level switch and Form B runs with it off; the two forms are different
configurations, so neither row should be quoted against the other. The A/B that would
decide it needs a restart and is a window item
([FINAL-METRICS §7](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md),
[§11](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)).

**One known regression, kept and disclosed:** c6 aggregate 260 → 236 (−9 %), an EP2
side effect; c8/c12 rise far more.

---

## 4. Experimental operator optimization (what we changed, and the risks)

The production build carries **three experimental layers** on top of upstream SGLang.
All are env-gated or file-level grafts; upstream behaviour is one flag away. They are
the main source of this build's measured gains (c12 aggregate +47 %, decode peak +12 %,
prefill 100 K +4–10 %) and the main source of its upgrade risk. Read this before
pinning a new upstream commit.

### Layer 1 — b12x CuTe kernels (fork of the b12x project, shipped in `b12x-site/`)

b12x is a consumer-Blackwell (SM120/SM121) CuTe-DSL kernel library: NVFP4/MXFP4/MXFP8
GEMM, fused MoE, paged/dense/sparse MLA attention, DSA indexing, mHC residual, PCIe
collectives. This repo vendors it under `b12x-site/` and routes selected SGLang ops
onto it:

- **MoE W4A16→b12x** (`adapter/moe_b12x.py`, gate `DSV41_MOE_B12X=1`): routes
  `flashinfer_mxfp4` MoE to b12x `fused_moe` under the replicated-input EP contract.
  Bake-off (real layer-2 weights): b12x ahead at every M (M=6 −11.4 % latency … M=2048 −5.2 %).
- **Dense MXFP8 linears→FlashInfer b12x backend** (`adapter/mxfp8_b12x.py`,
  `DSV41_MXFP8_BACKEND=b12x`): SGLang's CUTLASS SM120 kernel pads M=6→128 at decode
  (measured 50–75 GB/s, 52 ms of a 118 ms decode step); the b12x warp-level kernel
  takes small-M tiles instead.
- **Shared-expert K pad** (`adapter/shared_pad_k.py`, gate `DSV41_SHARED_PAD_K=1`):
  pads down_proj K 576→640 so the one b12x-rejected shape re-enters the fast path
  (bit-identical output; zero-block-scales encoded as 1.0).
- **MoE ladder caps** (`DSV41_MOE_B12X_CAPS=128,256,512,1024,2304,4096`,
  `DSV41_MOE_B12X_QUANT=a8`): per-bucket exact kernels up to a 96-row exactness cap,
  a8 activation quant above.

### Layer 2 — fused DeepSeek-V4 decode operators (`sglang-overlay/`)

Per-file bind-mount grafts over the image's sglang tree (see `SGLANG_OVERLAY_MAP` in
`start.sh`; the same files are baked into the production image at build time).
Headline operators, all fusing what upstream runs as separate kernels:

- `c1.py` — fused ratio-1 decode: RMSNorm + RoPE + FP4 fake-quant + FlashMLA cache write
- `c2.py` — fused ratio-2 pair-pooling decode + main-KV write (closed-form softmax;
  fp32-ulp deltas documented in-file)
- `fused_norm_rope_v2.cuh` / `main_norm_rope.cuh` / `store.cuh` / `c1.cuh` / `c2.cuh` /
  `kv_layout.cuh` — the CUDA halves of the same fusions
- `dspark_accept.py` / `dspark_draft.py` / `fast_argmax.py` / `dflash_info_v2.py` —
  DSpark speculative decode accept/draft path (two-stage split argmax, packed top-k)
- `decode_cuda_graph_runner.py`, `deepseek_v4_backend.py`, `deepseek_v2.py` —
  graph capture and backend routing
- `deepseek_v4_memory_pool.py` + `kv_cache_configurator.py` — **fork-v4-fp4 KV layout**:
  ratio-1 latents stored as FP4 (lossless vs upstream's second FP8 rounding;
  ratio-4/128 latents stay FP8)
- `dsv4_prefill_reuse.py` — adjacent prefill query rows reuse overlapping top-K sets
  (env-gated OFF by default)
- `engram.py` / `engram_hash.py` — Engram embedding row-cache integration

### Layer 3 — host-side adapters (`adapter/`)

- `engram_backend.py` + `librow_store.so` (from `row_store.cpp`) — bounded exact
  file-backed replacement for EngramEmbedding's owned-row gather (C++ extension,
  not pure Python — needs the matching image to run)
- `prefill_empty_cache.py` — returns each long-prefill chunk's transient indexer
  memory to the allocator between chunks (600 K-context headroom)

### ⚠️ Risks you accept by using this build

1. **Bit-exactness is per-path, not global.** c1/c2 use closed-form softmax and FMA
   contraction that can differ from torch by fp32 ulps; MoE `a8` mode quantizes
   activations above the exact ladder. Quality gates (GSM8K 0.9600, needle 30 K–470 K,
   corruption 0/0/0, code-gate 12/12) passed on the pinned **Form B** build — but a
   different sampling temperature or workload mix shifts the tail.
2. **Version pinning is load-bearing.** The kernels bind to the SGLang commit recorded
   in [BUILD-IDENTITY.md](BUILD-IDENTITY.md) + FlashInfer 0.6.18 +
   PyTorch 2.13.0+cu130 + driver 580.173.02. Rebase upstream and the grafts
   (esp. `deepseek_v2.py`, `deepseek_v4_backend.py`, graph runner) are the first things
   to break — `SGLANG_OVERLAY_MAP` is a shim surface, not an API.
3. **K-pad & ladder are shape-coupled.** The shared-expert pad hard-codes K=576→640;
   a different `moe_intermediate_size` or TP degree silently changes the shape and the
   pad either no-ops or misroutes. `DSV41_MOE_B12X_CAPS` likewise encodes this model's
   bucket geometry.
4. **FP4 KV layout halves per-token latent bytes.** Measured lossless for ratio-1
   latents (they are fp4-rounded upstream anyway), but it changes the memory pool
   layout — third-party pool tooling or future upstream layout changes will not read it.
5. **Graph-capture safety is on the honour system.** b12x `bind()` is written to be
   capture-safe, and `freeze_kernel_resolution` raises on a cache miss inside a live
   request — but any new shape hitting the frozen set mid-serve is a hard error,
   not a slow fallback.
6. **Documented regressions, not hidden**: c6 aggregate −9 % (EP2 side effect); 900 K
   context unavailable in the Form B configuration (Engram cache + K-pad buffer cost
   ~2 GB of deep-context headroom — 600 K and below unaffected).
7. **No upstream review.** Every file here is a local engineering artifact (r9-ops lane
   work, 2026-09-15 wave ports of upstream PRs #38409/#39370/#39420/#39187/#38979
   re-authored for this fork). Treat it as an engineering snapshot, not a
   distribution-quality patch set: audit `sglang-overlay/` against your own
   threat/perf model before reusing.

---

## 5. Form B — tuned reference board (2026-09-13)

The frozen configuration that produced the c1–c12 sweep and the context / long-prompt
results: **1 M ctx · 5 M KV pool · 12 concurrent · EP_SIZE=2 · PR#17 K-pad ·
Engram cache 1 GiB/16-way · `--min-free-slots-delay 1` · no fp4 indexer.**
Full six-stack comparison incl. LuZ / Vision-Exp / GLM:
[docs/4DGX-dsv41-基准测试-横向对比-20260912.md](docs/4DGX-dsv41-基准测试-横向对比-20260912.md).

> **These figures belong to Form B and are not comparable with §2.** Different context
> and pool size, different concurrency ceiling, indexer off, and a pre-SD-1 accounting
> convention. The comparison document states its own scope.

| benchmark | value |
|---|---|
| decode peak / mean (code, temp 0) | **100.3 / 81.4** · 99.8 / 81.2 tok/s (OFF · ON) |
| prose OFF · ON | **33.3 · 36.6** tok/s |
| prefill 8 K / 32 K / 100 K | **3102 / 3443 / 3253** t/s |
| aggregate c1 / c4 / c8 / c12 | 82 / 223 / 295 / **398** tok/s (ON: 83 / 225 / 298 / 403) |
| quality gates | needle 30 K–470 K ✅ · corruption 0/0/0 · termination 18/18 + 18/18 · code-gate 12/12 · GSM8K n=50 **1.00** |
| DSpark acceptance | 3.98 tok/step, rate 0.595 (6.0 saturated on math) |
| cold start | ~9 min, **no cold-start penalty** |

**Long context** (cold prefill, needle-checked):

| depth | result |
|---|---|
| 470 K | ✅ 211.7 s · 2144 t/s |
| 600 K | ✅ 341.7 s |
| **900 K** | ⚠️ **fails** in this form — the Engram row cache and the shared-expert pad buffer cost ~2 GB of deep-context headroom. 600 K and below are unaffected. |

> The 900 K case is a **configuration capacity** limit, not engine accumulation:
> it fails on a fresh engine too.

---

## 6. Repo contents

- `start.sh / start-tp4.sh / stop.sh / boot.py` — serving orchestration, pinned
  checkpoint boot, smoke + warm-up
- `adapter/` — SGLang patches (Engram row store C++, MXFP8 backend, shared-expert
  K pad, prefill cache hook)
- `sglang-overlay/` — the fused DeepSeek-V4 decode operators grafted over the image's
  sglang tree (Layer 2 above)
- `b12x-site/` — vendored b12x CuTe-DSL kernel library (Layer 1 above)
- `scripts/` — SSH helper, `verify/` probe kit, self-heal monitor + systemd unit,
  `gate.sh`, `nccl_selfcheck.sh`, `verify_release_artifact.py` (**offline** archive
  verifier: blob integrity + content identity, no cluster needed), and the three
  repository checks (`check_redaction.py`, `check_relative_links.py`,
  `check_report_tables.py`)
- `benchmarks/` — the harnesses that produced the tables, with a
  [harness-to-archive map](benchmarks/README.md), the
  [SD-1 protocol](benchmarks/README.md), the
  [redaction policy](benchmarks/README.md), and
  [§3.2 on the engine's prefill admission law](benchmarks/README.md)
- `bench/` — gate suite (needle / corruption / termination / code-gate), vision gate,
  prose, GSM8K, third-party-shaped sweep, MoE numeric/capacity ladders
- `data/` — **raw benchmark archives** under `data/sd1-20260918/`: the DE matrix with
  per-stream records, the grammar A/B, the fp4 short-output arm, gateway-vs-direct, the
  30-cell PR matrix with the engine's own per-step counters, and the two GSM8K runs —
  plus the recorded offline audit of the release archive
  (`data/release-artifact-20260918/`). Every published figure is re-derivable from these
  files; [`data/README.md`](data/README.md) says how, and names the one column that is
  not
- `.env.tp4.example` — the configuration this repo runs (sanitized template; the live
  `.env.tp4` is gitignored)
- `BUILD-IDENTITY.md` — image IDs, SGLang commit, component versions, artifact hashes,
  and the exact identity formula to check an image against
- `docs/` — deployment plan, upstream ISSUE/PR survey, benchmark comparison, and the
  final metrics board

---

## 7. Image download (release artifact)

The serving image (13.5 GiB) is distributed via cloud drive:

- **Baidu Netdisk**: https://pan.baidu.com/s/1QjmmRu8GbFpWTBRkWslvBQ?pwd=luzi (extract code: `luzi`)
- **File**: `LuZ-0.1.7-DSV41F-image.tar.zst`
- **Size**: 14,463,467,578 bytes (13.5 GiB)
- **MD5**: `10307040cd70ab23436bf34eee829d24`
- **Content identity**: `4ebef21b6aedbd70` — the same value all four production nodes report, and **re-derivable offline from the archive itself**

Verify before you load anything (no cluster, no docker daemon, no GPU needed):

```bash
pip install zstandard
python scripts/verify_release_artifact.py LuZ-0.1.7-DSV41F-image.tar.zst --md5
# md5 MATCH · 123/123 blob sha256 verified · 0 unreferenced blobs
# content identity 4ebef21b6aedbd70 · RESULT: PASS  (exit 0)
```

Then load on all four nodes (all of them need the image) and re-check identity locally:

```bash
docker load -i LuZ-0.1.7-DSV41F-image.tar.zst   # requires zstd; restores dsv41-sglang-optimized:v7
docker image inspect -f '{{join .RootFS.Layers " "}}' dsv41-sglang-optimized:v7 \
  | sha256sum | cut -c1-16      # expect: 4ebef21b6aedbd70
```

That one-liner is the formula `start.sh`'s own preflight uses, so a passing local check
means the fleet-level check will pass too. **Do not** verify by layer count or by
`docker image inspect --format '{{.Id}}'`: the reported image ID differs between the head
(`03587ce9…`) and the workers (`9e1036bc…`) because those are *two different objects in
the same archive* — the OCI index blob and the image-config blob respectively — while the
123-layer content is identical. Full reasoning, all five serializations of the same layer
list that have been published as "the identity" (they hash to five different values), and
the empty-input trap (`01ba4719c80b6fe9` = a **missing** image, not an identity) are in
[BUILD-IDENTITY.md](BUILD-IDENTITY.md).

---

## 8. Sanitization and repo status

Internal IPs / hostnames are replaced with placeholders and API keys are removed
(`YOUR_API_KEY`); the site `.env.tp4` is excluded via `.gitignore`.

**The one class that is masked rather than classified** is `PEER_HCA_RANK0..3`: on a
4-node ring that map encodes the physical cabling. `.env.tp4.example` carries
`<PINNING>` plus a three-step derivation so you can produce your own map from a
`NCCL_DEBUG=INFO` first boot, and `./start-tp4.sh ncclcheck` verifies it. The rationale,
and the list of hits that are deliberately *left alone* (generic address scheme, upstream
author identifiers, stock HCA names), are in
[benchmarks/README.md §4](benchmarks/README.md).
`scripts/check_redaction.py` re-checks all of it and exits non-zero on any unclassified
hit in a blocker class.

The repository's default branch is **`main`**, and **the adaptation lives on `main`** —
this is a standalone engineering snapshot, not a branch of the upstream project.
Upstream lineage is credited below and in [BUILD-IDENTITY.md](BUILD-IDENTITY.md).

| Component | Origin | License |
|---|---|---|
| SGLang serving recipe (boot, adapters, Engram row store, DSpark setup) | [`ntxf31415/DeepSeek-v4.1-Flash-DGX-Sparks`](https://github.com/ntxf31415/DeepSeek-v4.1-Flash-DGX-Sparks) (also published as `MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks`) | AGPL-3.0-or-later |
| Recipe lineage / benchmark methodology | [`0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000`](https://github.com/0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000) | MIT |
| Host ring-only NCCL 2.30.7 build + `libncclpin` core-pinning shim (host-side, not shipped) | [`luxingcom/aicad-nccl-optimization`](https://github.com/luxingcom/aicad-nccl-optimization) (LuZ lineage) | **no license declared** |
| Model weights | `deepseek-ai/DeepSeek-V4.1-Flash` (Hugging Face) | see model card |

**Sister projects:** [DeepSeek-V4-Flash-Vision-Exp TP4 switchless-ring](https://github.com/ntxf31415/deepseek-v4-vision-exp-dgxspark-tp4-switchless-ring) (vLLM, same ring base) · [GLM-5.3-Flash NVFP4 TP4 switchless-ring](https://github.com/ntxf31415/glm-5.3-flash-nvfp4-4x-dgx-spark-switchless) (companion recipe).

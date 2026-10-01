# LuZ-0.1.7-DSV41F · DeepSeek-V4.1-Flash on 4× DGX Spark · TP4 switchless RoCE ring
> ### 📥 Download the serving image (13.1 GiB)
>
> **[⬇ LuZ-0.2.9-dsv41-tp4-dgxspark.tar — Quark Drive](https://pan.quark.cn/s/aa6b189231e3)** · mirror **[Baidu Netdisk](https://pan.baidu.com/s/1-LvoV_xtF4hJKp5qaQH90g?pwd=luzi)** · code `luzi`
>
> SHA256 `c1840255408f8b8b012279153580d1310f5d7d9bc4f5aa4e4181bcc8bf23fb0d` · MD5 `3562a789ec0e9aa4bc80a7e54ba1be65` · content identity `355a5e45cb2725ae` · verify & install: **[Image download → §7](#7-image-download-release-artifact)**


**Repo version: v0.2.9** (2026-09-30) — see the
[release notes](docs/release-notes/RELEASE-NOTES-v0.2.9.md). Image is now `dsv41-sglang-optimized:0.2.9-ep1q2-fin2`
(content identity `355a5e45cb2725ae`, 5 layers): **the last stable build of the old base**, and the
**EP1 enablement chain** (`EP_SIZE` 2→1 with `DSV41_MOE_B12X` 1→0) plus the P1a adapter trio
(`draft_head_fp8_tp4`, `hc_fused`, `draft_tau`) baked in. Decode **c8 +4.0 % / c12 +4.8 %**;
262k/131k prefill flat inside boot noise; QA 17/0. The image is **packaged for download again** (below).

The 0.2.8 release remains the last **50-cell PR matrix board** and is kept as its own record —
its numbers belong to the 0.2.8 base and must not be mixed with 0.2.9's.

Production recipe for serving **deepseek-ai/DeepSeek-V4.1-Flash** — a ~550 B-parameter
MoE (40 layers, 384 routed experts/layer, top-6 routing + 1 shared expert, MXFP4
expert weights, 1 M native context, DSpark speculative decoding) — with **SGLang TP4**
across **4× NVIDIA DGX Spark (GB10)** wired as a **switchless RoCE ring**
(no 400 G switch).

This repo is a **ring adaptation + operations layer + kernel overlay** on top of the
upstream SGLang recipe. It ships launcher scripts, SGLang monkey-patches / fused
decode operators, a self-heal monitor, the benchmark gate suite, and the raw
benchmark archives. **No weights, no images, no NCCL binaries.**

中文说明 → **[README.zh-CN.md](README.zh-CN.md)** · 完整部署与基准文档 → **[docs/](docs/)** ·
基准口径与全部原始归档 → **[benchmarks/README.md](benchmarks/README.md)** / **[data/](data/)** · 📥 **[Image download → §7](#7-image-download-release-artifact)**

---

## 1. What is running right now

Every number below is tagged with the **build form it was measured on**. Three forms
appear in this repo and they are *not* interchangeable — read the tag before quoting.

Current release (**v0.2.9**, 2026-09-30) — the image and the EP1 chain:

| | value |
|---|---|
| image | `dsv41-sglang-optimized:0.2.9-ep1q2-fin2` — content identity **`355a5e45cb2725ae`** (**5 layers**) |
| change vs `ep1q2-fin` | **EP1 enablement chain** (`EP_SIZE` 2→1, `DSV41_MOE_B12X` 1→0) + P1a adapter trio (`draft_head_fp8_tp4`, `hc_fused`, `draft_tau`) + memwatch + PREFLIGHT `v1-fin2` + 16-gate banner |
| measured (vs `ep1q2-fin`) | DE prose **c8 +4.0 % · c12 +4.8 %**; PR 262k/131k flat inside boot noise; QA **17/0** |
| what it is | **the last stable build of the old base** — new-base work (LuZ-0.3.0) is a separate line |
| full doc | [docs/release-notes/RELEASE-NOTES-v0.2.9.md](docs/release-notes/RELEASE-NOTES-v0.2.9.md) |

> ⚠️ **0.2.9 did not re-run the PR matrix**, and its decode numbers come from a different
> base than 0.2.8's. The two boards are **not comparable** — do not normalize them into
> one table. 0.2.8's 50-cell board remains the matrix of record *for the 0.2.8 base*.

Matrix of record — what every number tagged *0.2.8* below was measured on:

| | value |
|---|---|
| image | `dsv41-sglang-optimized:0.2.8` — content identity **`4cca364c46778423`** (3 layers) ([BUILD-IDENTITY.md](BUILD-IDENTITY.md)) |
| change vs 0.2.4 | **OOM-era engineering close-out** — FIX-B/B′ (idle release + scheduler snapshot hook), FIX-D (logits width bucketing), `mm_ban` (input-side id sampling mask), R2 page-table grid, #40352 candidate-block protocol (**default off**). Pure increment, nothing reduced |
| context / KV pool / concurrency | 600,000 / 9,600,000 tokens / 16 |
| chunk / EP / indexer | 8192 / EP2 / fp4 indexer **off** — the production `.env.tp4` carries no `--enable-deepseek-v4-fp4-indexer` (grep count 0); see §4 for the history |
| promotion gates (0.2.8 window) | PR 512K single-stream **> 4,500 t/s hard gate ✓** · 512K × C16 **16/16 ok** · zero OOM, memory flat after the 8.4M-token corner |
| full doc | [docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md) |

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

Measured on the running production build (**0.2.8** — both the PR matrix and the DE re-run
were made on it). Full tables, per-cell aggregates and the raw archives:
[docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md),
[`data/luz028-matrix-20260923/`](data/luz028-matrix-20260923/) and
[`data/luz028-de-sd1-20260924/`](data/luz028-de-sd1-20260924/).

### DE decode, per stream (4 prompt-label types, no grammar, force-filled budget) — measured on 0.2.8

4 types × 5 concurrencies × 3 waves; cell value = `statistics.median` over every ok
stream of every wave. Full 20-cell table with aggregates, total-throughput view and
TTFT in [FINAL-METRICS §4](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md).
Re-run against the 0.2.4-era baseline on the same SD-1 protocol: **20/20 cells positive,
zero regressions** (drift band ≤5% PASS / 5–10% WATCH / >10% INVESTIGATE).

| Type | C=1 | C=2 | C=4 | C=8 | C=16 | wave spread | vs 0.2.4 |
|---|---:|---:|---:|---:|---:|---:|---|
| code | **89.19** | 73.36 | 61.71 | 44.11 | 37.75 | ±0.3–±6.1% | +0.9…+4.6% — 5/5 PASS |
| json | **85.90** | 69.28 | 54.84 | 36.70 | 31.44 | ±0.8–±2.7% | +2.4…+6.3% — PASS/WATCH |
| structured | **76.99** | 60.41 | 51.94 | 32.79 | 27.95 | ±4.9–±38.4% | +3.5…+38.2% — INVESTIGATE (positive) |
| prose | **51.92** | 40.06 | 29.88 | 19.51 | 15.94 | ±0.8–±3.0% | +4.5…+6.4% — PASS/WATCH |

> **`structured` here is a prompt label, not a grammar constraint.** Ranking
> `code > json > structured > prose` holds at all five concurrencies, and the spread
> widens with concurrency exactly as in the 0.2.4 baseline (C1 1.72× → C16 2.37×).
> `structured` remains the only unstable type (wave spread ±4.9–±38.4% vs ≤±6.1% for the
> others) and four of its cells drift far positive (+16…+38%): the direction is
> favorable, **the cause is not identified** — registered as an open item, not
> explained away.
> **DE aggregate total throughput (Σ output tokens ÷ Σ wave wall): peak 572.6 t/s at
> code × C16** — 572.6 / 488.3 / 363.0 / 247.6 (code / json / structured / prose);
> same-formula recompute of the 0.2.4 baseline gives 543.9 / 481.0 / 262.8 / 236.4 ⇒
> peak **+5.3%**.

### PR — pure-prefill total throughput (all 40 cells, 4K–512K) — [FINAL-METRICS §3](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)

> Baseline lineage: PR-v2 withdrawn (2026-09-18, no cache flush / not total-throughput) → PR-v3 @ chunk 4096 superseded → **v14** (chunk 8192 re-run) → **v18** (0.2.4, MoE W4A8-MX) → **v19** (0.2.5, #40217 native port) → **0.2.8** (OOM-era close-out, **current**; 4K–512K incl. 512K multi-stream). Superseded archives are kept for audit: [`data/sd1-20260918/pr/`](data/sd1-20260918/pr/), [`data/prv3-20260918/`](data/prv3-20260918/), [`data/prv3-v14-20260919/`](data/prv3-v14-20260919/), [`data/prv3-v18-20260919/`](data/prv3-v18-20260919/), [`data/prv3-v19-40217prep-20260920/`](data/prv3-v19-40217prep-20260920/).
**Quote the 0.2.8 table below and nothing else.**

PR-v3 measures what a load generator actually cares about: **total prompt tokens
divided by the wall clock from releasing the first stream to the last stream
finishing**, with `max_new_tokens=1` (pure prefill, no decode tail), a fresh nonce on
every request and a `POST /flush_cache` between cells.

| Input tokens | C1 | C2 | C4 | C8 | C16 |
|---:|---:|---:|---:|---:|---:|
| 4,096 | 4,464.8 | 4,480.5 | 4,530.9 | 4,875.8 | **5,033.1** |
| 8,192 | 5,360.1 | 5,337.1 | 5,165.3 | **5,383.3** | 5,326.1 |
| 16,384 | 5,498.8 | 5,638.4 | **5,639.3** | 5,618.9 | 5,494.8 |
| 32,768 | 5,772.0 | 5,781.2 | **5,810.3** | 5,691.9 | 5,689.8 |
| 65,536 | 5,792.5 | **5,823.1** | 5,777.6 | 5,701.7 | 5,724.3 |
| 131,072 | **5,791.1** | 5,671.6 | 5,620.8 | 5,600.9 | 5,675.0 |
| 262,144 | **5,585.7** | 5,429.9 | 5,439.9 | 5,496.1 | 5,520.1 |
| 524,288 | 5,042.2 | 4,976.9 | 5,009.1 | **5,066.6** | 5,038.8 |

**Reading the board** (single wave per cell ⇒ no error bar; same-window deltas only):
peak **5,823.1 t/s at 65536 × C2**; the whole board sits in **4,976.9–5,823.1 t/s**.
Concurrency does not drive throughput — within any input row the extremes span
**≤4.22%**. Long documents favour **many short prompts over few long ones** (the 65,536
row tops the board; the 524,288 row settles at 4,976.9–5,066.6). **512K single-stream =
5,042.2 t/s**, clearing the hard gate (`> 4,500`, **+12.05%**); **the 512K row was
measured at all five concurrencies this time** (C16 5,038.8, 16/16 ok) — earlier boards
promised single-stream only. The 4,096 row is `NON_ALIGNED` (a half-chunk size) and is
not compared against whole-chunk rows. Every per-cell value was recomputed from the
per-stream raw records and asserted equal to the server-side per-cell tables before
publication (see [the archive README](data/luz028-matrix-20260923/README.md)).

### Gateway and short-output arms *(v18-stack numbers, not re-run on 0.2.8)*

| metric | value | note |
|---|---|---|
| `:8001` gateway vs direct `:8899` | prefill **+0.9 %** · decode **−0.2 %** · wall **+0.3 %** | n=2 per arm — enough to exclude an order-of-magnitude penalty, **not** enough to exclude a single-digit-percent one ([§6](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)) |
| fp4-indexer, 256-token budget, `code` | C1 **88.58** · C8 44.52 · C16 36.99 tok/s/req | **one arm only** — measured with the indexer **on** (v18 Form A); the off arm needs a restart. Not an A/B, and **not** the 0.2.8 production form ([§7](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)) |

### Headline figures

**Total throughput — the two numbers to quote: PR pure-prefill total throughput peak
5,823.1 t/s (65536 × C2, **0.2.8**) · DE aggregate decode peak 572.6 t/s
(code, C16, **0.2.8**, Σ output tokens ÷ Σ wave wall).**

| metric | value |
|---|---|
| **PR total throughput peak (pure prefill, chunk 8192, 0.2.8)** | **5,823.1 t/s** (65536 × C2) · runner-up **5,791.1 t/s** (131072 × C1) · 512K single-stream **5,042.2 t/s** (hard gate `>4,500` ⇒ **+12.05%**) · within-row spread at any input ≤4.22% |
| **DE aggregate decode peak (total throughput, 0.2.8)** | **572.6 t/s** (code, C16) — same-formula 0.2.4 recompute 543.9 ⇒ **+5.3%** · per-stream C1 peak **89.19 t/s** (code) |
| DE vs 0.2.4 (SD-1, same protocol) | **20/20 cells positive, zero regressions** · code 5/5 PASS (+0.9…+4.6%) · 4 × structured cells +16…+38% flagged INVESTIGATE (positive; cause not identified) |
| GSM8K, 200 questions | **0.9600** (192/200) · temp 0.6, 8-shot · indexer off *(v18-stack number, not re-run)* |
| engine cold start | **345.7 s ≈ 5.8 min** (`tokenizer_e2e`) *(v18-stack number)* |
| promotion gates (0.2.8 window) | PR 512K single-stream >4,500 ✓ · 512K×C16 16/16 ok · zero OOM · memory flat after the 8.4M-token corner |

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
| `CHUNKED_PREFILL_SIZE=8192` (production since 0.2.8; was 4096) | what makes a 524288-token prompt fit at all — and the reason long-prompt prefill is serialized one request at a time. 8192 was first measured as a *benchmark-only* form on 2026-09-19 and promoted to the production `.env.tp4` (`.env.tp4:156`) in the 0.2.8 window; **every 0.2.8 cell** (§2) is at 8192, so a long-input prompt must be a multiple of 8192 to be comparable. See [benchmarks/README.md §3.2](benchmarks/README.md) and [FINAL-METRICS §1.4](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md) |

**fp4 indexer (`--enable-deepseek-v4-fp4-indexer`) is OFF in the 0.2.8 pinned
production.** The production `.env.tp4` (`EXTRA_SGLANG_ARGS`; env md5 `3f6a014d`)
does not contain the flag, so every row tagged *0.2.8* in this repo was measured
with it **unset** — and FIX-D's logits-width bucketing is correspondingly *not on
the path* (see the additions table above).

History, kept so the two forms are not confused: **Form A** (2026-09-17 onward)
ran with the indexer **on**. Its A/B (code-256, same protocol) measured
c1 −6.4 % / c8 −0.9 % / c16 −3.3 % — a slight negative, kept knowingly at the
time; the 0.2.8 pin dropped it. Form A and Form B (1 M ctx / 5 M pool / 12-way)
are *different configurations* — neither should be quoted against the other.
The one DE row in §2 labelled *fp4-indexer, 256-token budget* is an explicitly
tagged **test arm** from the 2026-09-18 SD-1 window (v18 stack, not re-run on
0.2.8), not the production form.

⚠️ **Operational ban:** do not enable this flag without fixing the bucketing
first — the current step is a 1024× over-allocation at the 2 K width.

**One known regression, kept and disclosed:** c6 aggregate 260 → 236 (−9 %), an EP2
side effect; c8/c12 rise far more.

---

## 4. Experimental operator optimization (what we changed, and the risks)

The production build carries **three experimental layers** on top of upstream SGLang,
plus a set of **env-gated scheduler/allocator fixes added in 0.2.8** (last subsection below).
All are env-gated or file-level grafts; upstream behaviour is one flag away. They are
the main source of this build's measured gains (c12 aggregate +47 %, decode peak +12 %,
prefill 100 K +4–10 %) and the main source of its upgrade risk. Read this before
pinning a new upstream commit.

### Layer 1 — b12x CuTe kernels (fork of the b12x project, shipped in `b12x-site/`)

b12x is a consumer-Blackwell (SM120/SM121) CuTe-DSL kernel library: NVFP4/MXFP4/MXFP8
GEMM, fused MoE, paged/dense/sparse MLA attention, DSA indexing, mHC residual, PCIe
collectives. This repo vendors it under `b12x-site/` and routes selected SGLang ops
onto it:

- **MoE →b12x** (`adapter/moe_b12x.py`, gate `DSV41_MOE_B12X=1`, default
  `DSV41_MOE_B12X_QUANT=a8`): routes `flashinfer_mxfp4` MoE to b12x `fused_moe`
  under the replicated-input EP contract. **Measured regime, from the raw
  bake-off** ([`docs/operators/moe-bakeoff-20260914.json`](docs/operators/moe-bakeoff-20260914.json)):
  b12x wins at small/decode M (−10 % latency at M=6 … −5.2 % at M=2048 with a8);
  **W4A16 loses the crossover at M≈2048** (+7.2 % vs FlashInfer CUTLASS W4A8) —
  an earlier docstring mislabeled the a8 numbers as a16 and over-claimed the
  regime; corrected 2026-09-19. Above the measured range (M = 4096–8192,
  reachable at `--chunked-prefill-size` ≥ 4096) there is **no a8 measurement
  yet**: prefill-heavy workloads should set `DSV41_MOE_B12X=0` (all-FlashInfer
  W4A8), which a third-party long-input evaluation measured at +30–89 % with
  length. The MMAX→FlashInfer hybrid route is **inert unless
  `DSV41_MOE_B12X_DUAL_HOLD=1`** — arming it under single-hold corrupts
  large-M KV (see [the regression write-up](docs/operators/V41-B12X-LARGEM-REGRESSION-ANALYSIS-20260919.md)).
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

### 0.2.8 additions — OOM-era close-out (scheduler / allocator, not kernels)

The **2026-09-21 four-node OOM chain** was root-caused to transient **prefill-chunk
memory strangulation** inside the CUDA caching allocator (~0.5–1 GB per chunk,
invisible to the scheduler's own accounting), compounded by health-check kill loops
and a Linger auto-restart. 0.2.8 closes that out. Production wires these into
`.env.tp4` `EXTRA_DOCKER_ENV`; the **image defaults** are shown for reference, because
"the code defaults to off" and "production runs it" are both true here:

| item | gate | image default | production (`.env.tp4`, md5 `3f6a014d`) |
|---|---|---|---|
| FIX-B idle release | `DSV41_IDLE_RELEASE` | `0` off | **`1` on** |
| FIX-B′ SIGUSR1 memory-snapshot hook | `DSV41_SCHED_SNAPSHOT` | `0` off | **`1` on** (diagnostic; whole chain fail-open) |
| FIX-D logits width bucketing | hard-coded, no env gate | follows the fp4-indexer branch | **not on the path** (that flag is unset) |
| `mm_ban` input-side id mask | `DSV41_BAN_MM_PLACEHOLDERS` / `DSV41_BAN_PROMPT_CONTROL_TOKENS` | `1` on | **on** (default) |
| R2 page-table width grid | `SGLANG_DSV4_PAGETABLE_PAGES_GRID` | `1024` → grid **on** | **`1` → grid off** (deliberate) |
| #40352 candidate-block protocol | `DSV41_IDX_PROTOCOL` | `false` | **`1`** — the 256K/512K single-stream survival switch |

- **FIX-B** releases allocator segments only inside a fully-idle window (no running, no
  queued — the same window class as `flush_cache`'s internal `empty_cache`). Its dose
  limit is stated honestly: 16 K clean, 32 K hits the wall on three nodes — it rescues
  *request boundaries*, not *in-flight* peaks.
  (v1 of it could **never fire**: it read a `memory_stats()` key that this torch build
  suffixes with `.current`/`.peak`, so the lookup returned 0 and the function returned
  silently. v2 uses the documented wrappers.)
- **FIX-D** collapses the per-chunk logits allocation width from 9185 distinct sizes to
  **2**, so the allocator reuses by class. ⚠️ **Operational ban:** if you ever enable
  `--enable-deepseek-v4-fp4-indexer`, fix the bucketing **first** — the current step is
  a 1024× over-allocation at the 2 K width.
- **`mm_ban`** masks 438 input-side-only token ids at the sampling layer, on **both** the
  target and the draft side. `129271..129278` are deliberately **not** masked (they are
  valid vision-grounding outputs), so the set is an explicit enumeration checked against
  the tokenizer — **it cannot be derived by id range or by the `special` flag.** Boundary:
  it filters *sampling*, not echoes of the request body.
- **R2 grid**: at `1024`, a page-table width above 1024 rounds up to a multiple of 1024
  (closing the "width grows with context ⇒ every chunk needs a new block" hole), while
  below the grid line it keeps legacy exact sizing. Production sets `1` (grid off) — a
  carried-over decision from the 2026-09-22 ladder window, not an oversight.
- **#40352** (semantics-level backport, not a whole-chain port) publishes prompt-side
  candidates as an **int32 block-id table** instead of a per-token fp32 score matrix +
  bool mask (~17 GB + 4.3 GB per layer at 600 K). Release payload **73.2× smaller**
  (600 K corner: `2048 × 4 B` vs `600000 B`); candidates cover **2.73 %** of tokens, so
  **97.27 %** of the old mask was pure waste. With the flag off there is zero coupling
  (the new module is imported lazily). CPU equivalence gate: **42/42 PASS** (7 scenarios
  × 4 checks, element-wise equal including the production 600 K / 8192 shape).

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
   ~2 GB of deep-context headroom — 600 K and below unaffected); **MoE hybrid route
   under single-hold corrupts large-M KV** (the `MMAX` delegation must only be armed
   with `DSV41_MOE_B12X_DUAL_HOLD=1` — caught by the needle gate, see
   [docs/operators/](docs/operators/)).
7. **No upstream review.** Every file here is a local engineering artifact (r9-ops lane
   work, 2026-09-15 wave ports of upstream PRs #38409/#39370/#39420/#39187/#38979
   re-authored for this fork). Treat it as an engineering snapshot, not a
   distribution-quality patch set: audit `sglang-overlay/` against your own
   threat/perf model before reusing.

---

## 5. Historical boards (superseded)

Early-configuration comparisons and their numbers are retired from this page — they
answered questions about *previous* forms and are not comparable with §2
 (different context/pool sizes, different concurrency ceiling, indexer off, pre-SD-1
 accounting):

- **Form B — tuned reference (1 M ctx / 5 M KV / C12, 2026-09-13)**: full six-stack
 comparison moved to [docs/4DGX-dsv41-基准测试-横向对比-20260912.md](docs/4DGX-dsv41-基准测试-横向对比-20260912.md).
 Its headline decode (100.3 tok/s), prefill (3102/3443/3253 t/s) and aggregate c1–c12
 figures belong to that form only.
- **v19 (0.2.5, #40217 native port) — 2026-09-20 to 2026-09-23**: the board that held
  this page until the 0.2.8 matrix replaced it. Archive [`data/prv3-v19-40217prep-20260920/`](data/prv3-v19-40217prep-20260920/);
  it is the last board measured on the v18-era stack and is **not cell-for-cell
  comparable** with §2 (different engine build and operator set).
- **PR-v2 / PR-v3@4096 / v14 / v18 PR boards**: kept as audit archives under
  [`data/`](data/) (`sd1-20260918/pr/`, `prv3-20260918/`, `prv3-v14-20260919/`,
  `prv3-v18-20260919/`) — quote §2 of this README instead.

## 6. Repo contents

- `start.sh / start-tp4.sh / stop.sh / boot.py` — serving orchestration, pinned
  checkpoint boot, smoke + warm-up
- `adapter/` — SGLang patches (Engram row store C++, MXFP8 backend, shared-expert
  K pad, prefill cache hook)
- `sglang-overlay/` — **host overlay slot** for the fused DeepSeek-V4 decode operators
  grafted over the image's sglang tree (Layer 2 above). It is consumed **only** in
  development mode (`SGLANG_CODE_MOUNTS=1`); production (`=0`, the default) takes its
  code from the image alone. ⚠️ This directory is **not** byte-synchronized with any
  published image yet — to check the code that production actually runs, use the image
  plus the per-file digests in
  [RELEASE-NOTES §2.4](docs/release-notes/RELEASE-NOTES-v0.2.8.md). See
  [`sglang-overlay/README.md`](sglang-overlay/README.md)
- `b12x-site/` — vendored b12x CuTe-DSL kernel library (Layer 1 above)
- `gateway/` — **streaming-aware concurrency proxy** (the `:8001` gateway in front of
  the engine): SSE heartbeat, TTFT budget, backpressure admission, equivalence
  dedup, disconnect propagation, `/gw/metrics`, optional `enable_thinking` injection,
  and image-placeholder sanitization — a client that serializes a past-turn image as
  literal text would otherwise be answered with a hard `400` and a dead conversation.
  Ships a sanitized `.env.example` (all 16 knobs documented), a systemd unit sample and
  a 15-assertion unit test; no internal hostnames, ports or URLs. See
  [`gateway/README.md`](gateway/README.md) for the lineage table and the equivalence
  argument
- `scripts/` — SSH helper, `verify/` probe kit, self-heal monitor + systemd unit,
  `gate.sh`, `nccl_selfcheck.sh`, `verify_release_artifact.py` (**offline** archive
  verifier: blob integrity + content identity, no cluster needed), and the four
  repository checks (`check_redaction.py`, `check_relative_links.py`,
  `check_report_tables.py`, `check_env_coverage.py` — the launcher↔template contract)
- `benchmarks/` — the harnesses that produced the tables, with a
  [harness-to-archive map](benchmarks/README.md), the
  [SD-1 protocol](benchmarks/README.md), the
  [redaction policy](benchmarks/README.md), and
  [§3.2 on the engine's prefill admission law](benchmarks/README.md)
- `bench/` — gate suite (needle / corruption / termination / code-gate), vision gate,
  prose, GSM8K, third-party-shaped sweep, MoE numeric/capacity ladders
- `data/` — **raw benchmark archives**. Current authority:
  [`data/luz028-matrix-20260923/`](data/luz028-matrix-20260923/) (PR, 40/40 cells at
  `chunk 8192`, per-stream raw records + `TABLE.md` + run identity) and
  [`data/luz028-de-sd1-20260924/`](data/luz028-de-sd1-20260924/) (DE, 20/20 cells on the
  SD-1 protocol, per-stream records, 3 waves, re-run against the 0.2.4 baseline). Then
  the lineage `prv3-v19-40217prep-20260920/`, `prv3-v18-20260919/`,
  `prv3-v14-20260919/`, `prv3-20260918/`; the 2026-09-18 SD-1 arms under
  `sd1-20260918/` (DE matrix with per-stream records, the grammar A/B, the fp4
  short-output arm, gateway-vs-direct, and the two GSM8K runs); and the two superseded
  PR archives kept for audit (`data/prv3-20260918/`, `data/sd1-20260918/pr/`). The
  offline audits of the published archives are recorded under
  `data/release-artifact-20260918/` (v0.2.4 pack) and
  [`data/release-artifact-20260923/`](data/release-artifact-20260923/) (0.2.8 tar: md5,
  9/9 blob digests, layer-chain decompression check, identity reproduction). Every
  published figure is re-derivable from these files; [`data/README.md`](data/README.md)
  says how, and names the one column that is not
- `.env.tp4.example` — the configuration this repo runs (sanitized template; the live
  `.env.tp4` is gitignored). Key-by-key comparison against the 0.2.8 production file,
  the four `IMAGE` sites, and the 0.2.8 delta list:
  [docs/CONFIG-v0.2.8-ENV.md](docs/CONFIG-v0.2.8-ENV.md)
- `BUILD-IDENTITY.md` — image IDs, SGLang commit, component versions, artifact hashes,
  and the exact identity formula to check an image against
- `docs/` — deployment plan, upstream ISSUE/PR survey, benchmark comparison, the
  final metrics board, the [release notes](docs/release-notes/),
  [the env template ↔ production key-by-key](docs/CONFIG-v0.2.8-ENV.md),
  the [operator inventory & rollback ledger](docs/operators/) (§4's evidence base),
  [the autotune-golden lock & rebuild runbook](docs/operators/AUTOTUNE-GOLDEN-RUNBOOK.md)
  (why the FlashInfer tactics table is pinned, and the quality gate a re-draw has to pass),
  and [engineering-assurance reports](docs/engineering-assurance/) (the 0.2.8 matrix
  window + the DE SD-1 verdict, in their sanitized published form)

---

## 7. Image download (release artifact)

**Current artifact — `v0.2.9` (2026-09-30).** The serving image (**13.1 GiB**) is distributed
via cloud drive (two mirrors):

- **Quark Drive**: https://pan.quark.cn/s/aa6b189231e3
- **Baidu Netdisk**: https://pan.baidu.com/s/1-LvoV_xtF4hJKp5qaQH90g?pwd=luzi (extract code: `luzi`)
- **File**: `LuZ-0.2.9-dsv41-tp4-dgxspark.tar` — a **plain (uncompressed) OCI tar**, so
  `docker load -i` works without `zstd`
- **Size**: 14,055,778,304 bytes (13.09 GiB)
- **SHA256**: `c1840255408f8b8b012279153580d1310f5d7d9bc4f5aa4e4181bcc8bf23fb0d`
- **MD5**: `3562a789ec0e9aa4bc80a7e54ba1be65`
- **Content identity**: **`355a5e45cb2725ae`** (**5 layers**) — loading it restores
  `dsv41-sglang-optimized:0.2.9-ep1q2-fin2`.

Recorded offline audit and identity data for this file:
[`data/release-artifact-20260930/`](data/release-artifact-20260930/) — the verifier's
console transcript, its machine-readable JSON, the 16-member blob manifest, and the
standalone layer-chain log, so you can check every number below without downloading
13 GiB. The same one-liner reproduces it:

```bash
python scripts/verify_release_artifact.py LuZ-0.2.9-dsv41-tp4-dgxspark.tar \
  --md5 --expect-md5 3562a789ec0e9aa4bc80a7e54ba1be65 \
  --expect-identity 355a5e45cb2725ae --layer-chain
```

**Fleet-wide distribution check** (run after deploying, before you trust a benchmark
number; shipped with this release — see
[`scripts/verify_fleet_distribution.sh`](scripts/verify_fleet_distribution.sh)):

```bash
./scripts/verify_fleet_distribution.sh \
  --image dsv41-sglang-optimized:0.2.9-ep1q2-fin2 \
  --identity 355a5e45cb2725ae --expect-layer-count 5 \
  --nodes <head-node> <worker-rank1> <worker-rank2> <worker-rank3>
# → four nodes agree, and agree across nodes ⇒ RESULT: PASS (exit 0)
```

It asserts **presence first, then identity**. `docker image inspect … | sha256sum` on a
missing image does not fail — it returns a plausible constant (`e3b0c442…` = `sha256("")`,
`01ba4719…` = `sha256("\n")`), so two nodes both missing the image would **pass** a naive
comparison. Identity is therefore never computed from a missing image.

Then load on all four nodes (all of them need the image) and re-check identity locally:

```bash
docker load -i LuZ-0.2.9-dsv41-tp4-dgxspark.tar   # restores dsv41-sglang-optimized:0.2.9-ep1q2-fin2
docker image inspect -f '{{join .RootFS.Layers " "}}' dsv41-sglang-optimized:0.2.9-ep1q2-fin2 \
  | sha256sum | cut -c1-16      # expect: 355a5e45cb2725ae
```

**Previous artifact — `v0.2.8` (2026-09-24)**, kept because its 50-cell PR matrix is the
matrix of record for that base:

- **Quark Drive**: https://pan.quark.cn/s/ca93fedc6376 (extract code: `RHdj`)
- **Baidu Netdisk**: https://pan.baidu.com/s/17IDk222FbLkLKTIqBJ6AzQ?pwd=luzi (extract code: `luzi`)
- **File**: `LuZ-0.2.8-dsv41-tp4-dgxspark.tar`
- **Size**: 14,002,663,936 bytes (13.0 GiB / 13.04 GiB)
- **MD5**: `a9d4cdf932203f173df7556aa511fee1`
- **SHA256**: `6c94745b261eb01a6bea9864af443d0e89583562c624926b30f9dfbc771ec3a4`
- **Content identity**: **`4cca364c46778423`** (3 layers) — a 14-member OCI layout
  (9 blobs + `index.json` + `manifest.json` + `oci-layout` + 2 directory entries).

> **Check the hashes, not the filename or the size.** Adjacent versions are nearly
> indistinguishable by size: 0.2.8 differs from 0.2.4 by only 604,160 bytes (+0.0043 %),
> and 0.2.9 differs from 0.2.8 by +0.38 %. The recorded offline audit of the 0.2.8 file
> (md5, 9/9 blob digests, layer chain, identity reproduction) is checked in under
> [`data/release-artifact-20260923/`](data/release-artifact-20260923/).

Verify before you load anything (no cluster, no docker daemon, no GPU needed):

```bash
python scripts/verify_release_artifact.py LuZ-0.2.8-dsv41-tp4-dgxspark.tar --md5 \
  --expect-identity 4cca364c46778423 --layer-chain
# md5 MATCH · 9/9 blob sha256 verified · 0 unreferenced blobs
# content identity 4cca364c46778423 · layer chain 3/3 decompress to their config diff_id
# RESULT: PASS  (exit 0)
```

That one-liner is the formula `start.sh`'s own preflight and boot banner use, so a passing
local check means the fleet-level check will pass too. **Do not** verify by layer count, by
`docker images SIZE`, or by `docker image inspect --format '{{.Id}}'` / `{{.Config}}`:
those report objects that legitimately differ between the head and the workers (or between
`docker images` versions) while the *content* is identical, so they manufacture false
"the four nodes disagree" alarms. What binds an archive to a running fleet is the
**layer list**, and the exact serialization matters: the same three layer digests serialize
**seven** different ways and hash to **seven** different values — only the
space-joined-with-trailing-newline form (`{{join .RootFS.Layers " "}}` piped into
`sha256sum`, i.e. `4cca364c46778423`) is authoritative. All seven, plus the empty-input
trap (`01ba4719c80b6fe9` = a **missing** image, not an identity), are in
[BUILD-IDENTITY.md](BUILD-IDENTITY.md).

### Bringing it up

The image is only half of it — the launcher needs your cluster's four site keys
first. On the first run it copies the template for you and tells you to edit it:

```bash
./start-tp4.sh doctor      # creates .env.tp4 from .env.tp4.example, then reports
                           # connectivity + GPUs + checkpoint
$EDITOR .env.tp4           # the 4 site keys: HEAD_IP / WORKER_IPS / WORKER_HOSTS / WORKER_USER
./start-tp4.sh share       # head exports its checkpoint over NFSv4 on ConnectX
./start-tp4.sh serve       # workers first, then head — API on :8899
```

`./start.sh help` prints the full subcommand list (`doctor | pull | build | pack |
download | share | mount | sync | serve | stop | status | logs | smoke | ncclcheck |
gate`). `start-tp4.sh` is a thin wrapper that pins `ENV_FILE=.env.tp4` and
delegates to `start.sh`; the legacy 3-Spark profile (`.env`, `start.sh`) is still
in the tree, but it is not the profile this release was measured on (see the
`Profiles:` block at the top of `start.sh`).

Two things no template can hand you:
- the `PEER_HCA_RANK*` wiring map — derive it from a `NCCL_DEBUG=INFO` first boot
  (§8) or from the three steps written inside `.env.tp4.example`
- the weights — `MODEL_DIR` / `WORKER_MODEL_DIR*` point at `$HOME/NewModels/…`,
  and the checkpoint is not distributed with this repository. **Do not just pull
  `main` from the Hub**: the launcher pins an exact revision, and `start.sh`
  already knows how to fetch it — see the weights rows in the table below

### Prerequisites — what this repository does *not* give you

The repo is a **recipe and an operations layer**, not a turnkey appliance. The list below
is what a deployer must supply that is **not in the tarball**. Every item is checked
against what is actually in the pack; if a row says "not shipped", do not go looking.

| Requirement | Status |
|---|---|
| **4× NVIDIA DGX Spark (GB10, SM121)** | hardware |
| **Switchless RoCE ring between them** (ConnectX-7; the launchers assume 4 nodes = 1 head + 3 workers) | hardware |
| **~121.63 GiB unified memory per node** (Grace–Blackwell UMA — host RAM *is* device memory) | hardware |
| **NVIDIA driver `580.173.02` + CUDA 13.0** | host, **not shipped** — the kernels bind to this pair (see §4) |
| **Ring-only NCCL 2.30.7** (`/opt/nccl-ringonly/libnccl.so.2.30.7`, LuZ lineage) + `libncclpin` shim | host, **not shipped**; the lineage project is **Apache-2.0** (see [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) §2) |
| **Model weights** `deepseek-ai/DeepSeek-V4.1-Flash` | **not shipped**, but *fetchable*: `./start.sh download` runs `hf download deepseek-ai/DeepSeek-V4.1-Flash --revision fb2764a5cf321eaa5070ca8f9e892818f477c16d` (the revision `start.sh` and `boot.py` both pin) into `MODEL_DIR` and symlinks it to `/var/tmp/DeepSeek-V4.1-Flash`. Needs the `hf` CLI — `pip install -U huggingface_hub[cli]`. It **skips** when `config.json` plus ≥`EXPECTED_SHARDS` (=48) `model-*-of-*.safetensors` are already present |
| **The 48-shard checkpoint layout** the launcher asserts | the `-0731` MXFP4 checkpoint is 48 shards (`model-000NN-of-00048.safetensors`); `EXPECTED_SHARDS` is the count both the downloader and the boot check use. A Hub `main` that has been re-sharded trips it |
| **Free disk for the image**: 13.09 GiB tar + ~40 GiB unpacked, **on each of the four nodes** | sizing note |
| **The 4 site keys** (`HEAD_IP`, `WORKER_IPS`, `WORKER_HOSTS`, `WORKER_USER`) | yours to fill in `.env.tp4` |
| **The `PEER_HCA_RANK*` wiring map** | derivable — three steps are written in `.env.tp4.example`; verify with `./start-tp4.sh ncclcheck` |
| **A watchdog / self-heal process** | **not shipped, and the one you might find is a trap.** `scripts/systemd/dsv41-head-monitor.service` *is* in this repository and its first line reads as an install instruction — but its `ExecStart` launches `scripts/dsv41-monitor-head.sh`, which self-declares `[RETIRED-20260920]`, was never wired, and does not even pass `bash -n` (line 33 puts the placeholders `<WIP_R1> <WIP_R2> <WIP_R3>` in command position). The unit is `Restart=always`, so installing it yields a permanent restart loop. **Do not install it.** The production self-heal is a site object (systemd user units `dsv41-serve.service` + `oom-gate-monitor`). See [`docs/4DGX-DSV41-Flash-部署方案-20260911.md`](docs/4DGX-DSV41-Flash-部署方案-20260911.md) Phase 3 |
| **A gateway / concurrency proxy** | the `gateway/` tree is source, not a service — you provide the unit that runs it |
| **The model's own checkpoint layout** (`/models/DeepSeek-V4.1-Flash` in-image path) | see [`BUILD-IDENTITY.md`](BUILD-IDENTITY.md) |

> **Before you trust a number.** Load the image, then run
> `./scripts/verify_fleet_distribution.sh` (§7). Two nodes both *missing* the image will
> otherwise agree with each other, because `docker image inspect … | sha256sum` on an
> absent image returns a plausible constant rather than failing.

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
hit in a blocker class. **The checker is itself checked**: injecting a known-bad path and
a known node hostname into the tree makes it fail (`exit 1`), removing them makes it pass
(`exit 0`) — a scanner that has never been shown to fail proves nothing. The 0.2.8
archives (`data/luz028-matrix-20260923/`, `data/luz028-de-sd1-20260924/`,
`data/release-artifact-20260923/`) were scanned with the same fail-closed run.

The repository's default branch is **`main`**, and **the adaptation lives on `main`** —
this is a standalone engineering snapshot, not a branch of the upstream project.
Upstream lineage is credited below and in [BUILD-IDENTITY.md](BUILD-IDENTITY.md).

| Component | Origin | License |
|---|---|---|
| SGLang serving recipe (boot, adapters, Engram row store, DSpark setup) | [`ntxf31415/DeepSeek-v4.1-Flash-DGX-Sparks`](https://github.com/ntxf31415/DeepSeek-v4.1-Flash-DGX-Sparks) (also published as `MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks`) | AGPL-3.0-or-later |
| Recipe lineage / benchmark methodology | [`0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000`](https://github.com/0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000) | MIT |
| Host ring-only NCCL 2.30.7 build + `libncclpin` core-pinning shim (host-side, not shipped) | [`luxingcom/aicad-nccl-optimization`](https://github.com/luxingcom/aicad-nccl-optimization) (LuZ lineage) | **Apache-2.0** ([`LICENSE`](https://github.com/luxingcom/aicad-nccl-optimization/blob/main/LICENSE), added 2026-09-20) |
| Model weights | `deepseek-ai/DeepSeek-V4.1-Flash` (Hugging Face) | see model card |

**Sister projects:** [DeepSeek-V4-Flash-Vision-Exp TP4 switchless-ring](https://github.com/ntxf31415/deepseek-v4-vision-exp-dgxspark-tp4-switchless-ring) (vLLM, same ring base) · [GLM-5.3-Flash NVFP4 TP4 switchless-ring](https://github.com/ntxf31415/glm-5.3-flash-nvfp4-4x-dgx-spark-switchless) (companion recipe).

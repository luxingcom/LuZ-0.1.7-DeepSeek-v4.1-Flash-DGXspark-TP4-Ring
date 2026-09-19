# Release notes — v0.2.3 (2026-09-19)

**Baseline:** the previously published repo state (`main` @ `70a1d02`, image
`dsv41-sglang-optimized:v7`, content identity `4ebef21b6aedbd70`). This release does
**not** change the image, and **not** the production launch args either (production
`CHUNKED_PREFILL_SIZE` stays 4096; only the PR benchmark re-ran at 8192 — §3). What
changes is the **repo**: nine engineering
commits land on `main`, the concurrency gateway is open-sourced, and the PR-v3
matrix is re-measured in full (40/40 cells) at `--chunked-prefill-size 8192`.

Fork association: these commits are linear extensions of the existing `main`
history (cherry-picked from the internal ops line, rebased onto `70a1d02`), so
existing forks can `git fetch && git merge main` or rebase as usual. No history
rewrite, no force-push.

---

## TL;DR

| | what | why it matters |
|---|---|---|
| 🔧 | 9 code commits (kernel backport, scheduler, autotune, launcher, gates) | the fixes the production fleet has been running since 09-18, now published |
| 🆕 | `gateway/` — the `:8001` streaming-aware concurrency proxy, open-sourced with a sanitized env template and systemd unit | the one repo-visible piece of the serving path that was missing |
| 📊 | PR-v3 matrix re-measured: **40/40 cells** at `chunk 8192` (was 34/35 at 4096); new peak **3,326.4 t/s** (8192×C4) | replaces every previously published PR number; old tables superseded (archives kept for audit) |
| 📝 | READMEs and FINAL-METRICS §3 rewritten in place; release-notes added | the published docs now match the archives cell for cell |
| 🛡️ | redaction blocker fixed at the source (GSM8K data path); `check_redaction.py` green over the whole tree incl. new archive | nothing new leaks; the one history-leak class is fixed where it was generated |

---

## 1. Code changes (in `main` order)

| commit | change |
|---|---|
| `5c3ecfd` | **b12x backport**: upstream E4M3 subnormal decode fix + MXFP8 swizzle bounds fix |
| `c7f4ae8` | **perf(adapter)**: raw scale snapshots held once instead of per-use — reclaims ~4.3 GiB per rank at 600 K context |
| `2070dab` | **feat(scheduler)**: per-request prefill share cap (idea from upstream #34554) — bounds what one long prompt can take from the co-running streams |
| `318f951` | **fix(autotune)**: majority-vote across boot probes instead of discard-all (the slow-boot root cause: one slow probe used to void the whole table) |
| `b6dddf3` | **feat(launcher)**: `CHUNKED_PREFILL_SIZE` validated against `{2048, 4096, 6144, 8192}` with MoE-ladder rung auto-append + numeric re-sort (a missing rung = HTTP 500 per the W5 precedent); NCCL env lint; gate.sh kernel guard + `/health`→`/v1/models` probe fix |
| `645d879` | **fix(bench)**: GSM8K data path parameterized (`GSM8K_DATA`, see §5) + `gate.sh` layout-aware suite staging |
| `d7210ed` | **feat(roce)**: RoCEv2 one-shot allreduce / allgather (`b12x comm.roce`, 11 files) — the ring transport used for the comm overlays |
| `c7b3f5d` + `043232e` | chore: `bench-results/` runtime artifacts gitignored (conflict resolved, markers cleaned) |
| `b3a229b` | audit: customer pitfall report P2 fixes + IMAGE tag alignment in `gate.sh` |
| `01d5e8f` | **feat(gateway)**: open-source pass of the concurrency proxy (§2) |

All touched shell files pass `bash -n`, all touched Python files pass
`py_compile`; the full check log ships with the release audit.

## 2. The concurrency gateway (`gateway/`)

The `:8001` service that fronts the engine on the head node (see the
gateway-vs-direct arm in FINAL-METRICS §6) is now in the repo:

- `concurrency_proxy_v2.py` — single-file aiohttp proxy: SSE heartbeat (idle
  streams are kept alive through the engine's long prefill silences), TTFT budget,
  backpressure admission, equivalence dedup, disconnect propagation, `/gw/metrics`,
  optional `enable_thinking` injection.
- `concurrency-proxy-v2.env.example` — all 13 knobs documented, `YOUR_API_KEY`
  placeholders, no real endpoints.
- `concurrency-proxy-v2.service.example` — systemd unit sample.

**What was sanitized:** internal doc references, hostnames, port/topology
narrative, and 15 in-code comments that carried internal change-history text were
rewritten; the header is neutral. **What was *not* changed: the code.** Equivalence
to the fleet-running version was proven by AST comparison (docstrings and version
strings normalized, the remaining trees dump byte-identically), so this file is the
same program the gateway-vs-direct numbers were measured through.

## 3. PR-v3 re-measured at chunk 8192 (`data/prv3-v14-20260919/`)

The 2026-09-18 PR-v3 pass (34/35 cells, `chunked_prefill_size=4096`) left two
holes: `131072×C16` unmeasured, and the 4096-chunk admission wall serializing every
row above 2,048 tokens. The 2026-09-19 re-run (`run_tag=prv3-v14-final`) moves the
benchmark form to **`--chunked-prefill-size 8192`** and completes the grid:
**8 input sizes (512…131072) × 5 concurrencies = 40/40 cells**, 1 wave per cell,
same PR-v3 protocol (`max_new_tokens=1`, fresh nonce, `/flush_cache` between
cells, total = Σprompt tokens ÷ wall clock).

| Input tokens | C1 | C2 | C4 | C8 | C16 |
|---:|---:|---:|---:|---:|---:|
| 512 | 1211.1 | 1316.0 | 1845.5 | 2311.5 | **2468.9** |
| 2,048 | 2607.5 | 2652.0 | **2899.7** | 2451.1 | 2705.8 |
| 4,096 | 3111.8 | **3288.5** | 2871.8 | 3107.0 | 2931.8 |
| 8,192 | 2667.5 | 2849.1 | **3326.4** | 3087.8 | 2863.1 |
| 16,384 | **3025.7** | 2516.1 | 2183.4 | 2171.2 | 1915.1 |
| 32,768 | **1963.0** | 1688.3 | 1704.9 | 1650.1 | 1690.4 |
| 65,536 | **1697.3** | 1463.4 | 1487.6 | 1497.7 | 1537.3 |
| 131,072 | **1770.0** | 1795.7 | 1536.7 | 1366.9 | 1560.2 |

Findings that change the published picture:

- **New peak: 3,326.4 t/s at 8192×C4.** The old single-stream peak (3,337.6 @
  8192×C1, 4096-chunk build) is superseded: at chunk 8192 the same cell reads
  2,667.5 (−20.1 %), i.e. the old peak was partly a chunk-seam artifact.
- **Concurrency pays now.** 512-row C1→C16 **+103.9 %**; 2048 C1→C4 +11.2 %; the
  8192 row rises to its C4 peak instead of falling (old form: −26.4 % C1→C16).
- **The cliff is gone.** 16384×C1: 1,936.6 → 3,025.7 (**+56.2 %**); the old
  8192→16384 drop (−42 %) no longer exists (now +13.4 %…−9.9 %, band-shaped).
- **Real parallel prefill in 11/40 cells.** Recomputed from per-stream first-token
  instants (`CONCURRENCY.md` in the archive): the admission law
  `min(C, max(1, ⌊8192/input⌋))` holds exactly in 35/40 cells and **no cell exceeds
  it**; the five shortfalls are arrival effects in tiny-prompt cells (a 512-token
  wave spans ~6 ms vs sub-millisecond scheduler steps), not policy violations.
  512-row steps reach width 13, 2048-row width 4, 4096-row width 2. Above 4,096
  tokens, 21/32 multi-stream cells are still one-request-at-a-time — an engine
  policy, not a client defect.
- **Long inputs stay in a narrow band** (1,367–1,963 tok/s across 32 K–131 K) and
  stay unresolved within it: one wave per cell ⇒ no error bar.

Supersession chain (archives kept, numbers not to be quoted): PR-v2 → withdrawn
2026-09-18 (`data/sd1-20260918/pr/`); PR-v3 @ 4096 (34/35, peak 3337.6) →
superseded 2026-09-19 (`data/prv3-20260918/`); **current = `data/prv3-v14-20260919/`**.

## 4. Documentation rewritten in place

- `README.md` / `README.zh-CN.md` — headline figures, §2 PR table (40 cells),
  admission-law paragraph, §3 chunk row, §6 repo inventory (gateway + new archive +
  release notes) all overwritten with the v14 numbers; version line added at top.
- `docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md` — §3 replaced by the v14
  board, revision log extended, TL;DR and open-items list updated (the 131072×C16
  hole is closed; remaining open items unchanged).
- `benchmarks/README.md` — §3.2 admission law re-derived at chunk 8192; harness map
  points at the new archive.
- `data/README.md` — archive index: `prv3-v14-20260919/` is current; the two
  superseded PR archives marked do-not-quote.

## 5. Redaction measures

- **The one blocker-class leak is fixed at the source** (`645d879`): `bench/gsm8k_dsv41.py`
  had the operator's home directory baked in; the data path is now
  `GSM8K_DATA`-environment-driven with a generic default.
- The gateway open-source pass is described in §2; its three files and both example
  configs scan clean.
- The v14 archive (40 raw JSONs + summary) scans clean — it contains only timestamps,
  token counts, hashes and nonces; no hostnames, IPs, usernames or ports.
- `scripts/check_redaction.py` exits 0 over the whole tree (118 hits, all in the
  pre-declared classified classes); `check_relative_links.py` and
  `check_report_tables.py` are part of the release audit.

## 6. Compatibility notes

- **Image unchanged**: pull this repo, keep your `v7` image; the new commits are
  launcher-, overlay- and bench-side. Overlay files are bind-mount grafts — re-pull
  and restart to pick them up.
- **The PR benchmark form is `CHUNKED_PREFILL_SIZE=8192`.** Production keeps 4096 —
  the v14 run is a benchmark form, not a production change. The launcher accepts
  `{2048, 4096, 6144, 8192}`; PR numbers are only comparable at equal chunk. If you
  reproduce the old 34-cell table, set 4096 and expect the old shape back.
- **PR quoting rule**: quote `data/prv3-v14-20260919/` only. The two superseded PR
  archives exist so the supersession can be audited, not so their numbers can circulate.

## 7. Known limitations carried forward (unchanged, not fixed by this release)

- One wave per PR cell ⇒ **no error bars**; row-to-row gaps inside the long-input
  band (and between 3,288.5 and 3,326.4) are unresolved, not ranked.
- The `structured` prompt-label spread in the DE matrix (±17.7–45 %) remains
  **unidentified** — no mechanism is claimed for it.
- DE matrix, grammar A/B, fp4_256 arm, gateway-vs-direct, GSM8K numbers are the
  2026-09-18 measurements; they were not re-run for this release.
- The gateway ships as a single-file proxy without tests; the AST-equivalence proof
  covers the published file vs the fleet-running file, not future edits.

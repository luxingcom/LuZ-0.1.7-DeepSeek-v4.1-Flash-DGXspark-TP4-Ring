# `benchmarks/` — the harnesses behind the published numbers

Every figure in `README.md` §2 and in `docs/03-final-metrics/` was produced by one of the
files in this directory or in `bench/`. This directory holds the ones that shape a
*row* of a published table; `bench/` holds the quality gates and the ad-hoc probes.

All of them speak **one** convention, **SD-1**, defined in
[`../docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md`](../docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)
§1 and implemented once in `sd_protocol.py`, which every reporting harness imports. The
convention and the wave count are also written **into each emitted JSON**, so a reader of
an archive never needs this page to interpret it.

If you want to re-derive a number rather than trust it, start here and in
[`../data/README.md`](../data/README.md).

---

## 1. Which harness produced which archive

| harness | what it measures | archive it produces | published in |
|---|---|---|---|
| `sd_protocol.py` | **the shared protocol module**: `new_nonce()`, `build_prompt()`, `stream_chat` / `stream_generate`, per-stream accounting, `aggregate_wave`, `dump` | — | FINAL-METRICS §1 |
| `de_matrix_v3.py` | DE matrix, 4 prompt-label types × 5 concurrencies × 3 waves, **no grammar**, force-filled budget | `../data/sd1-20260918/de/` (20 cells + 20 raw records) | FINAL-METRICS §4 |
| `pr_matrix_v2.py` | ⚠️ **superseded — its archive is withdrawn as a baseline (2026-09-18).** Kept source-only so the withdrawal can be audited: it did not flush the radix cache between cells, could not distinguish parallel prefill from queued prefill, and reported per-stream rates rather than total throughput | `../data/sd1-20260918/pr/` (35 cells) — **numbers must not be quoted** | — |
| `pr_matrix_v3.py` | **PR-v3, the current PR harness.** Pure-prefill total throughput: `max_new_tokens=1`, fresh nonce per request, `POST /flush_cache` between cells, total = `Σ(prompt tokens) / wall-clock (arm start → last stream end)`. 7 sizes (2048…131072) × 5 concurrencies, 1 wave | `../data/prv3-20260918/` (34 cells + 34 raw per-stream records) | FINAL-METRICS §3 |
| `pr_v3_concurrency.py` | **re-analysis, not a new measurement.** Clusters the archived per-stream first-token instants to decide whether a cell really prefilled more than one request per step. Needed because `ttft_overlap_peak` is degenerate when `max_new_tokens=1` (`t_end − t_first ≈ 0.1 ms`, so the span sweep can never reach 2) | consumes `../data/prv3-20260918/raw/` | FINAL-METRICS §3.3 |
| `pr_engine_steps.py` | the **third** evidence channel for the prefill admission law: attributes the scheduler's own `Prefill batch` lines to cells by wall-clock window and tests `max #new-seq`, `sum #new-token == C x input` and `max #queue-req` against the prediction | `../data/sd1-20260918/pr/engine-steps.log` (the pr-window lines) + a per-cell table | FINAL-METRICS §3 |
| `grammar_ab.py` | guided-decoding cost: `sampling_params.json_schema` present vs absent, same prompt body, separate nonces | `../data/sd1-20260918/grammar/`, `.../grammar2/` | FINAL-METRICS §5.1 |
| `gw_ab_v2.py` | the `:8001` gateway vs direct `:8899`, three arms (prefill / decode / **wall, not streamed**) | `../data/sd1-20260918/gw/` | FINAL-METRICS §6 |
| `cache_effect_probe.py` | **what a repeated prompt is worth**, at 2k / 32k / 131k | `../data/sd1-20260918/cache/` | FINAL-METRICS §8 |
| `channel_ab.py` | chat channel vs native `/generate` on an identical unconstrained prompt, alternated within each wave | `../data/sd1-20260918/channel/` | FINAL-METRICS §5.2 |
| `preflight_sd1.py` | 5 protocol checks, including the **nonce regression gate** (§8) | — | §8 |
| `render_report_tables.py` | renders the tables in FINAL-METRICS §4–§8 from the SD-1 archives. Exits non-zero and names the missing stage rather than emitting an empty table | `../data/sd1-20260918/TABLES.generated.md` | FINAL-METRICS §4–§8 |
| `render_pr_v3_tables.py` | renders the two PR-v3 tables (34-cell per-cell, and the 7×5 compressed view) from `data/prv3-20260918/`. Recomputes the concurrency columns from the raw per-stream files, so it does **not** trust `ttft_overlap_peak` | — | FINAL-METRICS §3 |
| `run_sd1_all.sh` | the staged main chain (`de → grammar → fp4_256 → gw → pr`), each stage its own `docker exec`, with a 30 s UMA memory sampler. `STAGES=` runs a subset and `TAG=` reuses a run directory, so a harness change invalidates one stage rather than five | the run directory itself | — |
| `run_sd1_extra.sh` | the closure stages (`cache → channel → grammar2`), run **after** the main chain | appends into the same run directory | — |
| `common_window.py` | re-analysis: delivered throughput while every stream in a wave overlaps | consumes raw per-cell records | (see §6) |
| `sweep.py` | streaming sweep emitting token IDs, for common-window evidence | — | — |
| `matrix.py`, `de_matrix.py`, `de_matrix_structured.py`, `code256_bench.py`, `pr_ab_gw_vs_direct.py` | earlier harnesses, kept source-only for the archives they produced | — (only the current generation is published under `../data/`) | — |
| `../bench/gsm8k_dsv41.py` | GSM8K, 200 questions, 8-shot CoT, temp 0.6 | `../data/gsm8k-20260917/` | README §2, FINAL-METRICS §9 |

> ⚠️ `cache_effect_probe.py` and `channel_ab.py` **must not run while a matrix is
> running**: injecting a 131k-token prefill into a C=1 cell is a contamination, not a
> diagnostic. That is why they are in `run_sd1_extra.sh` and not in the main chain.

`bench/` (quality gates, not tables): `gates_suite.py` (needle gradient / Hangul
corruption / termination / code gate), `vision_gate.py` (both-direction red/blue
image check), `prose_bench.py`, `bench_tp.py` (third-party-shaped sweep),
`moe_a8_*` + `moe_bakeoff.py` (kernel-level numerics and capacity ladders),
`matrix_v1.py` (the earlier `/v1`-shaped implementation of `matrix.py`).

---

## 2. Running them

Each harness talks to a live engine over loopback; none of them need a cluster
scheduler, and none of them start or stop containers.

```bash
# engine on 127.0.0.1:8899, key in a one-line file (default $DSV41_STATE/api-key)
export KEY_FILE=$DSV41_STATE/api-key
export CONCURRENCIES=1,2,4,8,16
export OUT_DIR=/tmp/de-out
python3 benchmarks/de_matrix_v3.py
```

The staged chain (run this from the head node; it drives `docker exec` itself):

```bash
bash benchmarks/run_sd1_all.sh                       # all five stages, fresh run dir
bash benchmarks/run_sd1_extra.sh                     # then the closure stages

STAGES=pr TAG=sd1-20260918T060913 bash benchmarks/run_sd1_all.sh   # re-measure one stage
                                                                  # into an existing run dir
```

`STAGES` and `TAG` exist because a harness change invalidates exactly one stage, and
re-running five to refresh one is not a trade anyone should have to make. The run log is
**appended to**, never truncated: the earlier stages' exit codes and timings are the
record of the run being extended.

Two environment variables are load-bearing for the PR matrix and easy to get wrong:
`REQUEST_TIMEOUT` must exceed the 524288 row's queue wait (the default was raised from
3600 s to 7200 s for exactly this reason), and `CHUNKED_PREFILL_SIZE` must match the
engine's `--chunked-prefill-size`, or the `Prefills/step (pred)` column will predict
something the engine is not doing.

**The PR stage needs a second, separate pass over the engine log.** The engine's own
step lines live in the head node's `docker logs` capture, not in the run directory, so
after the PR stage completes:

```bash
# ENGINE_LOG: the timestamped `docker logs -f dsv41-head` capture
python3 benchmarks/pr_engine_steps.py "$RUNDIR" "$ENGINE_LOG" \
        "$RUNDIR/pr/engine-steps.log"
```

It attributes each `Prefill batch` line to the cell whose wall-clock window contains it,
writes the raw lines to the archive, and prints the per-cell table. Cells are matched on
their own retained `t0` / `t_end`, so a wrong `ENGINE_LOG` shows up as cells with no
steps rather than as plausible-looking wrong numbers.

**Provisioning.** Credentials sit behind the `:8001` / `:8899` hops. They are supplied
through the environment or through the serving `.env` (see `../.env.tp4.example`); they
are not, and must not be, in this tree.

**Model names.** Four different model-name strings are in play across this stack
(image tag, gateway alias, engine self-report, upstream probe), and they are *not*
interchangeable. `pr_ab_gw_vs_direct.py` discovers an acceptable name by preflight
instead of hardcoding one — a name that works on one hop can 404 on another.

---

## 3. The SD-1 protocol, and the two things it deliberately did not unify

SD-1 is stated in full in FINAL-METRICS §1. The essentials, for someone writing a new
harness:

| dimension | rule |
|---|---|
| channel | chat `/v1/chat/completions`; **the one exception** is the PR matrix (input size is the independent variable and must be token-exact ⇒ native `/generate` + `input_ids`) |
| output type | `structured` / `prose` / `code` / `json` are **prompt labels**, not grammar constraints. Under SD-1 there is no guided decoding |
| budget | `min_tokens = max_tokens` + `ignore_eos = true` + `stop = []` — every stream hits its budget |
| sampling | `temperature = 0`, `top_p = 1`, thinking off |
| cold prefix | a **fresh nonce per request** (process counter + process salt), placed **first** in the prompt |
| per-stream rate | `decode = (ct − 1) / (t_last − t_first)`, `prefill = prompt_tokens / (t_first − t0)` |
| cell central value | `statistics.median` over **every ok stream of every wave** in the cell |
| aggregates | emitted three ways over **absolute timestamps** — union / intersection (common window) / wall |
| retained | per-stream `t0 / t_first / t_last / t_end` **and** `prompt_sha16`, so "every request was cold" is checkable rather than asserted |

Two things in this suite are **different animals and must not be "unified"**:

- **`512/(right − left)` in `matrix.py` and `sweep.py` is not a prompt length.** That
  `512` is the *token count of the 129–641 window* (641 − 129 = 512) divided by the window
  duration — a fixed physical window, correctly hardcoded. Only `de_matrix.py`'s `512.0`
  was a *prompt-length* numerator, and only there was it an approximation of a value the
  engine actually reports. Replacing the window constant with `prompt_tokens` would be a
  silent corruption.
- **Wave count is part of the measurement, not just a statistic.** 3 waves for DE /
  grammar / fp4, 1 for PR. A single wave and a median-of-three-waves are different
  measurements of the same cell; the count is recorded as `_meta.waves` and per cell so
  nobody has to infer it from which file was run.
- **Two earlier harnesses keep their own rules, on purpose.** `de_matrix.py` (upper median
  `sorted(x)[n//2]`, hardcoded `512.0`, 1 wave) and `de_matrix_structured.py`
  (median-of-wave-medians, xgrammar `json_schema`) are left exactly as they were when
  their archives were produced, because changing either would make their output
  **irreproducible from its own source file** — a worse defect than an inconsistent
  convention. Neither generates a table in `../data/`, so nothing published today depends
  on them.

### 3.1 Where guided decoding went, and the two traps that travel with it

SD-1 removes `json_schema` from the *decode matrix* because a per-token grammar mask is a
different workload, not a different prompt: it makes "structured output" slower than prose
for a reason that has nothing to do with the model. Guided decoding is therefore not
*dropped* by this suite, it is **isolated** — `grammar_ab.py` measures it as its own A/B,
`sampling_params.json_schema` present vs absent, same prompt body
(FINAL-METRICS §5.1).

Two behaviours reproduce on the native `/generate` path and are worth knowing before you
put a grammar in front of production traffic:

1. 🔴 **Passing `json_schema` as a dict kills the engine** — xgrammar raises
   `TypeError: unhashable type: 'dict'`, the scheduler dies and the container exits 247.
   **Always pass a JSON string.** Any caller that can put a dict-shaped `response_format`
   on the wire through the serving gateway can restart the whole stack. Unfixed upstream.
2. 🟠 **Under a grammar, `ignore_eos=True` stops guaranteeing a full budget.** If the
   schema can be satisfied early, EOS still fires and the stream ends short — which then
   contaminates any median that assumes a fixed completion length. Use a constraint that
   cannot terminate early (e.g. `minItems`) if you need the budget filled.

### 3.2 The engine's prefill admission law (measured, not assumed)

The PR matrix measures something the other tables never touch: what this stack does when
the *prompt* is long. The answer is not "it scales", and the reason is in the scheduler.

The engine runs with `--chunked-prefill-size 4096`, so a step's prefill token budget is
4096 tokens **in total**. In `PrefillAdder` (`sglang/srt/managers/schedule_policy.py`) a
request whose prompt exceeds that budget is truncated into a chunk and recorded as the
scheduler's single `chunked_req`; `add_chunked_req` charges the whole step budget to it
and, while it is unfinished, the admission loop has nothing left to give anyone else:

```python
# add_chunked_req, after charging the step budget
return req if truncated else None     # unfinished -> this step admits no new prefill
```

A request at or below the budget is never truncated, is therefore *not* the chunked_req,
and several such requests are admitted into one step. Hence:

```
prefills advanced per step  ==  min(concurrency, floor(chunked_prefill_size / input_tokens))
```

**Above `chunked_prefill_size`, prefill is strictly one request at a time.** That is what
the flat `Agg prefill tok/s` column in the PR table is — it is the single-stream chunked
rate, not a concurrency result — and it is why TTFT there grows with queue position.

Three independent layers agree, and they are all checkable:

| layer | what it is | where |
|---|---|---|
| client | `peak_client_overlap == C` in every cell, so the wave really was simultaneous on the client's side. The dispatch spread — `max(t0) - min(t0)` over the wave — is **derived from the retained per-stream `t0`**, never read from the summary: the summary field named `stagger_s` is the *TTFT* spread and is **not** evidence about dispatch | per-stream `t0` / `t_end` in `../data/sd1-20260918/pr/`; derived by `render_report_tables.py` |
| engine | `sglang:num_running_reqs` / `sglang:num_queue_reqs`, sampled once a second per cell. Read `med` first: `min`/`max` can carry a value from the *previous* cell, because the probe window opens as soon as the previous wave returns and an idle engine does not republish the gauge | `engine_probe` in `../data/sd1-20260918/pr/summary.json` |
| engine log | the scheduler's own per-step `#new-seq`, `#new-token`, `#running-req`, `#queue-req`, `#pending-token` — the direct test of the law rather than a restatement of it | `../data/sd1-20260918/pr/engine-steps.log`, attributed per cell by `pr_engine_steps.py` |

The per-cell evidence table — dispatch spread, peak overlap, engine gauge, and the
`#new-seq` histogram — is generated into the report by `render_report_tables.py` and
`pr_engine_steps.py`. It is not duplicated here, because a second copy of a number
that moves is a second number. Two checks in it are worth stating outright:

- `sum(#new-token) == C x input_tokens` in **every** cell — nothing below the chunk
  budget is ever truncated, so the aggregate is exact rather than approximate; and
- `max(#new-seq) == min(C, floor(chunk / input))` in **every** cell.

One detail those histograms expose: a step's `#new-seq` can come out **below** the law
when fewer requests have arrived yet. At `512`/C=16 the wave spans ~6 ms while the
scheduler steps in well under a millisecond, so the cell runs as `8, 7, 1` rather than
`8, 8`. The law is an upper bound per step; `max #new-seq` is what tests it, and the
histogram is printed so a reader can see arrival order instead of inferring it.

Two things this is **not**:

- **Not a client defect.** The obvious candidate — payload construction inside the worker
  threads, so the GIL staggers the wave — was measured rather than argued about: at
  524288 tokens the `repr`-for-hash plus `json.dumps` of one request is ~55 ms, so a fully
  serialized C=16 wave costs 0.88 s against a cell runtime of ~5000 s (0.02 %). The
  harness builds its payloads before the pool anyway, because a wave that is *supposed* to
  be simultaneous should not carry a launch ramp of its own — but it moved no number, and
  this page says so instead of claiming a fix.
- **Not a misconfiguration.** Chunked prefill is what makes a 524288-token prompt fit at
  all on this box. Raising `--chunked-prefill-size` would let more requests interleave per
  step and is the only lever that changes the shape of this table, but it is a **launch
  change** — a window item, not a harness setting — and it trades against peak memory.
  Recorded in FINAL-METRICS §11.

One more consequence, visible in the small rows: below the chunk size the prefill rate is
limited by **steps per second, not tokens per second**. The step costs about the same
whether it carries 2048 tokens or 4096, so a 2048-token cell at C=2 returns roughly twice
the aggregate prefill of C=1 while using the same number of steps. Above the chunk size
both effects disappear into "one request at a time".

**Re-verified 2026-09-18 on PR-v3 — and one trap worth recording.** `pr_matrix_v3.py`
ships two concurrency signals, and **neither is usable as shipped**:

- `ttft_overlap_peak` is **degenerate** under `max_new_tokens=1`. The single emitted
  token *is* the first token, so `t_end − t_first ≈ 0.1 ms`, and a `[t_first, t_end]`
  sweep can never reach 2 — every cell reports 1 no matter what the engine actually did.
  It is not evidence of serialization; it is an artefact of the output budget.
- `gauge_parallel` reads `sglang:num_running_reqs`, a **1 s sampler**. A 2048 × C1 cell
  lasts 0.84 s and can be missed entirely, so "the gauge never saw >1" is not proof
  either.

The verdict therefore comes from `pr_v3_concurrency.py`, which clusters the archived
per-stream **first-token instants** instead — a stream that shared a prefill step emits
its first token at the same wall instant as its step-mates, and a serialized stream is
one service-time away. The tolerance is derived from the data rather than picked:
within-step jitter is ≤ **0.5 ms** and the smallest between-step gap is **64 ms**, so
10 ms sits inside a two-order-of-magnitude separation. The verdict is stable for any
tolerance in 0.005–0.05 s and only flips 7 cells at ≥ 0.2 s. On that basis the law holds
**34/34** on PR-v3 — including the 2048 row, where the observed width is genuinely 2
(`floor(4096/2048)`) and is the *only* place in the matrix with real parallel prefill.

---

## 4. Sanitization: what is benign, and one class that is not

The scanner is `../scripts/check_redaction.py`. It enumerates classes **independently of
the masker** (`deliverables/…/sanitize_release.py`), records the policy verdict per class,
and exits non-zero on any unclassified hit in a blocker class. Its self-test samples are
assembled from fragments at run time, because writing a real value into the scanner to
prove the scanner can find it would itself be the leak.

### 4.1 Scan hits that are benign — please do not "fix" these

| hit | where | why it stays |
|---|---|---|
| `10.0.0.x` addresses | `.env.example`, `.env.tp4.example`, `stop.sh`, `scripts/verify/*.py`, `files/nfs-share.sh` | the repository's own generic scheme: `10.0.0.1` = head, `10.0.0.2` = worker 1. Used consistently across seven files; the real fabric is a different range entirely |
| `10.0.22.x` / `10.0.23.x` / `10.0.33.x` | same files | part of that same generic scheme (NFS pairs), not the fabric |
| `zurih` | `scripts/verify/ramp2.sh`, `.env.tp4.example` | **upstream author identifier**, not a credential. It appears in the upstream `NOTICE`/copyright lines. Removing it would strip attribution |
| `/home/zurih/...` | `.env.tp4.example` | the upstream author's paths in the upstream kit, carried over unchanged — same class as the entry above, not this deployment's account |
| `?pwd=luzi` | `README.md` §8 | a deliberately published cloud-drive extract code — it is *how* the reader is meant to get the image |
| `/opt/aicad-prod` | `start.sh`, deployment plan | `aicad` is a **published** project name: README's attribution table already links `github.com/luxingcom/aicad-nccl-optimization` as the origin of the `libncclpin` shim. The path reveals nothing not already credited |
| `~189 GiB` | `boot.py:281` | a memory *size*, matching an address-shaped pattern by coincidence |
| `149.8 / 140.3 tok/s` | research reports | throughput pairs; the second value matches a ring-host-octet pattern by coincidence |
| `disk-cache-hit`, `mask-initialization` | `b12x-site/` | matched an `sk-` key pattern mid-word; a left word boundary excludes them |
| `API_KEY = "YOUR_API_KEY"` | `bench/gsm8k_dsv41.py`, `scripts/verify/*` | already the intended public placeholder |
| `password = os.environ.get("WORKER_PASS")` | `scripts/remote.py` | a variable *reference*, not a literal |
| `enp1s0f1np1`, `enP7s7` | `.env.example`, `.env.tp4.example`, `start.sh` | **the driver-assigned interface names of the on-board ConnectX-7**, identical on every GB10-generation DGX Spark — `enp1s0f1np1` for the LAN NIC, `enP7s7` for the RoCE rail. No identity; and `.env.example`'s four fabric keys are the "copy and run" part of the template, so masking them would break the kit to no benefit |
| `rocep1s0f0`, `rocep1s0f1`, `roceP2p1s0f0`, `roceP2p1s0f1` | same files | same argument: stock RoCE HCA names for that board, not deployment-specific |

The two categories that produce real false positives are **numeric coincidence** (a
throughput figure shaped like an address fragment) and **mid-word substring matches** —
the string `disk-cache-hit` contains the three characters a naive key pattern reads as a
key prefix, so the scanning pattern is anchored to a token boundary rather than left free
to match mid-word. Both are pinned as regression cases in the scanner's self-test.

> A trap worth recording, because one draft of this paragraph walked into it: an earlier
> version abbreviated an example by eliding its middle with a Unicode ellipsis, and that
> **reintroduced the exact false positive it was describing** — the ellipsis is not a word
> character, so the boundary anchor no longer applied. **Documentation that quotes a
> pattern is executable as far as the pattern is concerned.** Quote the whole token, or
> none of it.

### 4.2 The class that is *not* benign — masked, not classified

`PEER_HCA_RANK0..3` must **never** appear in the clear. On a 4-node ring that map encodes
the physical cabling: which port of which node joins which two peers. It is the one thing
about this fabric that is not generic (`NCCL_ALGO`, the GID index and every interface name
above are the same on any such box — which is exactly why they are classified and this is
not).

`.env.tp4.example` carries `<PINNING>` in all four values plus a **three-step derivation**
so a reader can still produce their own map from a `NCCL_DEBUG=INFO` first boot;
`./start-tp4.sh ncclcheck` verifies the result. The deployment plan's per-rank table uses
`<PINNING>` likewise. `scripts/check_redaction.py` keeps this class at **blocker**
severity, so it cannot come back unnoticed.

### 4.3 How the gap was found, and the shape of the mistake

The masker's replacement table never had an entry for the interface classes — while the
scan that was supposed to confirm the mask reused that same class list. **Policy and
executor shared one blind spot, so neither end could see the omission.** The general form
is worth stating because it is not about redaction:

> A checker derived from the artefact it checks can only ever confirm the artefact's own
> vocabulary.

`scripts/check_redaction.py` avoids that by enumerating classes independently, and by
recording a verdict per class rather than a per-file result.

Two operational corollaries, both learned the hard way:

- **After every write, extend the pattern set with what you just wrote.** The scan must
  also cover **newly created** files, not just files that changed — a class the masker
  *does* cover can still land undetected in a brand-new script.
- **Never let a scan emit its own hit list into the tree.** The scanner's own output
  contains the values it found; a scan artefact left in the working directory is a leak
  with a plausible-looking filename. `.gitignore` excludes `.workbuddy/` for this reason.

---

## 5. What is deliberately not here

- **Engine logs and raw per-request traces** for runs that were only summarised. The SD-1
  archives retain per-cell raw records, so this does not affect a published number; it
  still applies to anything measured before them.
- **The `.env.tp4` actually in use** — gitignored; `../.env.tp4.example` is the sanitized
  template.
- **The RoCE one-shot RDMA work** (FINAL-METRICS §10) — the verdict was "rejected and
  rolled back"; its scripts were left on the machines on purpose and are not part of this
  distribution.

---

## 6. `common_window.py` and the 129–641 window column

`common_window.py` re-analyses a run to answer "what was delivered while *every* stream in
a wave was decoding simultaneously" — the one aggregate that is not inflated by queueing.
It consumes **raw per-cell request records**, and it expects the earlier naming
(`<size>-c<N>.json`).

The SD-1 PR harness writes `<size>-c<N>-w<W>.json` **including the per-token event log**,
so the window is reconstructible from the archive; adapting the tool to the new filenames
is mechanical and has not been done. Until it is, treat the common-window aggregate as
**derivable but not yet derived** for the current archive.

---

## 7. The nonce discipline: "cold prompt" must be a mechanism, not a claim

Every harness that shapes a published row prefixes each request with a nonce drawn from
`sd_protocol.new_nonce()`:

```
[label:run_tag:proc_salt:00001]
```

Unique across warm-ups, waves, cells, arms and stages. `de_matrix_v3.py` gets it through
`build_prompt()`; `grammar_ab.py` and `gw_ab_v2.py` call it directly. `pr_matrix_v2.py`
draws a fresh `uuid4` per request.

> **A loop-invariant string hoisted out of a wave loop or an arm loop is a cache leak by
> construction.** A nonce keyed on `(concurrency, index)` looks correct, is documented as
> correct, and makes every wave of a cell byte-identical — so it holds against *other*
> runs and *other* cells and fails against the two cases that are actually happening.
> The four places that shape leaks in this suite are the ones worth auditing in any new
> harness: **a warm-up stream**, **wave 1..n−1 repeating wave 0**, **an A/B's two arms
> sharing one prompt per index**, and **a gateway-vs-direct pair sending one prompt to
> both endpoints**. The fourth is the load-bearing one, because it sits on a
> 262,090-token prompt whose prefill is a large fraction of the arm's runtime.

Two consequences that are design decisions rather than fixes:

- **`grammar_ab`'s two arms send *different* prompts** (different nonces, same body). With
  one shared prompt the A/B measures the cache, not the grammar.
- **`gw_ab_v2`'s `wall` arm is the deliberate exception**: it reuses the decode request
  that the *same path* just sent, because "the same request" is what that arm is about.
  Both paths reach that line at the same temperature, so the comparison stays symmetric.

### Regression gate

`preflight_sd1.py` check 5 (`nonce/per-request-not-per-index`) calls `build_prompt()`
twice with identical arguments and fails if the two prompts are equal. It is cheap and it
is the only check on the board that tests the **mechanism** rather than the claim.
Preflight on the current tree: **PASS**, all five checks.

### The related honest caveat

Preflight also sends a 2,895-token prompt twice and looks for a TTFT drop. It returns a
ratio near **1.03** — no measurable cache benefit — and **that is not evidence the cache
is off**. TTFT on this stack carries roughly 0.25 s of fixed scheduling and transport
cost, and 2,895 tokens of prefill hides inside it: the probe is **underpowered**, not the
cache absent.

`cache_effect_probe.py` is the instrument that resolves it. It repeats prompts at
2,048 / 32,768 / 131,072 tokens, where prefill dominates TTFT, and reports
`worth_of_a_repeat = 1 − ttft_repeat / ttft_cold` alongside the `prompt_sha16` of all
three sends, so the byte-identity of the "repeat" pair is **checked rather than assumed**.
Its results are in FINAL-METRICS §8.

---

## 8. The wave spread is an error bar — read it before comparing rows

Every DE-style table prints a **`Wave spread`** column: `(max − min) / median` over a
cell's three per-wave medians. The rule that goes with it:

> **A row-to-row difference smaller than its own wave spread is not resolvable by that table.**

This bites harder than it sounds. The spread is **not evenly distributed**:

| type | wave spread across its 5 cells |
|---|---|
| `structured` | **17.7% – 45.0%** |
| `code` | 2.2% – 6.1% |
| `json` | 0.5% – 4.0% |
| `prose` | 0.8% – 7.4% |

One type carries all the instability. The full ordering `code > json > structured > prose`
holds at every concurrency, but **only 11 of the 15 adjacent gaps clear their own error
bar** — at C1 and C2 the low-concurrency rows separate `code` from `prose` and nothing in
between. **A table that printed the ordering without the spread would invite a claim the
data does not support**, which is why the column is mandatory rather than decorative.

### What is *not* claimed about it

`structured` is both the most content-variable type and the least reproducible one
(per-cell median `chars_per_token` spans 1.694–4.014; within a cell the per-stream span
reaches 1.188–3.661). That makes "content variability drives throughput variability" a
**hypothesis, not a finding** — and the archive does not support it. What the archive
shows instead:

- The per-stream relation **does not exist**: `r(chars_per_token, decode_tps)` *within a
  cell* has **median 0.001** across the 20 cells, and is negative in **10 of 20** — a coin
  flip.
- A pooled `r = −0.295` across the grid is an artefact of pooling across concurrencies and
  must not be quoted.
- A single-cell `r = +0.317` (one cell, n=48) is exactly the shape of mistake to avoid
  quoting for the grid.

**The mechanism behind the spread is unidentified**, and no table here states one.

> The rule this repository applies to file-level findings applies identically to a
> statistic: **a finding about a class is not a finding until the class is enumerated.**
> Compute it for **every** member before quoting it for any of them.

### Corollary: an archive should carry its own uncertainty

Every SD-1 archive carries `waves_detail`, so every published spread is re-derivable from
the file rather than restated from a report. An archive that cannot state its own
precision forces any later comparison to borrow someone else's error bar, which makes the
comparison asymmetric — a property worth designing against up front.

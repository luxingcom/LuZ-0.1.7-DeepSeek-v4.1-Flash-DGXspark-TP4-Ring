# `data/` — raw benchmark archives

Every summary number in the READMEs and in `docs/03-final-metrics/` must be
re-derivable from the files in this directory. If you find a published figure that has
no file behind it, that is a bug — please report it.

All runs below were made against the **current production form**:
600 K context · 9,600,000-token KV pool · `max_running_requests=16` · `TP4 / EP2` ·
DSpark (draft k=5 / verify=6) · fp4 indexer **enabled**. See
[`../BUILD-IDENTITY.md`](../BUILD-IDENTITY.md) for the exact image and software stack.

The measurement convention is **SD-1**, defined and justified in
[`../docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md`](../docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)
§1 and implemented exactly once, in [`../benchmarks/sd_protocol.py`](../benchmarks/sd_protocol.py).
Each JSON file additionally records the convention and the wave count that produced it,
so a file is self-describing even if this page drifts.

---

## `sd1-20260918/` — the SD-1 measurement set

**Every published performance table, measured under one convention.** Produced by
[`../benchmarks/run_sd1_all.sh`](../benchmarks/run_sd1_all.sh) followed by
[`../benchmarks/run_sd1_extra.sh`](../benchmarks/run_sd1_extra.sh); `run.log` in the run
directory on the head node carries each stage's start, exit code and elapsed time.

| subdirectory | what it holds | status |
|---|---|---|
| `de/` | DE matrix, 4 prompt-label types × 5 concurrencies × 3 waves = **20 cells**, plus the 20 per-cell raw record files | ✅ complete |
| `grammar/` | guided-decoding A/B, 5 concurrencies × 2 arms × 3 waves, **with the per-stream records** | ✅ complete |
| `fp4_256/` | fp4-indexer short-output arm, 256-token budget, `code` type, C=1/8/16 | ✅ complete (**one arm**: the indexer is on) |
| `gw/` | `:8001` gateway vs direct `:8899`, three arms (prefill / decode / wall), `ROUNDS=2` | ✅ complete |
| `pr/` | prompt-rate matrix, 6 input sizes × 5 concurrencies = **30 cells**, token-exact input via native `/generate`, plus `engine-steps.log` (the engine's own per-step prefill/decode counters for the same window) and a per-cell `engine_probe` in `summary.json` | ⏳ collecting |
| `cache/` | what a repeated prompt is worth, at 2 k / 32 k / 131 k — prices the nonce defect | ⏳ not yet run |
| `channel/` | chat vs native `/generate`, same unconstrained prompt, alternated within each wave | ⏳ not yet run |
| `TABLES.generated.md` | every table of FINAL-METRICS §2–§8, rendered straight from this directory by `../benchmarks/render_report_tables.py`. Re-run that command to check the report byte for byte | regenerated as stages land |

> The `grammar/` archive above is the **second** pass: the first one wrote no per-stream
> records, so its cells could not be checked below cell level. The run log names that
> stage `grammar2`; it is shipped under the plain name because it supersedes the first
> pass entirely rather than sitting beside it.

### Headline — DE, 2048-token budget, from `de/de_v3_matrix.json`

Median decode is token/s **per request**; the wave-spread column is that cell's own
error bar and is not decoration.

| | C1 | C8 | C16 | agg decode at C16 | wave spread |
|---|---:|---:|---:|---:|---:|
| `code` | **83.59** | 41.34 | 34.97 | **537.5** | ±2.2–±6.1 % |
| `json` | 76.20 | 33.64 | 29.90 | 473.4 | ±0.5–±4.0 % |
| `structured` | 56.41 | 27.42 | 21.31 | 254.9 | **±17.7–±45.0 %** |
| `prose` | 45.84 | 17.89 | 14.80 | 231.7 | ±0.8–±7.4 % |

> **Read the spread column.** The ordering `code > json > structured > prose` holds at
> every concurrency, but of the 15 adjacent gaps only **11** clear their own error bar;
> at C1 and C2 the rows separate `code` from `prose` and nothing in between.
> `structured`'s five cells are individually too noisy to compare, and **the cause of that
> noise is not identified** — it is recorded as unexplained rather than explained away.
> Full discussion in FINAL-METRICS §4.1 and §4.2.
>
> The per-stream records are kept for every cell, so any number above can be recomputed
> from `de/de_<type>_c<N>.json` rather than taken on trust.

**`pr/` headline**: aggregate prefill rate above 8192 input tokens is flat in
concurrency (524288: 1323–1409 tok/s from C1 to C16; the 16th stream's TTFT is
5955 s). Three evidence channels agree — `summary.json` (engine probe), per-stream
`t0` dispatch records, and `pr/engine-evidence.md` (per-step scheduler attribution,
27/30 strict on the admission law; the 3 exceptions are page-size seam steps).
The pre-restart 25 cells are in `pr-prefix/` on the run host and **not shipped**.
`pr/engine-steps.log` holds the raw scheduler lines (5306) behind that evidence table.

### `fp4_256/`, `grammar/`, `gw/`

- **`fp4_256/`** is one arm of an A/B, not the A/B: the indexer is on, and the off arm
  requires a restart. Do not use this table to answer "on or off"; see FINAL-METRICS §7.
- **`grammar/`** compares `sampling_params.json_schema` present vs absent on the native
  `/generate` path, same prompt body and same accounting. Its `grammar2/` successor is
  the auditable one.
- **`gw/`** alternates `:8001` and direct `:8899` within each round, so both paths see the
  same engine state. n = 2 per arm: enough to exclude an order-of-magnitude penalty,
  **not** enough to exclude a single-digit-percent one.

## `gsm8k-20260917/` — the two GSM8K runs

200 questions, 8-shot CoT, temp 0.6, concurrency 1, through the `:8003` gateway.
Two rows: the 600 K production form with the fp4 indexer **off** (0.9600) and
**on** (0.535, with 92 gateway-side errors — see that directory's README for why
both the raw rate and the 107/108 among completed requests must be quoted).

## `release-artifact-20260918/` — offline audit of the shipped image

Not a benchmark archive: this is the recorded output of `scripts/verify_release_artifact.py`
run against the distributed `LuZ-0.1.7-DSV41F-image.tar.zst` (14,463,467,578 B, md5
`10307040cd70ab23436bf34eee829d24`). It establishes, offline, that the archive is a
self-consistent content-addressed store (123/123 blobs with `sha256(bytes) == filename`),
that its reference graph closes (0 unreferenced blobs), and that it reproduces the content
identity **`4ebef21b6aedbd70`** — the value `start.sh`'s preflight asserts fleet-wide.

It is here for the same reason as the benchmark archives: a hash you cannot re-derive is a
claim, not a proof. See that directory's README for the DAG, the blob budget and the table
of all five serializations of the diffID list that have been published as "the identity".

---

## Reproducing a number

```bash
python3 - <<'PY'
import json, statistics
d = json.load(open('data/sd1-20260918/de/de_v3_matrix.json'))
c = d['DE-V3_code_C16']
print(c['median_decode_tps'], c['agg_decode_tps'], c['streams_ok'])
# -> 34.97 537.5 48

c = d['DE-V3_structured_C1']
per_wave = [w['median_decode_tps'] for w in c['waves_detail']]
print(round((max(per_wave) - min(per_wave)) / statistics.median(per_wave) * 100, 1))
# -> 45.0
PY
```

The first line is the cell's central value and the second is its aggregate; they are
different quantities measured over different populations and are **not** expected to
agree. The third line is why `structured` C1 cannot be compared with anything.

## Conventions worth knowing before comparing two numbers

- **Effective prefill** includes queueing and mixed decode work until the last request
  reaches its first token.
- **Per-request decode** is `(ct − 1) / (t_last − t_first)` over that stream's own
  timestamps, so it measures one stream from its own first token onward.
- **Aggregate decode** is measured over absolute timestamps across the whole concurrent
  population, not by summing the per-request rates.
- **A `—` in a total-decode column** means the wave never had all requested streams
  decoding simultaneously. It is *not* zero throughput.
- **`512` is not a prompt length.** In the historical harnesses it is the width of the
  window (tokens 129–641) over which the median is taken; the actual prompt length is
  `prompt_tokens`. Read the field, not the name.
- **A row-to-row difference smaller than the row's own wave spread is not resolvable by
  that table.** This applies to every table in this repository.

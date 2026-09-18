# `gsm8k-20260917/` — the runs behind the published GSM8K figures

Harness: [`../../bench/gsm8k_dsv41.py`](../../bench/gsm8k_dsv41.py) — GSM8K, 200
questions (idx 0-199), 8-shot CoT, `max_tokens=1024`, concurrency 1, issued through
the `:8003` gateway. Two scoring keys are reported for every run: `*_content`
(boxed-answer extraction) and `*_marker` (marker extraction). Both agree in both runs.

These files exist because README §2 and FINAL-METRICS §6 publish GSM8K numbers, and
`../README.md` requires that every published figure have a file behind it. Before
2026-09-18 they did not: §6 cited a `bench-results/gsm8k-600k.summary.json` path that
was not in the repository. That gap is recorded as **V3** in
[`../../benchmarks/README.md`](../../benchmarks/README.md) §4.

## Files

| file | run | result |
|---|---|---|
| `gsm8k-600k.summary.json` | 600 K production form, **fp4 indexer off** | **0.9600** (192/200), `err=0`, median completion 128 tokens, 501.0 s wall |
| `gsm8k-fp4idx.summary.json` | same form, **fp4 indexer on** | **0.535** (107/200), `err=92`, median completion 127 tokens, 281.1 s wall |

## How to read the second row

0.535 is the honest headline and must be quoted as such. The 92 `err` entries are
**gateway-side errors, not wrong answers** — under this run's conditions the
throughput advantage of the fp4 indexer was being measured while a fraction of
requests failed before reaching the model. Among the 108 requests that did complete,
107 were correct (**107/108**), and the contemporaneous baseline was 106/108, i.e.
no regression on the answers that were actually produced.

Reporting only `107/108` would overstate the result; reporting only `0.535` without
the `err=92` context would understate it. **Both are given above, always together.**
The same two-row presentation is in
[`../../docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md`](../../docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md) §9.

## Redaction

The `base` field held an internal management-network address; it is now
`http://<NODE_IP>:8003` (port preserved, per the redaction policy used across this
repository). Nothing else was altered — every count, rate and duration is the value
the run reported.

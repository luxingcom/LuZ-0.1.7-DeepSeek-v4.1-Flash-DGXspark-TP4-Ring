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
| `pr/` | prompt-rate matrix (PR-v2), 6 input sizes × 5 concurrencies = 30 cells + 5-cell supplement — **withdrawn 2026-09-18**: no cache flush between cells, parallel-vs-queued indistinguishable, per-stream columns. Kept for audit, **numbers must not be quoted** (superseded twice over — current archive: `prv3-v18-20260919/`, same-window baseline `prv3-v14-20260919/`) | ⚠️ withdrawn |
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

**`pr/` headline**: this directory is the *withdrawn* PR-v2 archive. The current PR
numbers live in [`prv3-v18-20260919/`](#prv3-v18-20260919--pr-v3-纯-prefill-总吞吐v18024-基线4040-格现行权威基线)（v14 为同窗对照基线）;
the two supersession chains are documented there and in FINAL-METRICS §3.

### `fp4_256/`, `grammar/`, `gw/`

- **`fp4_256/`** is one arm of an A/B, not the A/B: the indexer is on, and the off arm
  requires a restart. Do not use this table to answer "on or off"; see FINAL-METRICS §7.
- **`grammar/`** compares `sampling_params.json_schema` present vs absent on the native
  `/generate` path, same prompt body and same accounting. Its `grammar2/` successor is
  the auditable one.
- **`gw/`** alternates `:8001` and direct `:8899` within each round, so both paths see the
  same engine state. n = 2 per arm: enough to exclude an order-of-magnitude penalty,
  **not** enough to exclude a single-digit-percent one.

### `pr/` 4096-token supplement（2026-09-18 补测）

`4096-c{1,2,4,8,16}-w0.json` 五个原始格文件 + 合并后的 `summary.json`（35 格）与
`TABLE.md`。补测用同一 harness `pr_matrix_v2.py`、同一 SD-1 协议、同一
`manifest_sha256`（`6627b5b2…`），以独立 OUT_DIR 跑完后并回主 summary（`_meta.note_4096`
记录合并事实）。动机：4096 恰在 chunk 边界（`input == CHUNKED_PREFILL_SIZE`），
是同步准入（≤2048）与串行准入（≥8192）之间的过渡档。

> ⚠️ **2026-09-18 起本目录的 PR 数值已作废**，作废理由见
> `../prv3-v14-20260919/` 与 FINAL-METRICS §3。目录保留用于复核，**数值不得引用**。

---

## `prv3-20260918/` — PR-v3 @ chunk 4096（**已被 v14 取代，数值不得引用**）

`RUN_TAG=prv3-20260918T2310`，harness `benchmarks/pr_matrix_v3.py`，7 档输入
（2048 / 4096 / 8192 / 16384 / 32768 / 65536 / 131072）× 5 档并发（1/2/4/8/16）
= 35 格，实测 34 格，`chunked_prefill_size=4096`，峰值 3337.6 t/s（8192 × C1）。

> ⚠️ **2026-09-19 起，本目录被 [`prv3-v14-20260919/`](#prv3-v14-20260919--pr-v3-纯-prefill-总吞吐chunk-81924040-格现行-pr-归档)
> 整体取代**（8192-chunk 全量重测 40/40 格）。保留用于复核取代理由与新旧对照
> （FINAL-METRICS §3.4），**其数值不得再被引用**。以下文件描述保留原样，仅具溯源意义。

| 文件 | 内容 |
|---|---|
| `summary.json` | 34 格逐格结果 + `_meta`（协议、波次、`chunked_prefill_size`、口径原文） |
| `TABLE.md` | harness 自己渲染的总表 |
| `CONCURRENCY.md` | `benchmarks/pr_v3_concurrency.py` 的输出：逐格**实测步宽**、簇数、步间中位间隔、准入律吻合判定 |
| `raw/<input>-c<C>-w0.json` | 34 个逐流原始记录（`t0 / t_first / t_last / t_end / prompt_sha16 / nonce`） |

三条口径硬约束（对应复核提出的三个缺陷）：

1. **排除缓存** —— 每请求唯一 nonce 置提示词最前（radix 永不命中）＋ 每格之间
   `POST /flush_cache`，flush 失败即中止该格。
2. **证明并发** —— 见 `CONCURRENCY.md`；结论是 34 格中只有 4 格（2048 × C2/C4/C8/C16）
   为真并行（步宽 2），其余 23/27 个多流格为串行准入。
3. **总吞吐** —— `Σ(全部成功流 prompt token) ÷ 墙钟`，墙钟 = 放行第一流 → 最后一流结束；
   `max_new_tokens=1`（纯 prefill，无 decode 尾巴）。

**未测**：`131072 × C16`（本轮跑到第 34 格时按维护窗口决策停跑——是未测量，不是失败；
该缺口已在 v14 轮补齐）。
**已知限制**：每格 1 波 ⇒ 无误差棒。

## `prv3-v14-20260919/` — PR-v3 纯 prefill 总吞吐（chunk 8192，40/40 格，**现行 PR 归档**）

`RUN_TAG=prv3-v14-final`（2026-09-19，引擎侧 14:11:51 → 15:36:10 UTC），harness
`benchmarks/pr_matrix_v3.py`，**8 档输入（512…131072）× 5 档并发 = 40 格全测**，
`chunked_prefill_size=8192`，零失败、无缺口。上一轮的 131072×C16 缺口与 512 行空缺
均在本轮补齐。逐格口径与 v3 相同（nonce + flush + `max_new_tokens=1` + Σtoken ÷ 墙钟）。

| 文件 | 内容 |
|---|---|
| `summary.json` | 40 格逐格结果 + `_meta`（`run_tag=prv3-v14-final`、`chunked_prefill_size=8192`、协议原文） |
| `TABLE.md` | harness 渲染的 40 格总表（含 TTFT 首末、墙钟） |
| `CONCURRENCY.md` | `pr_v3_concurrency.py <raw> 0.010 8192` 的输出：准入律 `min(C, max(1, ⌊8192/input⌋))` **35/40 精确吻合、无一格超出**；真并行步 11 格（512 档步宽最高 13、2048 档最高 4、4096 档宽 2）；>4096 token 的多流格 21/21 串行 |
| `raw/<input>-c<C>-w0.json` | 40 个逐流原始记录 |

**引用头条数字**：峰值 **3,326.4 t/s**（8192 × C4）；次高 3,288.5（4096 × C2）；
512 行 C1→C16 **+103.9%**；长输入窄带 1,366.9–1,963.0 t/s。
**已知限制**：每格 1 波 ⇒ 无误差棒；chunk 4096→8192 只有单轮实测，无 A/B。

> ⚠️ **2026-09-20 起，本目录作为基线被 [`prv3-v18-20260919/`](#prv3-v18-20260919--pr-v3-纯-prefill-总吞吐v18024-基线4040-格现行权威基线)
> 接替**（MoE W4A16→W4A8-MX 生产切换后的 e2e 重测，同为 8192-chunk 同口径）。
> v14 仍是 v18 的**同窗对照基线**（引擎同日、同工具带外的唯一参考），数值仍可引用，
> 但做纵向对比时须写明对照对象是 v14。

复现：`python3 ../benchmarks/render_pr_v3_tables.py prv3-v14-20260919`；
并发判定：`python3 ../benchmarks/pr_v3_concurrency.py prv3-v14-20260919/raw 0.010 8192`。

## `prv3-v18-20260919/` — PR-v3 纯 prefill 总吞吐（v18/0.2.4 基线，40/40 格，**现行权威基线**）

`RUN_TAG=prv3-v18-20260919T234318`（2026-09-19 深夜），采集器
`bench/prv3_collector.py`（**重建版**——原 v3 采集器会话内联失传，按 v14 数据模式
同口径重建；**跨工具绝对值对照须谨慎，本表核心是同工具 v14→v18 序列内对照**）。
**8 档输入（512…131072）× 5 档并发 = 40 格全过**（COMPLETE），`max_tokens=1`、
逐请求 nonce、格间 flush，与 v14 三条硬约束一致。

引擎形态（head 容器 launch args 实证）：`--chunked-prefill-size 8192
--enable-mixed-chunk --prefill-decode-interval 4`，MoE **W4A8-MX 全区间**
（2026-09-19 生产切换，见 docs/operators/ 大 M 事故分析与 v0.2.4 release notes）。

| 文件 | 内容 |
|---|---|
| `summary.json` | 40 格逐格结果（由 raw 重建，schema 对齐 v14） |
| `TABLE.md` | 采集器渲染的 40 格总表（与服务器侧逐字节一致） |
| `CONCURRENCY.md` | `pr_v3_concurrency.py <raw> 0.010 8192` 输出：准入律 **27/40** 精确吻合、**无一格超出**；13 个偏差格全落在到达主导的小提示词档（10 格低于律、3 格步宽 2 系 mixed-chunk decode 搭载步）；真并行步 11 格 |
| `raw/<input>-c<C>-w0.json` | 40 个逐流原始记录 |

**v18 对 v14 同格增益**（复算，%）：4096 行 **+30~+38**；8192 行 −9~+25；
16384 行 +46~+70（C1 −23 单波离群）；32768 行 +34~+68；65536 行 **+67~+132**
（C8 峰 3,474.6）；131072 行 +35~+68（C1 +3.7）。512 行 **−3~−34**（待复核）。

**待复核（下一靴，≥2 靴纪律）**：512×C8/C16（−19%/−34%，单波方差嫌疑）；
16384×C1（−23%，同档 C2–C16 全 +46~70）；2048×C8（−7.7%，噪声带内）。

**基线登记**：v18 本次矩阵为**现行权威基线**，此后优化臂对同矩阵复测（≥2 靴、<5% 判噪声）。
代表值：512×C1 1214.2 / 4096×C16 4043.4 / 8192×C8 3704.1 / 65536×C8 3474.6 /
131072×C16 2508.1 t/s。全表峰值 **4,299.6 t/s**（4096 × C2）。

并发判定：`python3 ../benchmarks/pr_v3_concurrency.py prv3-v18-20260919/raw 0.010 8192`。

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

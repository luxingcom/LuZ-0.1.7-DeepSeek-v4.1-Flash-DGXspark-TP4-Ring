# FINAL-METRICS-600K · DeepSeek-V4.1-Flash · 4× DGX Spark TP4 Ring

> **被测形态**：现役生产形态 A —— 600000 ctx · 9,600,000 KV 池 · 16 并发 · `EP4`→`EP2` ·
> fp4 indexer 开启 · SGLang `da64c5cb` · DSpark k=6。
> **口径**：**SD-1**，唯一一套（§1）。本报告不含任何其他口径的数值。
> **构建身份**：[`../../BUILD-IDENTITY.md`](../../BUILD-IDENTITY.md)｜**原始归档**：
> [`../../data/sd1-20260918/`](../../data/sd1-20260918/)｜**harness**：
> [`../../benchmarks/README.md`](../../benchmarks/README.md)
>
> **修订记录**：
> - 2026-09-18（一）补测 **4096-token PR 行**（同 harness/协议/manifest，独立 supplement
>   目录跑后并回）⇒ 当时的 §3 由 30 格扩为 35 格；所有表格由 `render_report_tables.py`
>   从合并后归档机械产出。
> - 2026-09-18（三）**§3 整体作废并重写**：旧 PR 表（PR-v2，35 格）被判定**不可作为基准参数**
>   （缓存未排除 / 未证明真并发 / 口径不是总吞吐），改以 **PR-v3 纯 prefill 总吞吐**重测，
>   范围收敛为 2048–131072（**7 档 × 5 并发 = 35 格，实测 34 格**）。旧数据保留在
>   `data/sd1-20260918/pr/` 供复核作废理由，**但不得再引用其数值**。§2 的 PR 行同步替换。
>   ⚠ 历史段保留：上一条记录中的 35 格 PR-v2 表**已作废**，其数值仅具溯源意义。

---

## §1 测量口径（SD-1）

本节是本报告的**唯一口径定义**。任何引用本报告数值的下游文档，须连同本节一起引用。

### §1.1 协议

**SD-1** 是本仓库用于**全部**性能表的单一口径。

| 维度 | SD-1 规定 |
|---|---|
| 通道 | chat `/v1/chat/completions`；**唯一例外**是 PR 矩阵（输入尺寸是自变量，须 token 精确 ⇒ 用 native `/generate` + `input_ids`） |
| 输出类型 | `structured` / `prose` / `code` / `json` 是**提示词标签**，**不是** grammar 约束。SD-1 下**不存在** guided decoding |
| 强制吃满 | `min_tokens = max_tokens` + `ignore_eos = true` + `stop = []` |
| 采样 | `temperature = 0`、`top_p = 1`、thinking 关闭 |
| 冷前缀 | **每请求**唯一 nonce（进程内计数器 + 进程盐），置于提示词**最前** |
| 每流速率 | `decode = (ct − 1) / (t_last − t_first)`，`prefill = prompt_tokens / (t_first − t0)` |
| 格中心值 | 该格**全部有效流**的 `statistics.median`（真中位数） |
| 波次 | DE / grammar / fp4 每格 3 波；PR 每格 1 波（`_meta.waves` 逐格落盘） |
| 聚合 | 基于**绝对时间戳**emit 三种：并集窗 / 交集窗（共享窗）/ 墙钟 |
| 留存 | 逐流 `t0 / t_first / t_last / t_end` **与** `prompt_sha16`，使「每请求都是冷的」可被验证而非声明 |
| **PR 子口径（PR-v3）** | PR 矩阵在 SD-1 之上另有三条（2026-09-18 起，§3.1）：`max_new_tokens = 1`（**纯 prefill，无 decode 尾巴**）· **每格之间 `POST /flush_cache`** · 总吞吐 = **Σ(prompt token) ÷ 墙钟（放行→最后一流结束）**。DE 与其他各臂**不受影响**，仍按上表 |

> ⚠️ **SD-1 不是「一个数只能有一个值」，而是「一个值必须能说出它怎么来的」。** PR-v3 与 PR-v2
> 测的是**不同的量**（纯 prefill 总吞吐 vs per-stream 速率＋窗口聚合），因此两者不互通、不对比。

### §1.2 为什么写这么细（三条设计理由）

1. **同一个非零分子换一个来源就是另一个数。** prefill 速率的分母是 `t_first − t0`，分子若用
   硬编码的提示词长度常量，就等于把「引擎实报的输入规模」换成「我以为的输入规模」——两者只在
   提示词恰好只有提示词时才相等。
2. **同一批测量换一条聚合规则就是另一个数。** 上中位数 `sorted(x)[n//2]` 与真中位数在**偶数**
   并发上差一个次序统计量；而「1 波」与「3 波中位」是**不同的测量**，不只是不同的统计量。
   因此本仓库把规则收敛成一条、写进每一格 JSON，而不是写进文档。
3. **「冷」必须是机制，不是断言。** 预热请求、同格第 2/3 波、A/B 的两臂、以及网关/直连的一对
   请求，都是同一条循环不变量可能泄漏的位置。`prompt_sha16` 逐流留存就是为了让这条可检查。

### §1.3 误差棒与「可分辨性」规则

每格印 **Wave spread = (max − min) / median**（3 个波中位数的相对极差）。它是**误差棒**：

> **两行之差若小于其自身波次离散度，本表无法分辨这对差异。**

这条规则真的会咬人：四类型排序在 5 个并发档从未反转，但 15 个相邻间隔中只有 **11 个**超出各自
误差棒（§4.1）。离散度**不是全表弥漫**，而是集中在**一个类型**上：`structured` **17.7%–45.0%**，
其余三类 **0.5%–7.4%**。**成因未识别**，见 §4.2。

### §1.4 被测环境（launch args 实测）

- 引擎：SGLang（fork）· 4× DGX Spark GB10 / sm_121a · switchless RoCE ring · **TP4 / EP2**
- 投机解码：`--speculative-algorithm DSPARK`，`speculative_num_draft_tokens=6`（draft k=5 / verify=6）
- 上下文与容量：`--context-length 600000` · `--max-total-tokens 9600000` ·
  `--max-running-requests 16` · `--cuda-graph-max-bs-decode 16` · `--mem-fraction-static 0.90`
- 后端：`--attention-backend dsv4` · `--moe-runner-backend flashinfer_mxfp4` ·
  `--fp8-gemm-backend flashinfer_cutlass` · `--chunked-prefill-size 4096`
- KV：`kv_cache_dtype=fp8_e4m3`（引擎日志实报）；`SGLANG_DSV4_KV_LAYOUT=fork-v4-fp4`
- 解析：`--reasoning-parser deepseek-v41` · `--tool-call-parser deepseekv41` ·
  `--enable-decoder-swa-bounded-replay` · `grammar_backend=xgrammar`
- **fp4-indexer 已开**（`--enable-deepseek-v4-fp4-indexer`）
- 服务面：引擎 loopback `127.0.0.1:8899`；对外经并发代理 `:8001`
- 镜像：`dsv41-sglang-optimized:v7` · SGLang `0.0.0.dev1+gda64c5cbb` · driver 580.173.02 / CUDA 13.0
  （完整身份见 [`../../BUILD-IDENTITY.md`](../../BUILD-IDENTITY.md)）

### §1.5 内存相位（GB10 UMA 下判读内存的关键）

GB10 是 UMA：设备页与宿主页**同池**（121.6 GiB）。因此：

- `oom_gate pre -t 110` 的 **110 GiB 是发射前准入判据**，**不是稳态健康线**。
- **装载引擎后的稳态** `eff_free`（= `MemFree + Cached + SReclaimable − Shmem`）为
  **6.8–9.9 GiB 且平坦**（完整 208 点采样全程落在此带内，含正常完成的 C16 格）。
- 把稳态读数对照发射期阈值**双向有害**：误杀健康运行，或因「一直是 9」而放过真 OOM。
  **相位是阈值的一部分。**
- 设备侧精确通道只有 `nvidia-smi --query-compute-apps`；cgroup 计数看不见账外的设备页，
  所以 **`OOMKilled=false` 是预期**，不能据此否定 OOM。

### §1.6 原始归档与机械复现

| 数据集 | 归档路径 | 状态 |
|---|---|---|
| DE 20 格（4 类型 × 5 并发 × 3 波） | [`../../data/sd1-20260918/de/`](../../data/sd1-20260918/de/) | ✅ |
| grammar A/B（5 并发 × 2 臂 × 3 波） | [`../../data/sd1-20260918/grammar/`](../../data/sd1-20260918/grammar/) | ✅（第二遍逐流记录；日志名 `grammar2`，交付用本名） |
| fp4 短输出臂（256 token，3 并发） | [`../../data/sd1-20260918/fp4_256/`](../../data/sd1-20260918/fp4_256/) | ✅ |
| PR 30 格（PR-v2，含 `engine-steps.log` 与 `engine-evidence.md`） | [`../../data/sd1-20260918/pr/`](../../data/sd1-20260918/pr/) | ⚠️ **已作废**（2026-09-18）——保留供复核作废理由，**数值不得引用** |
| **PR-v3 34 格**（纯 prefill 总吞吐，逐流原始记录） | [`../../data/prv3-20260918/`](../../data/prv3-20260918/) | ✅（131072 × C16 未测） |
| 网关三臂 | [`../../data/sd1-20260918/gw/`](../../data/sd1-20260918/gw/) | ✅ |
| 缓存探针 | —（`data/sd1-20260918/cache/`） | ⛔ 业主取消，无归档 |
| 通道对照 | —（`data/sd1-20260918/channel/`） | ⛔ 业主取消，无归档 |

> **全表可由命令机械重出**（两条，各自对应一个归档）：
> `python3 benchmarks/render_report_tables.py data/sd1-20260918`（§4–§8）
> `python3 benchmarks/render_pr_v3_tables.py data/prv3-20260918`（§3）
> 本报告带 `<!-- generated from … -->` 标记的表格即这两个命令的输出，逐行一致
> （`scripts/check_report_tables.py <archive> <report>` 复核；该脚本按归档自报的
> `protocol_id` 选择渲染器，不会因目录改名而静默选错）。
> 缺阶段时该命令**报缺并以非零码退出**，不会静默出空表。

---

## §2 TL;DR

| 指标 | 结果 | 溯源 |
|---|---|---|
| DE 总吞吐（agg decode 峰值） | **537.5 t/s**（`code` C16） | §4 |
| DE 单流峰值（2048 预算） | **83.59 t/s/req**（`code` C1） | §4 |
| DE 单流最低（C16） | **14.80 t/s/req**（`prose` C16） | §4 |
| DE 聚合峰值（C16） | **537.5 t/s**（`code` C16） | §4 |
| DE 四类型排序 | `code > json > structured > prose`，**5 个并发档全部一致** | §4 |
| DE 最大误差棒 | **±45.0%**（`structured` C1）；其余三类 ≤±7.4% | §4 |
| 排序可分辨性 | 15 个相邻间隔中 **11 个**超误差棒；C1/C2 只能分辨首尾 | §4.1 |
| 引导解码（grammar） | 约束臂在**每一个**并发档都比自由臂**快**（decode +4.5%…+34.3%） | §5.1 |
| 通道对照（chat vs native） | ⛔ 业主取消（2026-09-18），问题保持开放 | §5.2 |
| 网关 vs 直连 | 三臂均**不可分辨**：prefill **+0.9%**、decode **−0.2%**、wall **+0.3%**（n=2/臂） | §6 |
| fp4 短输出臂（256 预算，indexer 开） | `code` C1 **88.58**、C16 **36.99**、agg C16 **542.7 t/s** | §7 |
| 缓存价值 | ⛔ 业主取消（2026-09-18）；PR 对 engram 路径失明的缺口仍在 | §8 |
| **PR 总吞吐峰值（PR-v3，纯 prefill）** | **3,337.6 t/s**（8192 × C1）；多流档峰值 **3,310.3 t/s**（4096 × C8） | §3 |
| PR 并发收益 | 2048 档 **+29.3%**（C1→C4，且该档**真并发**、步宽 2）；≥8192 档**为负**：8192 档 C1→C16 **−26.4%** | §3.3 / §3.4 |
| PR 并发真伪 | 34 格中仅 **4 格**（2048 × C2/C4/C8/C16）实测一步 2 个请求；其余 **23/27** 多流格为串行准入。准入律 `min(C, ⌊4096/input⌋)` **34/34 吻合** | §3.3 |
| PR 长输入收敛 | 32768 / 65536 / 131072 落在 **1,739.3–2,215.5 t/s** 窄带；全表最低 131072 × C8 **1,739.3 t/s** | §3.4 |
| PR 未闭环 | **131072 × C16 未测**（34/35）；每格仅 1 波 ⇒ **无误差棒**；8192→16384 的 −42% 悬崖**成因未识别** | §3.5 |
| GSM8K 质量门 | **0.9600**（192/200，temp 0.6 / 8-shot，**非 greedy**） | §9 |

---

## §3 PR 矩阵（PR-v3 纯 prefill 总吞吐 · 34/35 格）

> ⚠️ **本节 2026-09-18 整体重写。旧表（PR-v2，35 格，含 512 与 524288 两行）已作废，不得作为基准参数引用。**
> 作废理由三条，逐条对应复核中提出的测量缺陷：
>
> | # | 缺陷 | 旧表的问题 |
> |---|---|---|
> | 1 | KV / radix 缓存污染 | 旧 harness 每格之间不刷缓存，同一尺寸多波共享前缀 ⇒ 同一提示词二次发送的 TTFT 可降到首次的 **0.218×** |
> | 2 | 无法区分「并行」与「排队」 | 旧表只有聚合速率与 TTFT，读不出一个 prefill 步里到底同时推进了几个请求 |
> | 3 | 口径不是总吞吐 | 旧表列的是 per-stream 速率 + 窗口聚合，不是「从放行到最后一流结束」的全部 token ÷ 全部时间 |
>
> 旧数据**未删除**，仍在 [`../../data/sd1-20260918/pr/`](../../data/sd1-20260918/pr/) 可复核作废理由；
> 但**任何下游文档不得再引用其数值**。

### §3.1 PR-v3 口径

| 维度 | PR-v3 规定 |
|---|---|
| 输出预算 | `max_new_tokens = 1` ⇒ **纯 prefill，无 decode 尾巴** |
| 缓存 | 每请求唯一 nonce（置提示词最前，radix 永不命中）＋ **每格之间 `POST /flush_cache`**；flush 失败即中止该格，不静默继续 |
| 总吞吐 | **Σ(全部成功流的 prompt token) ÷ 墙钟**；墙钟 = 放行第一流 → 最后一流结束。一次时钟、无窗口、无 decode 项 |
| 并发真伪 | 由**逐流首包时刻聚类**判定（§3.3），不靠采样计数器 |
| 输入尺寸 | 2048 / 4096 / 8192 / 16384 / 32768 / 65536 / 131072（token 精确，native `/generate` + `input_ids`，仍是 SD-1 唯一例外） |
| 并发 | 1 / 2 / 4 / 8 / 16 |
| 波次 | **每格 1 波** ⇒ **本表没有波次误差棒**，见 §3.5 |

运行 `RUN_TAG=prv3-20260918T2310`（引擎侧 15:16:47 → 16:07:40），`chunked_prefill_size=4096`；
34 格全部 `streams_ok = C`、零失败。**131072 × C16 未测**——本轮跑到第 34 格时按维护窗口决策停跑，
是未测量，**不是失败、也不是超时**。

### §3.2 总吞吐矩阵（34 格）

<!-- generated from summary.json + raw/*-c*-w0.json -->

| Input tokens | C | Streams OK | Total prompt tokens | Wall s | **Total t/s** | TTFT first s | TTFT last s | Observed batch width | Prefill batches | Verdict |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2048 | 1 | 1/1 | 2048 | 0.839 | **2441.6** | 0.838 | 0.838 | 1 | 1 | single stream |
| 2048 | 2 | 2/2 | 4096 | 1.337 | **3062.6** | 1.336 | 1.337 | 2 | 1 | parallel (2/step) |
| 2048 | 4 | 4/4 | 8192 | 2.595 | **3157.1** | 2.498 | 2.593 | 2 | 2 | parallel (2/step) |
| 2048 | 8 | 8/8 | 16384 | 5.211 | **3144.4** | 1.965 | 5.209 | 2 | 5 | parallel (2/step) |
| 2048 | 16 | 16/16 | 32768 | 11.384 | **2878.4** | 2.577 | 11.382 | 2 | 9 | parallel (2/step) |
| 4096 | 1 | 1/1 | 4096 | 1.457 | **2810.5** | 1.456 | 1.456 | 1 | 1 | single stream |
| 4096 | 2 | 2/2 | 8192 | 2.537 | **3229.2** | 2.470 | 2.535 | 1 | 2 | serialized (1/step) |
| 4096 | 4 | 4/4 | 16384 | 4.971 | **3296.1** | 2.468 | 4.969 | 1 | 4 | serialized (1/step) |
| 4096 | 8 | 8/8 | 32768 | 9.899 | **3310.3** | 2.483 | 9.897 | 1 | 8 | serialized (1/step) |
| 4096 | 16 | 16/16 | 65536 | 22.493 | **2913.6** | 3.263 | 22.490 | 1 | 16 | serialized (1/step) |
| 8192 | 1 | 1/1 | 8192 | 2.454 | **3337.6** | 2.453 | 2.453 | 1 | 1 | single stream |
| 8192 | 2 | 2/2 | 16384 | 6.306 | **2598.3** | 4.280 | 6.304 | 1 | 2 | serialized (1/step) |
| 8192 | 4 | 4/4 | 32768 | 13.496 | **2428.1** | 4.260 | 13.493 | 1 | 4 | serialized (1/step) |
| 8192 | 8 | 8/8 | 65536 | 24.266 | **2700.8** | 4.344 | 24.263 | 1 | 8 | serialized (1/step) |
| 8192 | 16 | 16/16 | 131072 | 53.325 | **2458.0** | 4.360 | 53.322 | 1 | 16 | serialized (1/step) |
| 16384 | 1 | 1/1 | 16384 | 8.460 | **1936.6** | 8.458 | 8.458 | 1 | 1 | single stream |
| 16384 | 2 | 2/2 | 32768 | 16.876 | **1941.6** | 10.384 | 16.873 | 1 | 2 | serialized (1/step) |
| 16384 | 4 | 4/4 | 65536 | 32.526 | **2014.9** | 10.313 | 32.523 | 1 | 4 | serialized (1/step) |
| 16384 | 8 | 8/8 | 131072 | 62.550 | **2095.5** | 8.945 | 62.547 | 1 | 8 | serialized (1/step) |
| 16384 | 16 | 16/16 | 262144 | 122.489 | **2140.2** | 9.888 | 122.485 | 1 | 16 | serialized (1/step) |
| 32768 | 1 | 1/1 | 32768 | 14.799 | **2214.1** | 14.794 | 14.794 | 1 | 1 | single stream |
| 32768 | 2 | 2/2 | 65536 | 30.705 | **2134.4** | 16.371 | 30.703 | 1 | 2 | serialized (1/step) |
| 32768 | 4 | 4/4 | 131072 | 64.099 | **2044.9** | 17.287 | 64.095 | 1 | 4 | serialized (1/step) |
| 32768 | 8 | 8/8 | 262144 | 120.882 | **2168.6** | 14.908 | 120.875 | 1 | 8 | serialized (1/step) |
| 32768 | 16 | 16/16 | 524288 | 249.905 | **2097.9** | 17.195 | 249.901 | 1 | 16 | serialized (1/step) |
| 65536 | 1 | 1/1 | 65536 | 34.047 | **1924.9** | 34.042 | 34.042 | 1 | 1 | single stream |
| 65536 | 2 | 2/2 | 131072 | 67.403 | **1944.6** | 36.080 | 67.393 | 1 | 2 | serialized (1/step) |
| 65536 | 4 | 4/4 | 262144 | 118.324 | **2215.5** | 31.721 | 118.314 | 1 | 4 | serialized (1/step) |
| 65536 | 8 | 8/8 | 524288 | 257.518 | **2035.9** | 31.637 | 257.503 | 1 | 8 | serialized (1/step) |
| 65536 | 16 | 16/16 | 1048576 | 527.764 | **1986.8** | 31.209 | 527.758 | 1 | 16 | serialized (1/step) |
| 131072 | 1 | 1/1 | 131072 | 73.807 | **1775.9** | 73.789 | 73.789 | 1 | 1 | single stream |
| 131072 | 2 | 2/2 | 262144 | 150.702 | **1739.5** | 77.133 | 150.693 | 1 | 2 | serialized (1/step) |
| 131072 | 4 | 4/4 | 524288 | 297.068 | **1764.9** | 72.971 | 297.026 | 1 | 4 | serialized (1/step) |
| 131072 | 8 | 8/8 | 1048576 | 602.857 | **1739.3** | 75.301 | 602.847 | 1 | 8 | serialized (1/step) |
| 131072 | 16 | — | — | — | **—** | — | — | — | — | ⛔ 未测（本轮停跑，非失败） |

压缩视图（同一数据的 7×5 形式）：

<!-- generated from summary.json (7x5) -->

| Input tokens | C1 | C2 | C4 | C8 | C16 | row median | best |
|---:|---:|---:|---:|---:|---:|---:|---|
| 2048 | 2441.6 | 3062.6 | 3157.1 | 3144.4 | 2878.4 | 3062.6 | **3157.1** @C4 |
| 4096 | 2810.5 | 3229.2 | 3296.1 | 3310.3 | 2913.6 | 3229.2 | **3310.3** @C8 |
| 8192 | 3337.6 | 2598.3 | 2428.1 | 2700.8 | 2458.0 | 2598.3 | **3337.6** @C1 |
| 16384 | 1936.6 | 1941.6 | 2014.9 | 2095.5 | 2140.2 | 2014.9 | **2140.2** @C16 |
| 32768 | 2214.1 | 2134.4 | 2044.9 | 2168.6 | 2097.9 | 2134.4 | **2214.1** @C1 |
| 65536 | 1924.9 | 1944.6 | 2215.5 | 2035.9 | 1986.8 | 1986.8 | **2215.5** @C4 |
| 131072 | 1775.9 | 1739.5 | 1764.9 | 1739.3 | — | 1752.2 | **1775.9** @C1 |

### §3.3 并发真伪：逐流首包时刻聚类

复核第 2 条要求「确保是真的在并发运行，而不是在排队」。PR-v3 自带的两个指标**回答不了**这个问题：

- `max_new_tokens=1` 时唯一产出的 token 就是首个 token，`t_end − t_first ≈ 0.1 ms` ⇒
  `[t_first, t_end]` 区间扫描**恒为 1**，`ttft_overlap_peak` 退化，任何格子都拿不到 ≥ 2；
- 引擎 `sglang:num_running_reqs` 是 1 s 采样的瞬时值，短格（2048 × C1 仅 0.84 s）可能一次都没采到。

因此并发判定改为对**逐流首包时刻**做间距聚类：同一个 prefill 步完成的流会挤在一起，
串行完成的流之间隔着一个请求的服务时间。容差取 **10 ms**，依据是实测的两个数量级分离：

- 步内抖动 ≤ **0.5 ms**（2048 档成对流的实测极差）；
- 步间最小间隔 **64 ms**。

容差在 **0.005–0.05 s 区间内结论稳定（准入律 34/34 吻合）**；只有 ≥ 0.2 s 才会把相邻步并成一簇
并翻转 7 格——故此处不使用该量级。复算脚本
[`../../benchmarks/pr_v3_concurrency.py`](../../benchmarks/pr_v3_concurrency.py)，
输入是归档的逐流文件：**不改动已归档的 harness，也不重测任何格子**。

| 输入 | 实测步宽 | 判定 |
|---|---|---|
| 2048 | **2**（C2 / C4 / C8 / C16 共 4 格） | **真并发**：一步 2 个请求，与 `floor(4096/2048) = 2` 一致 |
| 4096 | 1 | 串行：首包间隔 ≈ 1.21 s，即单个 4096-token prefill 的耗时 |
| ≥ 8192 | 1（**20/20** 个多流格） | 串行：首包间隔 ≈ 单请求服务时间，无两个流重合 |

准入律 `min(C, floor(chunked_prefill_size / input))` 在 **34/34** 格上吻合；逐格证据见
[`../../data/prv3-20260918/CONCURRENCY.md`](../../data/prv3-20260918/CONCURRENCY.md)。

> **因此：除 2048 档的 4 格外，本表的总吞吐是「串行准入下的墙钟吞吐」，不是并行 prefill 吞吐。**
> 这是引擎在 `--chunked-prefill-size 4096` 下的**准入策略**结果——不是客户端缺陷，也不是排队超时。

### §3.4 读数

- **总吞吐峰值 3,337.6 t/s**（8192 × C1，单流纯 prefill）；多流档峰值 **3,310.3 t/s**（4096 × C8）。
- **2048 档并发确有收益**：C1 2441.6 → C4 **3157.1**（**+29.3%**），且该档是真并发（步宽 2）。
- **4096 档收益有限且串行**：C1 2810.5 → C8 3310.3（+17.8%），C16 回落至 2913.6。
- **≥ 8192 档并发无收益甚至为负**：8192 档 C1 3337.6 → C16 2458.0（**−26.4%**）。串行准入下
  每个请求都要重复付一次调度 + 单 token decode + 回包开销。
- **8192 → 16384 之间存在悬崖**：C1 由 3337.6 掉到 1936.6（**−42.0%**），且在 5 个并发档中的
  **4 个**上 16384 行都低于 32768 行（C16 反转）。**成因未识别**——每格 1 波、无误差棒，
  本表不做机理论断。
- **长输入收敛**：32768 / 65536 / 131072 三档落在 1,739.3–2,215.5 t/s 的窄带内，
  全表最低为 131072 × C8 的 **1,739.3 t/s**。

### §3.5 未闭环 / 已知缺陷

1. **131072 × C16 未测**（34/35）。
2. **每格 1 波 ⇒ 无误差棒**。按 §1.3 规则，小于自身离散度的差异**不可分辨**；§3.4 的悬崖与
   长输入收敛只能在「逐档一致」的意义上使用，不能当作单点精值。
3. **`ttft_overlap_peak` 在 `max_new_tokens=1` 下退化**：并发判定一律以 §3.3 的聚类结果为准。
4. **512 与 524288 两档本轮未覆盖**（指定测量范围为 2048–131072）。524288 × C16 在旧表里
   TTFT 达 5955 s，本轮不重测——它是旧口径下的数，同样不得引用。

---


---

## §4 DE 矩阵（20 格）

2048-token 输出预算，4 类型 × 5 并发 × 每格 3 波，每请求唯一 nonce，无 guided decoding。
**`structured` 是提示词标签，不是 grammar 约束。**

<!-- generated from de/de_v3_matrix.json -->

Max output 2048 tokens, 3 waves per cell, one nonce per request -- no cell can be warmed by an earlier wave, an earlier stage, or the warm-up. `median decode` = `statistics.median` over every ok stream of every wave; the stream count is the `OK streams` column. `agg decode` = median over waves of that wave's own `Σ(ct−1) / (last first-token − first first-token)`. `agg prefill` = the same shape on `Σ prompt_tokens`. The two aggregates are cluster-wide, so a cell's `median` and its `agg` are different quantities and are not expected to agree.

`Wave spread` is `(max − min) / median` over the three per-wave medians, and it is a real error bar rather than decoration: the prompt fixes **how much** is generated, not **what**, and the resulting instability is concentrated in one type -- 17.7%–45.0% for `structured`, 0.5%–7.4% for the other three. **A row-to-row difference smaller than its own wave spread is not resolvable by this table.** On this run that bites: the full ordering `code > json > structured > prose` holds at every concurrency, but of the 15 adjacent gaps only 11 clear their own error bar -- at C1 and C2 the low-concurrency rows separate `code` from `prose` and nothing in between. The cause of the spread is not identified; see the note on `wave_spread`.

| Type | C | Median decode tok/s/req | Wave spread | Agg decode tok/s | Median prefill tok/s | Agg prefill tok/s | Median TTFT s | chars/token | OK streams | Waves OK |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| structured | 1 | 56.41 | ±45.0% | 56.4 | 271.3 | 271.3 | 0.262 | 1.74 | 3 | 3/3 |
| structured | 2 | 44.41 | ±38.0% | 80.3 | 251.7 | 502.7 | 0.282 | 1.69 | 6 | 3/3 |
| structured | 4 | 42.25 | ±17.7% | 120.9 | 171.9 | 685.4 | 0.413 | 1.74 | 12 | 3/3 |
| structured | 8 | 27.42 | ±33.5% | 167.3 | 153.4 | 1216.8 | 0.463 | 1.85 | 24 | 3/3 |
| structured | 16 | 21.31 | ±31.6% | 254.9 | 105.6 | 1143.3 | 0.672 | 1.80 | 48 | 3/3 |
| prose | 1 | 45.84 | ±7.4% | 45.8 | 269.2 | 269.3 | 0.290 | 3.81 | 3 | 3/3 |
| prose | 2 | 35.74 | ±5.4% | 70.9 | 259.8 | 518.8 | 0.300 | 4.01 | 6 | 3/3 |
| prose | 4 | 27.20 | ±1.2% | 107.5 | 215.9 | 861.8 | 0.361 | 3.92 | 12 | 3/3 |
| prose | 8 | 17.89 | ±0.8% | 139.7 | 162.5 | 1294.4 | 0.480 | 3.93 | 24 | 3/3 |
| prose | 16 | 14.80 | ±1.3% | 231.7 | 111.7 | 1221.9 | 0.698 | 3.96 | 48 | 3/3 |
| code | 1 | 83.59 | ±6.1% | 83.6 | 428.7 | 428.7 | 0.343 | 2.92 | 3 | 3/3 |
| code | 2 | 65.39 | ±2.3% | 130.1 | 361.1 | 721.7 | 0.407 | 2.86 | 6 | 3/3 |
| code | 4 | 56.41 | ±3.9% | 212.6 | 301.0 | 1201.2 | 0.488 | 2.86 | 12 | 3/3 |
| code | 8 | 41.34 | ±2.2% | 313.6 | 211.6 | 1688.3 | 0.695 | 2.86 | 24 | 3/3 |
| code | 16 | 34.97 | ±5.5% | 537.5 | 128.2 | 1522.5 | 1.147 | 2.86 | 48 | 3/3 |
| json | 1 | 76.20 | ±4.0% | 76.2 | 312.0 | 312.0 | 0.314 | 2.48 | 3 | 3/3 |
| json | 2 | 64.85 | ±3.2% | 129.0 | 295.0 | 589.4 | 0.332 | 2.48 | 6 | 3/3 |
| json | 4 | 50.18 | ±0.5% | 197.7 | 235.2 | 938.0 | 0.417 | 2.47 | 12 | 3/3 |
| json | 8 | 33.64 | ±3.7% | 267.8 | 166.9 | 1330.9 | 0.587 | 2.48 | 24 | 3/3 |
| json | 16 | 29.90 | ±2.5% | 473.4 | 94.9 | 1100.9 | 1.032 | 2.48 | 48 | 3/3 |

### §4.1 结论

1. **排序稳定且方向明确**：`code > json > structured > prose`，在 C1/C2/C4/C8/C16 **五个档全部
   成立**，从未反转。token 致密、可预测性高的形态（代码 / JSON）天然快于散文。
2. **误差棒分布极不均匀**（比排序本身更值得注意）：`structured` 的波次离散度
   **17.7%–45.0%**，其余三类 **0.5%–7.4%**。不稳定性集中在**一个类型**上。
3. **可分辨性**（按 §1.3 规则逐对判定）：

| C | 可分辨的相邻间隔 | 不可分辨的相邻间隔 |
|---|---|---|
| 1 | `code` vs `json`（9.7% > 6.1%） | `json` vs `structured`（35.1% vs 45.0%）、`structured` vs `prose`（23.1% vs 45.0%） |
| 2 | `json` vs `structured`（46.0% > 38.0%） | `code` vs `json`（**0.8%** vs 3.2%）、`structured` vs `prose`（24.3% vs 38.0%） |
| 4 | **全部三对** | — |
| 8 | `code` vs `json`（22.9%）、`structured` vs `prose`（53.3%） | `json` vs `structured`（22.7% vs 33.5%） |
| 16 | **全部三对** | — |

   ⇒ **可断言的**：C4/C8/C16 上完整排序成立；C1/C2 上只能分辨**首尾**（`code` 快于 `prose`，
   间隔 82.3% / 83.0%，远超误差棒），中间二类的相对位置**本表无法分辨**。

4. **一处方向一致但成因未识别的位移**：`prose` 在 C4/C8/C16 上一致地偏快 **+5.8%…+12.3%**，
   而其自身离散度仅 ±0.8%…±1.2%，故这是**真实位移**而非噪声。成因**未识别**，不能用 nonce
   泄漏解释（泄漏影响的是 61-token 提示词的波间预热，对 decode 影响可忽略，且四类型应同等
   受影响，而实际只有 `prose` 一致偏移）。列为 §11 未闭环项。

### §4.2 关于 `structured` 的不稳定性——**机理未识别**

事实（可由逐流记录复算）：

- 格内**逐流** `chars_per_token` 跨度可达 **1.188–3.661**（`structured` C8，2.85×）；
  而 `json` 几乎是常数 **2.448–2.484**。
- 但**流级关系不存在**：格内 `r(chars_per_token, decode_tps)` 在 20 格上**中位数 0.001**，
  **10/20 为负**（一次硬币投掷）。
- 跨格汇总得到的 `r = −0.295` 是**并发混杂的假信号**，不得引用。
- 单格的 `r = +0.317` **恰好是 `structured` C16 一格的值**（n=48）——把一个格网成员的值当成
  整网的结论，是「枚举完之前不算发现」在**数值**上的同一错误。

**因此**：`structured` 既是内容最不稳的类型、也是吞吐最不稳的类型，这使「内容可变性驱动吞吐
可变性」成为一条**值得检验的假设**，但本归档**不支持**把它写成结论。机理**开放**。

---

## §5 引导解码与通道

### §5.1 grammar A/B（`sampling_params.json_schema` 有 / 无）

两臂走同一 native `/generate` 通道、**同一提示词体**、同 SD-1 记账、**每请求独立 nonce**；
唯一差异是是否存在 `json_schema`。Δ = 「grammar − free」。schema 带 `minItems: 400`——
grammar 之下 `ignore_eos` 不再是绝对的（schema 一旦可满足，grammar 仍会发 EOS），可早满足的
schema 会让流提前结束，于是被比较的恰好是早停的行。

<!-- generated from grammar/grammar_ab.json -->

| C | decode tok/s/req (free) | decode (grammar) | Δ | agg decode (free) | agg (grammar) | Δ | prefill tok/s (free) | prefill (grammar) | Δ | median ct (free / grammar) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 73.35 | 76.66 | +4.5% | 73.3 | 76.7 | +4.6% | 332.6 | 301.5 | -9.4% | 2048 / 2048 |
| 2 | 39.94 | 59.66 | +49.4% | 75.9 | 118.4 | +56.0% | 299.1 | 262.5 | -12.2% | 2048 / 2048 |
| 4 | 38.46 | 46.92 | +22.0% | 135.4 | 186.3 | +37.6% | 213.2 | 237.0 | +11.2% | 2048 / 2048 |
| 8 | 25.81 | 32.74 | +26.9% | 154.1 | 259.2 | +68.2% | 134.4 | 177.8 | +32.3% | 2048 / 2048 |
| 16 | 21.88 | 29.38 | +34.3% | 234.0 | 463.7 | +98.2% | 117.2 | 113.8 | -2.9% | 2048 / 2048 |

> Archive note: the grammar stage that shipped is the second run of the day; the first
> run had no per-stream records and was overwritten in place (the run log names it
> `grammar2`, the archive ships it as `grammar/` because the second run fully replaces
> the first).

**读这张表之前必须先看 §5.2，这不是客套。** 本表两臂都在 native `/generate` 上，而 §4 里
无约束的 `json` / `code` 行走的是 **chat** 通道。因此「grammar 更快」这句话有两个完全不同的
可能含义：(a) grammar 真的让解码更快；(b) native 通道对**同一无约束请求**本就更慢，grammar
只是把通道让出的那部分追了回来。两种情况的处置截然不同——前者值得进生产，后者只说明本表
选错了基线。**只有 §5.2 能把这两句话分开**，所以在 §5.2 落地之前，本表的方向不构成任何结论。

### §5.2 通道对照（chat vs native，同一无约束提示词）

同一提示词体、无约束、强制吃满、每请求 nonce，**波内交替**两臂，以消除时间漂移。

⛔ **未跑，业主在 PR 段收口后取消了剩余阶段（cache / channel / grammar2），2026-09-18。**
§5.1 的判别问题——「grammar 更快」是 (a) grammar 让解码更快，还是 (b) native 通道对同一
无约束请求本就更慢——**因此保持开放**。在该对照落地之前，§5.1 的 grammar 行不得被引用为
「grammar 提升吞吐」的证据；唯一可用 §5.1 说的方向是 native 通道内 A/B（schema 有无），
它的两臂通道相同，不受此影响。

---

## §6 网关 `:8001` vs 直连 `:8899`（三臂）

`ROUNDS=2`，两路径**每轮内交替**执行（先 gw 后 direct），故时间漂移同时落在两侧。
每个请求带独立 nonce，**唯一例外**是 `wall` 臂：它有意复用**本方路径**自己刚发过的 `decode`
请求（「同一请求」正是该臂的意义），两路径到达该行时等温，对比仍对称。
Δ = 「网关 − 直连」；prefill / decode 为速率，**正值为网关更快**；`wall` 是时长，
**正值为网关更慢**。

<!-- generated from gw/gw_ab.json -->

Gateway `:8001` vs direct engine `:8899`, alternating within each round. Δ is "gateway − direct", in percent. Positive is the gateway ahead on prefill and decode tok/s; on the wall arm positive means the gateway is *slower*, because wall time is a duration. Every request carries its own nonce except the wall arm, which deliberately re-sends its own path's decode request unstreamed -- both paths reach that line equally warm, so the comparison stays symmetric.
| Arm | :8001 gateway (median) | direct :8899 (median) | Δ vs direct | n per arm |
|---|---:|---:|---:|---:|
| prefill tok/s | 1551.400 | 1537.000 | +0.9% | 2 |
| decode tok/s/req | 47.670 | 47.765 | -0.2% | 2 |
| wall s (not streamed) | 22.173 | 22.110 | +0.3% | 2 |

### §6.1 结论

**网关在三条臂上都与直连不可分辨**（|Δ| ≤ 0.9%）。其中 `wall` 臂是**唯一**能看见缓冲式中继的臂
（流式客户端不会等单次读完），它给出 **+0.3%**。

⚠️ **功效边界（必须连同结论一起引）**：`n = 2` per arm，本臂**不足以检出小量网关开销**。它排除
的是**数量级**的差异，不是个位数百分比的差异。要给出「网关开销 ≤ x%」的结论需加大 `ROUNDS`。

⚠️ **一处必须说明的口径事实**：`prefill` 臂的提示词实测 **262,090** prompt tokens，而非标签值
131,072——`BIG_TOKENS` 计的是 `" the"` 的**重复次数**，本 tokenizer 约 2 token/次重复。
**读 `prompt_tokens`，不要读该变量名。**

---

## §7 fp4-indexer 短输出臂（256-token 预算）

`code` 类型、256-token 预算。**只有开臂**：indexer 当前为**开**
（`--enable-deepseek-v4-fp4-indexer`），故这是 indexer-on 一侧。**indexer-off 一侧需要重启引擎**，
属窗口项（见 §11）——在它落地前，本表**不能**用来回答「开或关哪个更好」，只能回答「开着的时候
短输出的绝对水平是多少」。

<!-- generated from fp4_256/de_v3_matrix.json -->

Short-output arm (256 tokens) of the fp4-indexer A/B, `code` type. **One arm only**: the indexer is currently ON, so this is the indexer-on side. The off side needs a restart and is a window item.

| C | Median decode tok/s/req | Wave spread | Agg decode tok/s | Median prefill tok/s | Median ct | OK streams |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 88.58 | ±14.7% | 88.6 | 409.7 | 256 | 3 |
| 8 | 44.52 | ±15.4% | 356.0 | 188.1 | 256 | 24 |
| 16 | 36.99 | ±11.0% | 542.7 | 143.7 | 256 | 48 |

**读法**：与 §4 的 `code`（2048 预算）相比，短预算下单流更快（C1 88.58 vs 83.59）——输出短、
爬坡占比小。**但相对误差棒更大**（±11.0%…±15.4% vs §4 `code` 的 ±2.2%…±6.1%）：短输出的总
时长小，同样的绝对抖动占更大比例。**引用本表时误差棒不可省。**

---

## §8 缓存价值探针

该探针测量「重复提示词究竟值多少」。按 2048 / 32768 / 131072 三个尺寸，各发三次
（`cold` 新 nonce、`repeat` 字节全同、`distinct` 仅换 nonce），报
`worth = 1 − ttft_repeat / ttft_cold`，并留存三个 `prompt_sha16` 供自证
（`cold` 与 `repeat` 必须相同、与 `distinct` 必须不同——若前一对照不成立，探针没在测它声称的
东西）。

> ⚠️ 该探针**不得与任何矩阵并行运行**：把一个 131k-token 的 prefill 注入 C=1 测量是污染，不是
> 诊断。

⛔ **未跑，业主取消（同 §5.2，2026-09-18）。**「重复提示词究竟值多少」在本轮归档中保持
未测量。顺带一提：PR 矩阵的合成 prompt 使 engram 缓存在 PR 负载下命中率 100%、NVMe 读为 0
（引擎日志，12:44–12:50 连续 7 窗），而 09-16 真实流量下命中率为 71.4–84.1%——即 **PR 全表
对 engram offload 路径完全失明**；这正是本探针需要独立设计的原因，取消后该缺口仍在。

---

## §9 质量门

| 门 | 结果 | 口径与溯源 |
|---|---|---|
| GSM8K（600K 在役，fp4idx 关） | **0.9600**（192/200），err=0 | 200 题、**temp 0.6**、8-shot、concurrency 1、max_tokens 1024、median ct 128、耗时 501.0 s，经 `:8003` 网关发起 |
| GSM8K（fp4idx 开） | **0.535**（107/200），**err=92** | 同口径；92 条为网关侧错误（非错答）。**有效样本 108 条中 107 条正确 = 107/108**；同期基线 106/108 ⇒ 无回退。⚠️ 原始准确率 0.535 必须如实披露，不能只写「107/108」 |

归档：[`../../data/gsm8k-20260917/`](../../data/gsm8k-20260917/)。

> **本章是质量门，不属于本轮性能口径**。其数值测于 2026-09-17，且此后**引擎未变更**
> （无重启、无参数改动、镜像与 launch args 不变，见 §1.4），故不构成陈旧口径。
> 若后续进行窗口内变更（如 indexer 关臂），**必须先重跑质量门再宣告晋升**。

---

## §10 RoCE one-shot RDMA（2026-09-17/18）——**否决归档**

b12x `comm/roce` + SG17 patch + TP4 adapt 全部接线成功，但 QP 建联超时（RTR timeout）。

**根因：物理布线与 one-shot 全互联不兼容。** GID 表显示四机 HCA 分属两个互不互通的网段
（`<FABRIC_SUBNET_A>` / `<FABRIC_SUBNET_B>`，按脱敏政策占位符化），one-shot RDMA 要求 rank
两两直连，而环形 P2P 布线只保证邻居互通。**NCCL RING 不受影响**（复用同环）。

处置：env / overlay 全部回滚，生产回 NCCL RING 路径。补丁与部署脚本留档于机上台临时目录
（不入库）。

---

## §11 未闭环事项（诚实清单）

| # | 事项 | 状态 | 阻塞 |
|---|---|---|---|
| 1 | `prose` C4/C8/C16 一致偏快 **+5.8%…+12.3%** | 🟡 **成因未识别** | 需专门实验；见 §4.1 第 4 条 |
| 2 | `structured` 波次离散度 17.7%–45.0% 的机理 | 🟡 **未识别** | 见 §4.2；归档不支持现有假设 |
| 3 | GSM8K 质量门重测 | ⛔ 未做 | 非本轮范围（§9 已说明理由） |
| 4 | fp4-indexer **关**臂 | ⛔ 未做 | **窗口**（需重启） |
| 5 | NCCL channels=8 优化空间（外部反馈） | ⛔ 未做（只读评估已完成） | **窗口授权**；前置阻塞：`dsv41-serve.service` 用户级 enabled 但 **inactive / MainPID=0**，容器已跑 16 h 却不受该单元监管 ⇒ 上线会把生产置于**无自愈**状态 |
| 6 | compact ragged-verify 恢复 | ⛔ 被上游阻塞 | [sgl-project/sglang#39173](https://github.com/sgl-project/sglang/issues/39173) 仍 open |
| 7 | STS 校准表 | ⛔ 不可为 | 与第 6 项同源（需 compact 模式装载 confidence head） |
| 8 | 900K 单条 prompt | 🟡 形态 B 下不可用 | 配置容量问题（§9 之外的形态细节见[横向对比](../4DGX-dsv41-基准测试-横向对比-20260912.md)） |

### 关于第 5 项（NCCL channels = 8）的只读评估

- 本栈当前 `NCCL_MAX_NCHANNELS = NCCL_MIN_NCHANNELS = 4`（**双向钉死**），该值是 2026-08-17
  经 32 档 A/B 后正式冻结的基线，取代此前 16 通道。**「设为 8」不是从默认值出发的探索**。
- ⚠️ **诚实标注**：全交付目录检索**未找到 8 通道臂的独立结果表**。可确证的只有「4 通道通过并
  被冻结」；**不得**据此声称「8 已测过且更差」——该结论无归档支撑。
- 机制上本栈经验方向是**通道越少越快**（与「多通道 = 多并行」的直觉相反）：prefill 主消息
  368 KB allreduce 在 4ch 下为 **92 KB/通道**、8ch 为 46 KB、16ch 为 23 KB；该 ring-only 构建的
  tuner 按**消息总量**选协议（368 KB > `NCCL_TUNER_THRESHOLD` = 40960 ⇒ Simple），
  **通道数不改变协议分支**，收益来自每通道分片变大 + QP 竞争减少。
- **但今天的栈与冻结时不同**（当时 vLLM TP4；现在 SGLang fork TP4/**EP2** + DSpark k=6，EP 引入
  all-to-all）⇒ 值得重新确认。请求应写成「**确认冻结值在现栈仍成立**」。
- 判据 4 项可证伪（微基准 368 KB 延迟改善 ≥ 5%；DE 优化 ≤ 3%；PR 优化 ≤ 3%；
  **必须带 `NCCL_TUNER_DEBUG=1` 且留存日志证明实际生效通道数**）；窗口预算 ≈ 1 h 20 min。
- **本项结论：需窗口授权，尚未执行。**

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
> **§3–§8 的表格由 [`benchmarks/render_report_tables.py`](../../benchmarks/render_report_tables.py)
> 从原始归档机械产出后粘贴**，可重跑该命令逐字节复核（`scripts/check_report_tables.py`）；
> 报告正文中的派生量（排名、可分辨性判定）由 `python` 从同批归档复算，**无手算 / 口算值**。
> 任何引用本报告的下游文档须连同 **§1 口径** 一起引用。

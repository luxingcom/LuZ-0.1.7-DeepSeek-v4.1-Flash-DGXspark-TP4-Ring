# LuZ-0.1.7-DSV41F · DeepSeek-V4.1-Flash（SGLang）· 4× DGX Spark TP4 · 无交换机环网
> ### 📥 镜像下载（13.1 GiB）
>
> **[⬇ LuZ-0.2.9-dsv41-tp4-dgxspark.tar — 夸克网盘](https://pan.quark.cn/s/aa6b189231e3)** · 备用 **[百度网盘](https://pan.baidu.com/s/1-LvoV_xtF4hJKp5qaQH90g?pwd=luzi)** · 提取码 `luzi`
>
> SHA256 `c1840255408f8b8b012279153580d1310f5d7d9bc4f5aa4e4181bcc8bf23fb0d` · MD5 `3562a789ec0e9aa4bc80a7e54ba1be65` · 内容身份 `355a5e45cb2725ae` · 校验与安装：**[镜像下载 → §7](#7-镜像下载发布件)**


**仓库版本 v0.2.9**（2026-09-30），见[版本更新报告](docs/release-notes/RELEASE-NOTES-v0.2.9.md)。
镜像现为 `dsv41-sglang-optimized:0.2.9-ep1q2-fin2`（内容身份 `355a5e45cb2725ae`，**5 层**）：
**旧基座的最后稳定版**，也是 **EP1 使能链**（`EP_SIZE` 2→1，`DSV41_MOE_B12X` 1→0）
并烘入 P1a 三件 adapter（`draft_head_fp8_tp4`、`hc_fused`、`draft_tau`）。
解码 **c8 +4.0 % / c12 +4.8 %**；262k/131k 预填在靴噪声带内持平；QA 17/0。镜像**已重新打包供下载**（见下）。

> ⚠️ **0.2.9 未重跑 PR 矩阵**，且其解码数字来自**与 0.2.8 不同的基座** —— 两张表**不可比**，
> 不要把它们归一成一张表。0.2.8 的 50 格矩阵仍是**该基座**的矩阵权威。

在 **4× NVIDIA DGX Spark（GB10）无交换机 RoCE 环网**上以 **SGLang TP4** 部署
**deepseek-ai/DeepSeek-V4.1-Flash** 的生产方案。该模型为 ~550 B 参数 MoE
（40 层、每层 384 个路由专家、top-6 路由 + 1 个共享专家、MXFP4 专家权重、
原生 1 M 上下文、DSpark 投机解码）。

本仓库是上游 SGLang 配方之上的**环网适配 + 运维层 + 算子 overlay**：启动脚本、
SGLang 猴补丁 / 融合 decode 算子、自愈监控、基准门禁套件，以及**全部基准原始归档**。
**不含权重、镜像、NCCL 二进制。**

English → **[README.md](README.md)** · 完整文档 → **[docs/](docs/)** ·
基准口径与全部原始归档 → **[benchmarks/README.md](benchmarks/README.md)** / **[data/](data/)** · 📥 **[镜像下载 → §7](#7-镜像下载发布件)**

---

## 1. 当前在跑的是什么

下面的数字都标注了**测得它时的构建形态**。本仓库出现过多个形态，它们
**不可互换**——引用前先看标签。

**当前发布（v0.2.9，2026-09-30）—— 镜像与 EP1 使能链：**

| | 值 |
|---|---|
| 镜像 | `dsv41-sglang-optimized:0.2.9-ep1q2-fin2` —— 内容身份 **`355a5e45cb2725ae`**（**5 层**） |
| 相对 `ep1q2-fin` 的改动 | **EP1 使能链**（`EP_SIZE` 2→1、`DSV41_MOE_B12X` 1→0）＋ P1a 三件 adapter（`draft_head_fp8_tp4`、`hc_fused`、`draft_tau`）＋ memwatch ＋ PREFLIGHT `v1-fin2` ＋ 16 闸横幅 |
| 实测（对照 `ep1q2-fin`） | DE prose **c8 +4.0 % · c12 +4.8 %**；PR 262k/131k 在靴噪声带内持平；QA **17/0** |
| 它是什么 | **旧基座的最后稳定版** —— 新基座工作（LuZ-0.3.0）是另一条线 |
| 完整文档 | [docs/release-notes/RELEASE-NOTES-v0.2.9.md](docs/release-notes/RELEASE-NOTES-v0.2.9.md) |

> ⚠️ **0.2.9 未重跑 PR 矩阵**，且其解码数字来自**与 0.2.8 不同的基座**。两张表**不可比** ——
> 不要把它们归一成一张表。0.2.8 的 50 格矩阵仍是**该（0.2.8）基座**的矩阵权威。

**矩阵权威 —— 下文所有标注 *0.2.8* 的数字都测于这个形态：**

| | 值 |
|---|---|
| 镜像 | `dsv41-sglang-optimized:0.2.8` —— 内容身份 **`4cca364c46778423`**（3 层）（[BUILD-IDENTITY.md](BUILD-IDENTITY.md)） |
| 对 0.2.4 的改动 | **OOM 期工程收口** —— FIX-B/B′（空闲释放 + 调度器快照钩子）、FIX-D（logits 宽度分桶）、`mm_ban`（输入侧专用 id 采样屏蔽）、R2 page_table 网格、#40352 候选块协议（**默认关**）。纯增量，无任何削减 |
| 上下文 / KV 池 / 并发 | 600,000 / 9,600,000 token / 16 |
| chunk / EP / indexer | 8192 / EP2 / fp4 indexer **关** —— 生产 `.env.tp4` 不含 `--enable-deepseek-v4-fp4-indexer`（出现次数实测 0）；沿革见 §4 |
| 提升门禁（0.2.8 窗口） | PR 512K 单流 **> 4,500 t/s 硬门 ✓** · 512K × C16 **16/16 ok** · 零 OOM、8.4M token 角落后内存持平 |
| 完整文档 | [docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md) |

镜像 ID、SGLang commit、组件版本与发布件哈希：**[BUILD-IDENTITY.md](BUILD-IDENTITY.md)**。
思考模式写作 `OFF · ON`（两者都测过）。

**只有一套测量口径，且只写一次。** 本仓库所有性能表都是 **SD-1**：chat 通道 +
提示词标签式输出类型（无引导解码）+ 强制吃满输出预算 + 每请求独立 nonce + 单一聚合规则。
定义与设计理由在 [FINAL-METRICS §1](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)，
实现只有一处：[`benchmarks/sd_protocol.py`](benchmarks/sd_protocol.py)。每份归档都把口径与
波次数**写进 JSON 自身**，所以单个文件是自描述的。
**比较两行之前请先读 [FINAL-METRICS §1.3](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)：
每张表都带自己的误差棒，小于误差棒的差异不是结论。**

---

## 2. 形态 A — 600K 生产指标板

在生产构建上实测（**PR 矩阵与 DE 重测都测于 0.2.8**）。完整表格、逐格聚合与原始归档见
[docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)、
[`data/luz028-matrix-20260923/`](data/luz028-matrix-20260923/) 与
[`data/luz028-de-sd1-20260924/`](data/luz028-de-sd1-20260924/)。

### DE 单流 decode（4 种提示词标签，零 grammar，强制吃满）—— 测于 0.2.8

4 类型 × 5 并发 × 3 波；格中心值 = 全部有效流的 `statistics.median`。完整 20 格表、
总吞吐口径视图与 TTFT 见 [FINAL-METRICS §4](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)。
与 0.2.4 时代基线在同一 SD-1 口径下重测对照：**20/20 格全为正，零回退**
（漂移带 ≤5% PASS / 5–10% WATCH / >10% INVESTIGATE）。

| 类型 | C=1 | C=2 | C=4 | C=8 | C=16 | 波次离散度 | vs 0.2.4 |
|---|---:|---:|---:|---:|---:|---:|---|
| code | **89.19** | 73.36 | 61.71 | 44.11 | 37.75 | ±0.3–±6.1% | +0.9…+4.6% — 5/5 PASS |
| json | **85.90** | 69.28 | 54.84 | 36.70 | 31.44 | ±0.8–±2.7% | +2.4…+6.3% — PASS/WATCH |
| structured | **76.99** | 60.41 | 51.94 | 32.79 | 27.95 | ±4.9–±38.4% | +3.5…+38.2% — INVESTIGATE（正向） |
| prose | **51.92** | 40.06 | 29.88 | 19.51 | 15.94 | ±0.8–±3.0% | +4.5…+6.4% — PASS/WATCH |

> **`structured` 是提示词标签，不是 grammar 约束。** `code > json > structured > prose`
> 在全部五档成立，且离散度随并发放大，与 0.2.4 基线同型（C1 1.72× → C16 2.37×）。
> `structured` 仍是唯一离散异常类型（±4.9–±38.4% vs 其余 ≤±6.1%），其中四格大幅正向漂移
> （+16…+38%）：方向有利，但**成因未识别**——登记为未闭合项，不用「解释」把它抹掉。
> **DE 总吞吐（Σ 输出 token ÷ Σ 波墙钟）峰值 572.6 t/s @ code × C16** ——
> 572.6 / 488.3 / 363.0 / 247.6（code / json / structured / prose）；
> 对 0.2.4 基线同口径复算 543.9 / 481.0 / 262.8 / 236.4 ⇒ 峰值 **+5.3%**。

### PR 纯 prefill 总吞吐（40/40 格全齐，4K–512K）—— [FINAL-METRICS §3](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)

> 基线谱系：PR-v2 作废（2026-09-18，不刷缓存 / 非总吞吐）→ PR-v3@4096 被取代 → **v14**（chunk 8192 全量重测）→ **v18**（0.2.4，MoE W4A8-MX）→ **v19**（0.2.5，#40217 native port）→ **0.2.8**（OOM 期收口，**现行**；4K–512K 含 512K 多流）。被取代的归档保留供复核：
> [`data/sd1-20260918/pr/`](data/sd1-20260918/pr/)、[`data/prv3-20260918/`](data/prv3-20260918/)、
> [`data/prv3-v14-20260919/`](data/prv3-v14-20260919/)、[`data/prv3-v18-20260919/`](data/prv3-v18-20260919/)、[`data/prv3-v19-40217prep-20260920/`](data/prv3-v19-40217prep-20260920/)。
> **引用一律以下方 0.2.8 表为准。**

PR-v3 测的是压测真正关心的量：**从放行第一流到最后一流结束的墙钟内，全部 prompt token
之和 ÷ 墙钟**；`max_new_tokens=1`（**纯 prefill，无 decode 尾巴**），每请求唯一 nonce，
每格之间 `POST /flush_cache`。

| 输入 token | C1 | C2 | C4 | C8 | C16 |
|---:|---:|---:|---:|---:|---:|
| 4,096 | 4,464.8 | 4,480.5 | 4,530.9 | 4,875.8 | **5,033.1** |
| 8,192 | 5,360.1 | 5,337.1 | 5,165.3 | **5,383.3** | 5,326.1 |
| 16,384 | 5,498.8 | 5,638.4 | **5,639.3** | 5,618.9 | 5,494.8 |
| 32,768 | 5,772.0 | 5,781.2 | **5,810.3** | 5,691.9 | 5,689.8 |
| 65,536 | 5,792.5 | **5,823.1** | 5,777.6 | 5,701.7 | 5,724.3 |
| 131,072 | **5,791.1** | 5,671.6 | 5,620.8 | 5,600.9 | 5,675.0 |
| 262,144 | **5,585.7** | 5,429.9 | 5,439.9 | 5,496.1 | 5,520.1 |
| 524,288 | 5,042.2 | 4,976.9 | 5,009.1 | **5,066.6** | 5,038.8 |

**读表方式**（每格仅 1 波 ⇒ 无误差棒；只做同窗对照）：全表峰值
**5,823.1 t/s @65536×C2**，全表落在 **4,976.9–5,823.1 t/s**。并发并不驱动吞吐——
同一输入行内极差 **≤4.22%**。长文档**偏好「多个短提示词」而非「少数长提示词」**
（65536 行登顶；524288 行落在 4,976.9–5,066.6）。**512K 单流 = 5,042.2 t/s**，
越过硬门禁（`> 4,500`，**+12.05%**）；**本轮 512K 行在全部五档并发都测了**
（C16 5,038.8，16/16 ok）——早前各代只承诺单流。4,096 行属 `NON_ALIGNED`
（半 chunk 尺寸），不与整 chunk 行比较。每一格值都由逐流原始记录复算，并在发布前
与服务器 per-cell 表逐格断言相等（见[归档 README](data/luz028-matrix-20260923/README.md)）。

### 网关与短输出臂 *(v18 栈数字，未在 0.2.8 上重跑)*

| 指标 | 数值 | 说明 |
|---|---|---|
| `:8001` 网关 vs 直连 `:8899` | prefill **+0.9 %** · decode **−0.2 %** · wall **+0.3 %** | 每臂 n=2 —— 足以排除数量级差异，**不足以**排除个位数百分比差异（[§6](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)） |
| fp4 indexer，256 token 预算，`code` | C1 **88.58** · C8 44.52 · C16 36.99 t/s/流 | **只有一条臂** —— 测量时 indexer **开**（v18 形态 A）；关闭臂需要重启。**不是 A/B**，也**不是** 0.2.8 生产形态（[§7](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)） |

### 头部数字

**总吞吐（引用就引这两个数）：PR 纯 prefill 总吞吐峰值 5,823.1 t/s（65536 × C2，**0.2.8**）· DE 聚合 decode 峰值 572.6 t/s（code，C16，**0.2.8**，Σ 输出 token ÷ Σ 波墙钟）。**

| 指标 | 数值 |
|---|---|
| **PR 总吞吐峰值（纯 prefill，chunk 8192，0.2.8）** | **5,823.1 t/s**（65536 × C2）· 次高 **5,791.1 t/s**（131072 × C1）· 512K 单流 **5,042.2 t/s**（硬门 `>4,500` ⇒ **+12.05%**）· 任意输入行内极差 ≤4.22% |
| **DE 聚合 decode 峰值（总吞吐，0.2.8）** | **572.6 t/s**（code，C16）—— 对 0.2.4 同口径复算 543.9 ⇒ **+5.3%** · 单流 C1 峰 **89.19 t/s**（code） |
| DE vs 0.2.4（SD-1，同口径） | **20/20 格全为正，零回退** · code 5/5 PASS（+0.9…+4.6%）· structured 四格 +16…+38% 标 INVESTIGATE（正向；成因未识别） |
| GSM8K（200 题） | **0.9600**（192/200）· temp 0.6、8-shot · indexer 关 *（v18 栈数字，未重跑）* |
| 引擎冷启 | **345.7 s ≈ 5.8 min**（`tokenizer_e2e`）*（v18 栈数字）* |
| 提升门禁（0.2.8 窗口） | PR 512K 单流 >4,500 ✓ · 512K×C16 16/16 ok · 零 OOM · 8.4M token 角落后内存持平 |

引导解码的代价、chat 与 native 两通道的对照、以及「重复一次提示词值多少」这三件事，
各自作为独立臂测量，见 [FINAL-METRICS §5](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)
与 [§8](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)，原始归档就在
[`data/sd1-20260918/`](data/sd1-20260918/) 里。

**结构化输出两个坑** —— `sampling_params.json_schema` 传 **dict 会把引擎打崩**；grammar 之下
`ignore_eos=True` **不再绝对**（schema 可满足时仍会发 EOS）。两者都在 native `/generate`
路径上复现；机理与处置见 [benchmarks/README.md §3.1](benchmarks/README.md)。

---

## 3. 环网适配差异（相对上游 TP4 profile）

**传输 / 拓扑**

- ring-only NCCL 2.30.7 + `libncclpin` 核绑定 shim（`LD_PRELOAD`）；四边接线的
  per-rank `PEER_HCA`（`./start-tp4.sh ncclcheck` 可自检 ring-only 是否真的生效）。
  该库是 **LuZ 谱系**构建（靠 NCCL 算法矩阵 `Tree=0 / Ring=1` 实现 ring-only），
  **不是** SparkRing 的补丁库——见 [BUILD-IDENTITY.md](BUILD-IDENTITY.md)
- 节点本地权重（无 NFS）、loopback 引擎 + 并发代理、多别名 served name
  （旧名保留，消费端零改动）

**为环网做的调优**（每项单独 A/B，实测差值见配置示例头部注释）

| 设置 | 理由 |
|---|---|
| `EP_SIZE=2`（原 4） | 消除专家并行 straggler；500K 长档 prefill 595 s → 345 s |
| `MAX_RUNNING_REQUESTS=16`（原 12，最初 8） | 配合 `--min-free-slots-delay 1` 高位槽位才真正并行：12 路板上 c12 271 → 398；16 路是当前生产形态 |
| `DSV41_CACHE_GIB=1` / 16-way | Engram 行缓存：命中率 0 → 99.1 %，c12 +6 %，prefill 100K +10.5 % |
| `DSV41_SHARED_PAD_K=1` | 上游 PR#17：让共享专家 K=576 的形状重回 b12x（逐位无损） |
| static verify | 上游 compact/ragged 模式在 V4.1 上触发 engram target-verify 断言（sgl-project/sglang#39173） |
| `CHUNKED_PREFILL_SIZE=8192`（0.2.8 起为生产现役；原 4096） | 它是 524288 token 提示词**能装下**的原因，也是长提示词 prefill **逐请求串行**的原因。8192 在 2026-09-19 先作为**基准形态**测量，0.2.8 窗口并入生产 `.env.tp4`（`.env.tp4:156`）；**§2 的每一格都在 8192 下测得**，因此长输入提示词必须是 8192 的整数倍才可比。见 [benchmarks/README.md §3.2](benchmarks/README.md) 与 [FINAL-METRICS §1.4](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md) |

**fp4 indexer（`--enable-deepseek-v4-fp4-indexer`）在 0.2.8 定板生产里是关闭的。**
生产 `.env.tp4`（`EXTRA_SGLANG_ARGS`；env md5 `3f6a014d`）不含该 flag，因此本仓所有
标注 *0.2.8* 的行都是在该 flag **未设**的前提下测得 —— FIX-D 的 logits 宽度分桶相应地
**不在路径上**（见上方 0.2.8 additions 表）。

沿革（保留以免两种形态被混引）：**形态 A**（2026-09-17 起）**开启**该 indexer。其 A/B
（code-256，同口径）测得 c1 −6.4 % / c8 −0.9 % / c16 −3.3 % —— 轻微负向，当时知情保留；
0.2.8 定板将其移出生产形态。形态 A 与形态 B（1 M ctx / 5 M 池 / 12 路）是**不同配置**，
任何一行的数值都不该拿去和另一形态比。§2 中标注 *fp4 indexer，256 token 预算* 的那一行
是 2026-09-18 SD-1 窗口（v18 栈，未在 0.2.8 重跑）里**明确标注的测试臂**，不是生产形态。

⚠️ **运维禁令**：未先修好分桶之前，不得开启该 flag —— 现制在 2K 宽度上是 1024× 过分配。

**唯一保留的已知回退**：c6 聚合 260 → 236（−9 %），EP2 的副作用；c8/c12 涨幅远大于此。

---

## 4. 实验性算子优化（改了什么，以及你接受的风险）

生产构建在上游 SGLang 之上带了**三层实验内容**，外加一组 **0.2.8 新增的
env 门控调度器/分配器修复**（本节最后一小节）。全部由 env 门控或文件级 graft，
上游行为只差一个开关。它们既是本构建实测增益的主要来源
（c12 聚合 +47 %、decode 峰值 +12 %、prefill 100K +4–10 %），也是升级风险的主要来源。
**钉新上游 commit 之前请先读这一节。**

### 第一层 — b12x CuTe 内核（b12x 项目 fork，随仓库 `b12x-site/` 分发）

b12x 是消费级 Blackwell（SM120/SM121）的 CuTe-DSL 内核库：NVFP4/MXFP4/MXFP8 GEMM、
融合 MoE、paged/dense/sparse MLA 注意力、DSA indexing、mHC 残差、PCIe 集合通信。
本仓库把它 vendor 到 `b12x-site/`，并把选定的 SGLang 算子路由过去：

- **MoE →b12x**（`adapter/moe_b12x.py`，门 `DSV41_MOE_B12X=1`，默认
  `DSV41_MOE_B12X_QUANT=a8`）：在 replicated-input EP 契约下把 `flashinfer_mxfp4`
  MoE 路由到 b12x `fused_moe`。**实测区间**（原始数据
  [`docs/operators/moe-bakeoff-20260914.json`](docs/operators/moe-bakeoff-20260914.json)）：
  b12x 在小/decode M 领先（M=6 延迟 −10 % … M=2048 a8 −5.2 %）；**W4A16 在 M≈2048
  被反超**（较 FlashInfer CUTLASS W4A8 慢 +7.2 %）——早期 docstring 把 a8 数字误标成
  a16、夸大了适用区间，2026-09-19 已纠正。实测上限之上（M=4096–8192，
  `--chunked-prefill-size` ≥ 4096 时可达）**尚无 a8 实测**：prefill 密集负载应设
  `DSV41_MOE_B12X=0`（全 FlashInfer W4A8），第三方长输入评测在该形态测得 +30–89 %
  随长度放大。MMAX→FlashInfer 混合路由**仅在 `DSV41_MOE_B12X_DUAL_HOLD=1` 时武装**——
  single-hold 下启用会静默污染大 M KV（见[事故分析](docs/operators/V41-B12X-LARGEM-REGRESSION-ANALYSIS-20260919.md)）。
- **Dense MXFP8 线性层 → FlashInfer b12x 后端**（`adapter/mxfp8_b12x.py`，
  `DSV41_MXFP8_BACKEND=b12x`）：SGLang 的 CUTLASS SM120 内核在 decode 时把 M=6
  pad 到 128（实测 50–75 GB/s，占 118 ms decode step 中的 52 ms）；b12x 的 warp 级
  内核直接吃小 M tile。
- **共享专家 K pad**（`adapter/shared_pad_k.py`，门 `DSV41_SHARED_PAD_K=1`）：
  把 down_proj K 576→640，让唯一被 b12x 拒绝的形状重回快路径（输出逐位相同；
  零 block-scale 编码为 1.0）。
- **MoE 阶梯 cap**（`DSV41_MOE_B12X_CAPS=128,256,512,1024,2304,4096`、
  `DSV41_MOE_B12X_QUANT=a8`）：按桶给精确内核，96 行以上转 a8 激活量化。

### 第二层 — 融合 DeepSeek-V4 decode 算子（`sglang-overlay/`）

按文件 bind-mount graft 到镜像的 sglang 树上（映射见 `start.sh` 的 `SGLANG_OVERLAY_MAP`；
同一批文件在构建时也烘焙进生产镜像）。主要算子（把上游的多个 kernel 融成一个）：

- `c1.py` — 融合 ratio-1 decode：RMSNorm + RoPE + FP4 伪量化 + FlashMLA cache 写
- `c2.py` — 融合 ratio-2 pair-pooling decode + 主 KV 写（闭式 softmax；fp32-ulp 差异在文件内登记）
- `fused_norm_rope_v2.cuh` / `main_norm_rope.cuh` / `store.cuh` / `c1.cuh` / `c2.cuh` /
  `kv_layout.cuh` — 同一批融合的 CUDA 侧
- `dspark_accept.py` / `dspark_draft.py` / `fast_argmax.py` / `dflash_info_v2.py` —
  DSpark 投机解码接受/起草路径（两段式 split argmax、打包 top-k）
- `decode_cuda_graph_runner.py`、`deepseek_v4_backend.py`、`deepseek_v2.py` — 图捕获与后端路由
- `deepseek_v4_memory_pool.py` + `kv_cache_configurator.py` — **fork-v4-fp4 KV 布局**：
  ratio-1 latent 以 FP4 存储（相对上游的二次 FP8 舍入是无损的；ratio-4/128 latent 仍为 FP8）
- `dsv4_prefill_reuse.py` — 相邻 prefill query 行复用重叠 top-K 集合（env 门控，默认关）
- `engram.py` / `engram_hash.py` — Engram 嵌入行缓存接入

### 第三层 — 宿主侧适配器（`adapter/`）

- `engram_backend.py` + `librow_store.so`（源自 `row_store.cpp`）— 给 EngramEmbedding
  的 owned-row gather 做有界、精确、文件支撑的替代（C++ 扩展，**非纯 Python**，
  需要匹配镜像才能跑）
- `prefill_empty_cache.py` — 在长 prefill 的 chunk 之间把瞬时 indexer 内存还给分配器
  （600K 上下文的余量来源）

### 0.2.8 新增 —— OOM 期收口（调度器 / 分配器，不是内核）

事故背景：**2026-09-21 四机连环 OOM** 已定位为 **prefill chunk 的瞬时内存绞死**
（CUDA 缓存分配器，每 chunk 约 0.5–1 GB，调度器自己的记账**看不见**），
叠加健康检查磨死与 Linger 自启。0.2.8 是这批修复的收口。下表「镜像缺省」指不接线时的
行为——**「代码缺省为关」与「生产在跑」在这里同时成立**，所以两列都给：

| 项 | 门控 | 镜像缺省 | 生产（`.env.tp4`，md5 `3f6a014d`） |
|---|---|---|---|
| FIX-B 空闲释放 | `DSV41_IDLE_RELEASE` | `0` 关 | **`1` 开** |
| FIX-B′ SIGUSR1 内存快照钩子 | `DSV41_SCHED_SNAPSHOT` | `0` 关 | **`1` 开**（诊断；全链 fail-open） |
| FIX-D logits 宽度分桶 | 硬编码，无 env 门 | 随 fp4-indexer 分支 | **不在路径上**（该 flag 未开） |
| `mm_ban` 输入侧 id 屏蔽 | `DSV41_BAN_MM_PLACEHOLDERS` / `DSV41_BAN_PROMPT_CONTROL_TOKENS` | `1` 开 | **开**（缺省即开） |
| R2 page_table 宽度网格 | `SGLANG_DSV4_PAGETABLE_PAGES_GRID` | `1024` → 网格**开** | **`1` → 网格关**（有意选择） |
| #40352 候选块协议 | `DSV41_IDX_PROTOCOL` | `false` | **`1`** —— 256K/512K 单流的存活开关 |

- **FIX-B** 只在**完全空闲窗**内释放分配器段（无 running、无 queued —— 与
  `flush_cache` 内部 `empty_cache` 同一类窗口）。剂量上限如实记录：16 K 干净，
  32 K 会在三台机上擦墙 ⇒ 它救**请求边界**，救不了请求**进行中**的峰值。
  （v1 **永不 fire**：它读的 `memory_stats()` 键在这个 torch 版里带 `.current`/`.peak`
  后缀，查不到即取 0、函数静默返回。v2 改用官方包装后才全链通过。）
- **FIX-D** 把每 chunk 的 logits 分配宽度从 **9185 个互异值坍缩到 2 个**，
  分配器因此能按类复用。⚠️ **运维禁令**：将来若启用
  `--enable-deepseek-v4-fp4-indexer`，**必须先把分桶改掉**——现制在 2K 宽度上
  是 **1024× 冗余**。
- **`mm_ban`** 在采样层屏蔽 438 个输入侧专用 id，**target 与 draft 两侧同置**。
  `129271..129278` 有意**不**屏蔽（它们是合法视觉 grounding 输出），
  所以这个集合是**显式枚举 + 与 tokenizer 对表**——**不能按 id 区间、也不能按
  `special` 标志推导**。边界：它过滤的是**采样**，对「请求体回显」类泄漏无效。
- **R2 网格**：置 `1024` 时，超过 1024 页的 page_table 宽度向上取整到 1024 的倍数
  （堵住「宽度随上下文变宽 ⇒ 每 chunk 都拿不到可复用的块」的漏网点），
  网格线以下保留 legacy 精确尺寸。生产置 `1`（关网格）——这是 2026-09-22 阶梯窗的
  延续，不是疏忽。
- **#40352**（语义级回移，不是整链回移）把 prompt 侧候选从「逐 token fp32 打分矩阵 +
  bool 掩码」（600K 下每层约 17 GB + 4.3 GB）改为按候选块发布 **int32 block-id 表**。
  发布物体积缩减 **73.2×**（600K 角：`2048 × 4 B` vs `600000 B`）；候选覆盖
  **2.73 %** 的 token，即旧 bool 掩码 **97.27 % 是纯浪费**。关时**零耦合**
  （新模块惰性导入）。CPU 等价门：**42/42 PASS**（7 场景 × 4 项，含生产形状
  600 K / 8192 逐元素相等）。

### ⚠️ 使用本构建即接受的 7 条风险

1. **逐位一致性是按路径的，不是全局的。** c1/c2 用闭式 softmax 与 FMA 收缩，
   可能与 torch 差 fp32 ulp；MoE `a8` 模式在精确阶梯之上做激活量化。
   质量门（GSM8K 0.9600、needle 30K–470K、corruption 0/0/0、code-gate 12/12）
   是在钉死的**形态 B** 构建上通过的——换采样温度或负载构成会移动尾部。
2. **版本钉死是承重的。** 内核绑定 [BUILD-IDENTITY.md](BUILD-IDENTITY.md) 记录的
   SGLang commit + FlashInfer 0.6.18 + PyTorch 2.13.0+cu130 + driver 580.173.02。
   一旦 rebase 上游，graft（尤其 `deepseek_v2.py`、`deepseek_v4_backend.py`、graph runner）
   会最先破——`SGLANG_OVERLAY_MAP` 是 shim 面，不是 API。
3. **K-pad 与阶梯是形状耦合的。** 共享专家 pad 写死 K=576→640；换
   `moe_intermediate_size` 或 TP 度数会静默改变形状，pad 要么空转要么错路由。
   `DSV41_MOE_B12X_CAPS` 同样编码了这个模型的桶几何。
4. **FP4 KV 布局把每 token latent 字节减半。** ratio-1 latent 实测无损
   （上游本来也按 fp4 舍入），但它改变了内存池布局——第三方池工具或未来的上游
   布局变更读不懂它。
5. **图捕获安全性依赖自觉。** b12x `bind()` 是按捕获安全写的，
   `freeze_kernel_resolution` 在活请求中碰到 cache miss 会抛错——但任何新形状
   在服务中撞上冻结集合都是**硬错误**，不是慢回退。
6. **回退项已登记、不藏**：c6 聚合 −9 %（EP2 副作用）；形态 B 配置下 900K 上下文不可用
   （Engram 缓存 + K-pad 缓冲吃掉约 2 GB 深上下文余量；600K 及以下不受影响）；
   **single-hold 下的 MoE 混合路由会污染大 M KV**（`MMAX` 委派必须搭配
   `DSV41_MOE_B12X_DUAL_HOLD=1` 才允许武装——已由 needle 门抓获，见
   [docs/operators/](docs/operators/)）。
7. **无上游 review。** 这里每个文件都是本地工程产物（r9-ops 通道工作，
   2026-09-15 波次移植上游 PR #38409/#39370/#39420/#39187/#38979 并为本 fork 重写）。
   请把它当工程快照，而不是可分发的补丁集：复用前请按你自己的威胁/性能模型审 `sglang-overlay/`。

---

## 5. 历史指标板（已被接替）

早期配置形态的对照数字已从本页撤下——它们回答的是**旧形态**的问题，与 §2 不可比
（上下文/池容量、并发上限、indexer 开关、SD-1 之前的记账口径都不同）：

- **形态 B — 调优参照（1 M ctx / 5 M KV / C12，2026-09-13）**：六栈横向对比全文在
  [docs/4DGX-dsv41-基准测试-横向对比-20260912.md](docs/4DGX-dsv41-基准测试-横向对比-20260912.md)。
  其 decode 100.3 tok/s、prefill 3102/3443/3253 t/s、aggregate c1–c12（峰值 398 tok/s）、
  470K/600K/900K 长上下文等头部数字只属于该形态（900K 在该形态下失败，属配置容量问题）。
- **v19（0.2.5，#40217 native port）—— 2026-09-20 ~ 2026-09-23**：在 0.2.8 矩阵接替
  之前持有本页的指标板。归档 [`data/prv3-v19-40217prep-20260920/`](data/prv3-v19-40217prep-20260920/)；
  它是**最后一个测于 v18 时代栈**的指标板，与 §2 **不能逐格对比**
  （引擎构建与算子集合都不同）。
- **PR-v2 / PR-v3@4096 / v14 / v18 各代 PR 板**：作为审计归档保留在
  [`data/`](data/)（`sd1-20260918/pr/`、`prv3-20260918/`、`prv3-v14-20260919/`、
  `prv3-v18-20260919/`）——引用一律用本 README §2。

## 6. 仓库内容

- `start.sh / start-tp4.sh / stop.sh / boot.py` — 编排、锁修订版下载、冒烟 + 预热
- `adapter/` — SGLang 补丁（Engram 行存储 C++、MXFP8 后端、共享专家 K padding、prefill 缓存钩子）
- `sglang-overlay/` — **宿主覆盖位**：graft 到镜像 sglang 树上的融合 DeepSeek-V4 decode 算子（上文第二层）。它**只在开发模式**（`SGLANG_CODE_MOUNTS=1`）被消费；生产模式（`=0`，默认）代码只来自镜像。⚠️ 本目录**尚未**与任何已发布镜像逐字节同步 —— 要核对"生产实际跑的代码"，请以镜像为准，逐件摘要见 [RELEASE-NOTES §2.4](docs/release-notes/RELEASE-NOTES-v0.2.8.md)。详见 [`sglang-overlay/README.md`](sglang-overlay/README.md)
- `b12x-site/` — vendor 的 b12x CuTe-DSL 内核库（上文第一层）
- `gateway/` — **流式感知并发网关**（引擎前的 `:8001` 网关）：SSE 心跳、TTFT 预算、
  背压准入、等值去重、断连传播、`/gw/metrics`、可选 `enable_thinking` 注入，
  以及图像占位符净化 —— 客户端把历史图像序列化成字面文本时，否则整请求会被硬 `400`
  拒绝、会话即死。附脱敏后的 `.env.example`（16 个旋钮全部注释说明）、systemd 单元
  样例与 15 项单测；不含内部主机名、端口与 URL。血缘表与等价性论证见
  [`gateway/README.md`](gateway/README.md)
- `scripts/` — SSH 助手、`verify/` 探针集、自愈监控 + systemd 单元、`gate.sh`、`nccl_selfcheck.sh`、
  `verify_release_artifact.py`（**离线**归档校验器：blob 完整性 + 内容身份，无需集群），
  以及四个仓库自检（`check_redaction.py`、`check_relative_links.py`、`check_report_tables.py`、
  `check_env_coverage.py` —— 启动器↔模板契约）
- `benchmarks/` — 产出这些表的 harness，附
  [harness → 归档映射](benchmarks/README.md)、[SD-1 口径](benchmarks/README.md)、
  [脱敏策略](benchmarks/README.md)、以及
  [§3.2 引擎 prefill 准入律](benchmarks/README.md)
- `bench/` — 门禁套件（needle / corruption / termination / code-gate）、vision 门禁、
  散文、GSM8K、第三方形状扫描、MoE 数值/容量阶梯
- `data/` — **基准原始归档**。现行权威：
  [`data/luz028-matrix-20260923/`](data/luz028-matrix-20260923/)（PR，40/40 格 @ `chunk 8192`，
  含逐流原始记录 + `TABLE.md` + 运行身份）与
  [`data/luz028-de-sd1-20260924/`](data/luz028-de-sd1-20260924/)（DE，20/20 格 @ SD-1 口径，
  含逐流记录、3 波、与 0.2.4 基线对照重测）。谱系：
  `prv3-v19-40217prep-20260920/`、`prv3-v18-20260919/`、`prv3-v14-20260919/`、
  `prv3-20260918/`；`data/sd1-20260918/` 下有 DE 矩阵（含逐流原始记录）、grammar A/B、
  fp4 短输出臂、网关 vs 直连、以及两次 GSM8K；另有两份被取代的 PR 归档
  （`data/prv3-20260918/`、`data/sd1-20260918/pr/`）保留供复核。发布件的离线审计记录在
  `data/release-artifact-20260918/`（v0.2.4 包）与
  [`data/release-artifact-20260923/`](data/release-artifact-20260923/)（0.2.8 tar：md5、
  9/9 blob 摘要、层链解压校验、身份复现）。
  每一个公布的数字都能由这些文件复算——[`data/README.md`](data/README.md) 说明怎么复算，
  并**点名列出唯一一个不能复算的列**
- `.env.tp4.example` — 本仓库实际运行的配置（脱敏模板；现网 `.env.tp4` 已 gitignore）。与 0.2.8 生产 `.env.tp4` 的**逐键对照**、四处 `IMAGE` 出处、以及 0.2.8 的改动清单见 [docs/CONFIG-v0.2.8-ENV.md](docs/CONFIG-v0.2.8-ENV.md)
- `BUILD-IDENTITY.md` — 镜像 ID、SGLang commit、组件版本、发布件哈希，
  以及用于核对镜像的**内容身份公式**
- `docs/` — 部署方案、上游 ISSUE/PR 调研、基准横向对比、终版指标板、
  以及[版本更新报告](docs/release-notes/)、
  [算子全景清单与回退台账](docs/operators/)（§4 的证据底座）、
  [autotune golden 锁定与重建规程](docs/operators/AUTOTUNE-GOLDEN-RUNBOOK.md)
  （FlashInfer 战术表为何被钉住、以及重抽它必须先过的质量门）、
  与[工程保障报告](docs/engineering-assurance/)（0.2.8 矩阵窗 + DE SD-1 判决，均为脱敏发布版）

---

## 7. 镜像下载（发布件）

**当前发布件 —— `v0.2.9`（2026-09-30）。** 服务镜像（**13.1 GiB**）经网盘分发（双通道）：

- **夸克网盘**：https://pan.quark.cn/s/aa6b189231e3
- **百度网盘**：https://pan.baidu.com/s/1-LvoV_xtF4hJKp5qaQH90g?pwd=luzi（提取码 `luzi`）
- **文件**：`LuZ-0.2.9-dsv41-tp4-dgxspark.tar` —— **未压缩 OCI tar**，`docker load -i` 无需 `zstd`
- **大小**：14,055,778,304 字节（13.09 GiB）
- **SHA256**：`c1840255408f8b8b012279153580d1310f5d7d9bc4f5aa4e4181bcc8bf23fb0d`
- **MD5**：`3562a789ec0e9aa4bc80a7e54ba1be65`
- **内容身份**：**`355a5e45cb2725ae`**（**5 层**）—— 载入后还原为
  `dsv41-sglang-optimized:0.2.9-ep1q2-fin2`

该文件的离线审计与身份数据落档在
[`data/release-artifact-20260930/`](data/release-artifact-20260930/)。

**四机分发校验**（部署之后、信任任何基准数字之前先跑；随本次发布分发 —— 见
[`scripts/verify_fleet_distribution.sh`](scripts/verify_fleet_distribution.sh)）：

```bash
./scripts/verify_fleet_distribution.sh \
  --image dsv41-sglang-optimized:0.2.9-ep1q2-fin2 \
  --identity 355a5e45cb2725ae --expect-layer-count 5 \
  --nodes <head-node> <worker-rank1> <worker-rank2> <worker-rank3>
# → four nodes agree, and agree across nodes ⇒ RESULT: PASS (exit 0)
```

它**先断言存在、再断言身份**。对**不存在的镜像**跑 `docker image inspect … | sha256sum`
**不会失败** —— 它会返回一个看着很像样的常量（`e3b0c442…` = `sha256("")`、
`01ba4719…` = `sha256("\n")`），于是两台**都缺该镜像**的机器会**通过**朴素的比对。
因此身份**永不**从缺失的镜像上计算。

然后在四台机器上分别载入（**四台都需要**该镜像）并按内容身份自检：

```bash
docker load -i LuZ-0.2.9-dsv41-tp4-dgxspark.tar   # 还原为 dsv41-sglang-optimized:0.2.9-ep1q2-fin2
docker image inspect -f '{{join .RootFS.Layers " "}}' dsv41-sglang-optimized:0.2.9-ep1q2-fin2 \
  | sha256sum | cut -c1-16      # 期望：355a5e45cb2725ae
```

**上一发布件 —— `v0.2.8`（2026-09-24）**，保留的原因是其 50 格 PR 矩阵仍是**该基座**的矩阵权威：

- **夸克网盘**：https://pan.quark.cn/s/ca93fedc6376（提取码 `RHdj`）
- **百度网盘**：https://pan.baidu.com/s/17IDk222FbLkLKTIqBJ6AzQ?pwd=luzi（提取码 `luzi`）
- **文件**：`LuZ-0.2.8-dsv41-tp4-dgxspark.tar`
- **大小**：14,002,663,936 字节（13.0 GiB）
- **MD5**：`a9d4cdf932203f173df7556aa511fee1`
- **SHA256**：`6c94745b261eb01a6bea9864af443d0e89583562c624926b30f9dfbc771ec3a4`
- **内容身份**：**`4cca364c46778423`**（3 层）—— 14 个成员的 OCI 布局（9 个 blob +
  `index.json` + `manifest.json` + `oci-layout` + 2 个目录项）。

> **认哈希，不要认文件名或体积。** 相邻版本几乎无法凭体积区分：0.2.8 与 0.2.4 只差
> 604,160 字节（+0.0043 %），0.2.9 与 0.2.8 只差 +0.38 %。0.2.8 文件的离线审计记录
> （md5、9/9 blob 摘要、层链、身份复现）已随仓库落档在
> [`data/release-artifact-20260923/`](data/release-artifact-20260923/)。

载入之前先**离线自证**（无需集群、无需 docker 守护进程、无需 GPU）：

```bash
python scripts/verify_release_artifact.py LuZ-0.2.8-dsv41-tp4-dgxspark.tar --md5 \
  --expect-identity 4cca364c46778423 --layer-chain
# md5 吻合 · 9/9 个 blob 的 sha256 全部自洽 · 0 个未引用 blob
# 内容身份 4cca364c46778423 · 层链 3/3 解压摘要等于 config 的 diff_id
# RESULT: PASS  （退出码 0）
```

然后在四机分别载入，并按内容身份自检：

```bash
docker load -i LuZ-0.2.8-dsv41-tp4-dgxspark.tar   # 还原为 dsv41-sglang-optimized:0.2.8
docker image inspect -f '{{join .RootFS.Layers " "}}' dsv41-sglang-optimized:0.2.8 \
  | sha256sum | cut -c1-16      # 期望：4cca364c46778423
```

该一行式**就是 `start.sh` 自检与开机横幅用的同一条公式**，所以本机算得过＝集群断言也过得。
**不要**用层数、`docker images SIZE`、或 `docker image inspect --format '{{.Id}}'` / `{{.Config}}`
验收：它们报出的对象在 head 与 worker 之间（或不同 `docker images` 版本之间）**本来就不同**，
而**内容完全相同**——这类判据只会制造「四机不一致」的假警报。真正把归档与在跑机队绑定的量是
**层清单**，而且**序列化口径本身承重**：同一份三层摘要可以**七种**写法、哈希出**七个**不同值，
只有「空格连接 + 尾随换行」那一种（`{{join .RootFS.Layers " "}}` 接 `sha256sum`，即
`4cca364c46778423`）是权威。七种全表、以及空输入陷阱（`01ba4719c80b6fe9` 表示**镜像缺失**，
不是身份）见 [BUILD-IDENTITY.md](BUILD-IDENTITY.md)。

### 起栈

镜像只是一半 —— 启动器还需要你自己集群的四个站点键。首次运行时它会替你把模板
复制出来，并提示你去改：

```bash
./start-tp4.sh doctor      # 首次会把 .env.tp4.example 复制成 .env.tp4，然后报告
                           # 连通性 + GPU + checkpoint
$EDITOR .env.tp4           # 四个站点键：HEAD_IP / WORKER_IPS / WORKER_HOSTS / WORKER_USER
./start-tp4.sh share       # head 通过 ConnectX 上的 NFSv4 导出它的 checkpoint
./start-tp4.sh serve       # 先起 workers，再起 head —— API 在 :8899
```

`./start.sh help` 会打印完整的子命令表（`doctor | pull | build | pack | download |
share | mount | sync | serve | stop | status | logs | smoke | ncclcheck | gate`）。
`start-tp4.sh` 只是个薄包装：它把 `ENV_FILE` 钉在 `.env.tp4` 上，然后转交
`start.sh`。legacy 三机 profile（`.env` / `start.sh`）仍在树里，但**本版发布的
每一个数字都不是在它上面测的**（选择逻辑见 `start.sh` 顶部的 `Profiles:` 块）。

有两样东西没有哪个模板能给：
- `PEER_HCA_RANK*` 布线表 —— 从一次 `NCCL_DEBUG=INFO` 首启里推（见 §8），或按
  `.env.tp4.example` 里写的三步做
- 权重本身 —— `MODEL_DIR` / `WORKER_MODEL_DIR*` 指向 `$HOME/NewModels/…`，
  checkpoint 不随本仓分发

---

## 8. 脱敏说明与仓库状态

内部 IP / 主机名已占位符化、API key 已移除（`YOUR_API_KEY`）；站点 `.env.tp4`
由 `.gitignore` 排除。

**唯一需要掩码而非归类的一项是 `PEER_HCA_RANK0..3`**：在 4 机环网上，那张映射等价于
物理布线。`.env.tp4.example` 用 `<PINNING>` 加**三步推导**替代，让你能从一次
`NCCL_DEBUG=INFO` 首启自行推出自己的映射，并用 `./start-tp4.sh ncclcheck` 验证。
理由、以及**明确不动**的命中清单（通用地址方案、上游作者标识、原厂 HCA 名）见
[benchmarks/README.md §4](benchmarks/README.md)。
`scripts/check_redaction.py` 会重扫全部内容，任何阻塞类未归类命中都会以非零码退出。
**这个检查器本身也要被检查**：往树里注入一个已知的坏路径与一个已知节点主机名，它必须
**失败**（`exit 1`）；移除后必须**通过**（`exit 0`）——一个从未被证明会失败的扫描器，
什么也证明不了。0.2.8 的三份归档（`data/luz028-matrix-20260923/`、
`data/luz028-de-sd1-20260924/`、`data/release-artifact-20260923/`）用的就是同一次
fail-closed 运行。

仓库默认分支是 **`main`**，**适配内容就在 `main` 上**——本仓库是一份独立的工程快照，
**不是**上游项目的某个分支。上游归属见下表与 [BUILD-IDENTITY.md](BUILD-IDENTITY.md)。

| 组件 | 来源 | 许可证 |
|---|---|---|
| SGLang 配方（boot、适配器、Engram 行存储、DSpark 设置） | [`ntxf31415/DeepSeek-v4.1-Flash-DGX-Sparks`](https://github.com/ntxf31415/DeepSeek-v4.1-Flash-DGX-Sparks)（亦以 `MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks` 发布） | AGPL-3.0-or-later |
| 配方谱系 / 基准方法 | [`0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000`](https://github.com/0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000) | MIT |
| 宿主 ring-only NCCL 2.30.7 构建 + `libncclpin` 核绑定 shim（宿主侧，仓库不含） | [`luxingcom/aicad-nccl-optimization`](https://github.com/luxingcom/aicad-nccl-optimization)（LuZ 谱系） | **未声明许可证** |
| 模型权重 | `deepseek-ai/DeepSeek-V4.1-Flash`（Hugging Face） | 见模型卡 |

**姊妹项目：** [DeepSeek-V4-Flash-Vision-Exp TP4 无交换机环网](https://github.com/ntxf31415/deepseek-v4-vision-exp-dgxspark-tp4-switchless-ring)（vLLM，同一环网底座）· [GLM-5.3-Flash NVFP4 TP4 无交换机环网](https://github.com/ntxf31415/glm-5.3-flash-nvfp4-4x-dgx-spark-switchless)（同底座配方）。

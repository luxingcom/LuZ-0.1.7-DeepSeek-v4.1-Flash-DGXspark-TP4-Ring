# LuZ-0.1.7-DSV41F · DeepSeek-V4.1-Flash（SGLang）· 4× DGX Spark TP4 · 无交换机环网
> ### 📥 镜像下载（13.5 GiB）
>
> **[⬇ LuZ-0.2.4-dsv41-tp4-dgxspark.tar.zst — 百度网盘](https://pan.baidu.com/s/1FUJUQ8ZYK5ZIsYZBK8aqkg?pwd=luzi)** · 提取码：`luzi`
>
> MD5 `9daeb2ba314a1380988ed6f8afbe4657` · 内容身份 `4ebef21b6aedbd70` · 校验与安装：**[镜像下载 → §7](#7-镜像下载发布件)**


**仓库版本 v0.2.5**（2026-09-20），见[版本更新报告](docs/release-notes/RELEASE-NOTES-v0.2.5.md)。
镜像升级为 `dsv41-sglang-optimized:0.2.5`（别名 `v19-40217prep`，image ID `ab5a109f…`，
内容身份 `b4ca63d71bbe8557`）：**#40217 最小原生移植**（dense indexer candidate mask
无界项收界 `[tail≤128, lc]`）+ engram stats v2。下方 §7 的 0.2.4 下载包是**最近一个
已打包**的发布件；0.2.5 镜像暂以源码 + `start.sh` 重建分发（身份在构建时重新推导）。

在 **4× NVIDIA DGX Spark（GB10）无交换机 RoCE 环网**上以 **SGLang TP4 / EP2** 部署
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

下面的数字都标注了**测得它时的构建形态**（v19 = 0.2.5 现役；DE 等臂仍是 v18 栈数字，
已逐处标注）。引用前先看标签。

当前生产（下文标注 *v19* 的数字全部测于该构建）：

| | 值 |
|---|---|
| 镜像 | `dsv41-sglang-optimized:0.2.5` —— 内容身份 **`b4ca63d71bbe8557`**（[BUILD-IDENTITY.md](BUILD-IDENTITY.md)） |
| 对 0.2.4 的改动 | **#40217 最小原生移植**（dense indexer candidate mask 曾是无界 `[chunk≤8192, lc]` bool，245K 前缀 ≈2 GiB —— 现收界 `[tail≤128, lc]`）+ engram stats v2（观察面） |
| 上下文 / KV 池 / 并发 | 600,000 / 9,600,000 token / 16 |
| chunk / EP / indexer | 8192 / EP2 / fp4 indexer 开 |
| 提升前窗口门禁 | 套件 18/18 · 4×245.7K needle 4/4 · governance pin → 0.2.5 |
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

在生产构建上实测（**PR 矩阵测于 v19/0.2.5**；DE 与各侧臂仍是 v18 栈数字——下方已逐处
标注）。完整表格、逐格聚合与原始归档见
[docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)、
[`data/prv3-v19-40217prep-20260920/`](data/prv3-v19-40217prep-20260920/) 与 [`data/sd1-20260918/`](data/sd1-20260918/)。

### DE 单流 decode（4 种提示词标签，零 grammar，强制吃满）—— 测于 v18（0.2.4）栈

4 类型 × 5 并发 × 3 波；格中心值 = 全部有效流的 `statistics.median`。完整 20 格表、
总吞吐口径视图与 TTFT 见 [FINAL-METRICS §4](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)。

| 类型 | C=1 | C=2 | C=4 | C=8 | C=16 | 波次离散度 |
|---|---:|---:|---:|---:|---:|---:|
| code | **88.37** | 71.47 | 58.98 | 42.30 | 36.16 | ±3.5–±9.3% |
| json | **81.55** | 65.16 | 52.25 | 35.64 | 30.70 | ±0.4–±2.1% |
| structured | **74.40** | 51.36 | 38.81 | 28.24 | 20.23 | ±8.4–±43.5% |
| prose | **49.09** | 38.34 | 28.08 | 18.37 | 15.11 | ±0.7–±8.3% |

> **`structured` 是提示词标签，不是 grammar 约束。** `code > json > structured > prose`
> 在全部五档成立。`structured` 仍是唯一离散异常类型（±8.4–±43.5% vs 其余 ≤±9.3%），
> 成因未识别。
> **DE 总吞吐（Σ 输出 token ÷ Σ 波墙钟）峰值 543.9 t/s @ code × C16** ——
> 543.9 / 481.0 / 262.8 / 236.4（code / json / structured / prose）；对 v14 同口径
> 复算 528.5 **+2.9%**（v18 栈谱系）。

### PR 纯 prefill 总吞吐（PR-v3，40/40 格全齐）—— [FINAL-METRICS §3](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)

> 基线谱系：PR-v2 作废（2026-09-18，不刷缓存 / 非总吞吐）→ PR-v3@4096 被取代 → **v14**（chunk 8192 全量重测）→ **v18**（0.2.4，MoE W4A8-MX）→ **v19**（0.2.5，#40217 native port，**现行**）。被取代的归档保留供复核：
> [`data/sd1-20260918/pr/`](data/sd1-20260918/pr/)、[`data/prv3-20260918/`](data/prv3-20260918/)、
> [`data/prv3-v14-20260919/`](data/prv3-v14-20260919/)、[`data/prv3-v18-20260919/`](data/prv3-v18-20260919/)。
> **引用一律以下方 v19 表为准**。

PR-v3 测的是压测真正关心的量：**从放行第一流到最后一流结束的墙钟内，全部 prompt token
之和 ÷ 墙钟**；`max_new_tokens=1`（**纯 prefill，无 decode 尾巴**），每请求唯一 nonce，
每格之间 `POST /flush_cache`。

| 输入 token | C1 | C2 | C4 | C8 | C16 |
|---:|---:|---:|---:|---:|---:|
| 512 | 1,279.9 | 1,288.1 | 1,138.8 | 1,891.9 | **2,523.3** |
| 2,048 | 3,199.9 | 3,095.8 | 3,792.7 | 3,838.1 | **3,876.5** |
| 4,096 | 4,098.9 | 4,156.3 | 4,285.4 | **4,555.6** | 3,692.5 |
| 8,192 | 4,794.2 | **4,803.2** | 4,715.7 | 3,370.6 | 4,185.8 |
| 16,384 | 2,837.0 | 3,101.0 | **4,223.8** | 3,265.8 | 4,210.5 |
| 32,768 | 3,338.0 | 3,433.8 | **3,645.8** | 2,900.8 | 2,888.0 |
| 65,536 | 2,899.5 | **2,924.1** | 2,856.8 | 2,719.3 | 2,685.2 |
| 131,072 | **2,634.9** | 2,559.8 | 2,523.8 | 2,467.5 | 2,517.2 |
| 524,288（只做单流） | 2,257.2 | — | — | — | — |

**读表方式**（每格仅 1 波 ⇒ 无误差棒；只做同窗对照）：全表峰值 **4,803.2 t/s @8192×C2**（对 v18 峰 4,299.6 **+11.7%**；全表中位 **+8.1%**，40 格 31 升 9 降）。
8192 行在 C1–C4 整行抬升 **+36~+55%** —— 与 #40217 有界化的方向一致（dense indexer
瞬态在 8192 步预算满载时伤害最大）。长输入 32K–131K 收敛到 **2,467.5–3,645.8 t/s**。
诚实记录回退格（全部单波，已列 ≥2 靴补测）：512×C4 −36.6%、65536×C8 −21.7%、
16384×C2 −15.5%，另有四处小幅回落。并发判定与 v18 同型：准入律 27/40 精确、
无一格超出；真并行步 11/40 格（512 最高宽 10、2048 最高 5、4096 宽 2–3；≥8192 多流格
为串行准入——引擎策略，非客户端缺陷；逐格证据见
[data/prv3-v19-40217prep-20260920/CONCURRENCY.md](data/prv3-v19-40217prep-20260920/CONCURRENCY.md)）。

### 网关与短输出臂

| 指标 | 数值 | 说明 |
|---|---|---|
| `:8001` 网关 vs 直连 `:8899` | prefill **+0.9 %** · decode **−0.2 %** · wall **+0.3 %** | 每臂 n=2 —— 足以排除数量级差异，**不足以**排除个位数百分比差异（[§6](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)） |
| fp4 indexer，256 token 预算，`code` | C1 **88.58** · C8 44.52 · C16 36.99 t/s/流 | **只有一条臂** —— indexer 当前开启；关闭臂需要重启。**不是 A/B**（[§7](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)） |

### 头部数字

**总吞吐（引用就引这两个数）：PR 纯 prefill 总吞吐峰值 4,803.2 t/s（8192 × C2，chunk 8192，**v19/0.2.5**）· DE 聚合 decode 峰值 543.9 t/s（code，C16，v18/0.2.4 栈——v19 DE 补测未跑）。**

| 指标 | 数值 |
|---|---|
| **PR 总吞吐峰值（纯 prefill，PR-v3 @ chunk 8192，v19）** | **4,803.2 t/s**（8192 × C2）· 次高 **4,794.2 t/s**（8192 × C1）· 小提示词最佳格 **2,523.3 t/s**（512 × C16）· 8192 行 C1–C4 对 v18 **+36~+55%** |
| PR 对 v18 同窗增益（同采集器、同 chunk） | 峰值 **+11.7%** · 全表中位 **+8.1%**（31 升 9 降）· 长档（≥16K）中位 +8.1% · 单波回退最深 −36.6%（待补测） |
| PR 并发判定（v19） | 与 v18 同型：准入律 27/40 精确、无一格超出；真并行步 11/40 格（512 ≤10 · 2048 ≤5 · 4096 2–3）；≥8192 多流格为串行准入（引擎策略） |
| **DE 聚合 decode 峰值（总吞吐，v18 栈）** | **543.9 t/s**（code，C16）· 单流 C1 峰 88.37 t/s（code）—— v19 补测未跑 |
| GSM8K（200 题，v18 栈） | **0.9600**（192/200）· temp 0.6、8-shot · indexer 关 |
| 引擎冷启 | **345.7 s ≈ 5.8 min**（`tokenizer_e2e`，v18） |
| v19 提升前窗口门禁 | 套件 18/18 · 4×245.7K needle 4/4 · governance pin → 0.2.5 |

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
| `CHUNKED_PREFILL_SIZE=4096`（生产现役） | 它是 524288 token 提示词**能装下**的原因，也是长提示词 prefill **逐请求串行**的原因。**2026-09-19 的 PR 重测基准口径为 8192**（这是基准形态，不是生产变更——启动器现对 `{2048, 4096, 6144, 8192}` 做校验）；见 [benchmarks/README.md §3.2](benchmarks/README.md) 与 [FINAL-METRICS §1.4](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md) 的标注 |

**fp4 indexer（`--enable-deepseek-v4-fp4-indexer`）在形态 A 下是开启的。** 它是 env 级开关，
形态 B 则在关闭状态下运行；两者是**不同配置**，任何一行的数值都不该拿去和另一形态比。
能判定它的 A/B 需要重启，属于窗口事项
（[FINAL-METRICS §7](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)、
[§11](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)）。

**唯一保留的已知回退**：c6 聚合 260 → 236（−9 %），EP2 的副作用；c8/c12 涨幅远大于此。

---

## 4. 实验性算子优化（改了什么，以及你接受的风险）

生产构建在上游 SGLang 之上带了**三层实验内容**。全部由 env 门控或文件级 graft，
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
- **PR-v2 / PR-v3@4096 / v14 / v18 各代 PR 板**：作为审计归档保留在
  [`data/`](data/)（`sd1-20260918/pr/`、`prv3-20260918/`、`prv3-v14-20260919/`、
  `prv3-v18-20260919/`）——引用一律用本 README §2。

## 6. 仓库内容

- `start.sh / start-tp4.sh / stop.sh / boot.py` — 编排、锁修订版下载、冒烟 + 预热
- `adapter/` — SGLang 补丁（Engram 行存储 C++、MXFP8 后端、共享专家 K padding、prefill 缓存钩子）
- `sglang-overlay/` — graft 到镜像 sglang 树上的融合 DeepSeek-V4 decode 算子（上文第二层）
- `b12x-site/` — vendor 的 b12x CuTe-DSL 内核库（上文第一层）
- `gateway/` — **流式感知并发网关**（引擎前的 `:8001` 网关）：SSE 心跳、TTFT 预算、
  背压准入、等值去重、断连传播、`/gw/metrics`、可选 `enable_thinking` 注入。
  附脱敏后的 `.env.example`（13 个旋钮全部注释说明）与 systemd 单元样例；
  不含内部主机名、端口与 URL
- `scripts/` — SSH 助手、`verify/` 探针集、自愈监控 + systemd 单元、`gate.sh`、`nccl_selfcheck.sh`、
  `verify_release_artifact.py`（**离线**归档校验器：blob 完整性 + 内容身份，无需集群），
  以及三个仓库自检（`check_redaction.py`、`check_relative_links.py`、`check_report_tables.py`）
- `benchmarks/` — 产出这些表的 harness，附
  [harness → 归档映射](benchmarks/README.md)、[SD-1 口径](benchmarks/README.md)、
  [脱敏策略](benchmarks/README.md)、以及
  [§3.2 引擎 prefill 准入律](benchmarks/README.md)
- `bench/` — 门禁套件（needle / corruption / termination / code-gate）、vision 门禁、
  散文、GSM8K、第三方形状扫描、MoE 数值/容量阶梯
- `data/` — **基准原始归档**：现行权威 `data/prv3-v19-40217prep-20260920/`（PR-v3 矩阵、
  `chunk 8192`、40/40 格、含逐流原始记录）；谱系 `prv3-v18-20260919/`（上一代对照）、
  `prv3-v14-20260919/`、两份更早被取代的 PR 归档（`data/prv3-20260918/`、
  `data/sd1-20260918/pr/`）保留供复核；`data/sd1-20260918/` 下有 DE 矩阵（含逐流原始记录）、
  grammar A/B、fp4 短输出臂、网关 vs 直连、以及两次 GSM8K；另含发布件离线审计记录
  `data/release-artifact-20260918/`。
  每一个公布的数字都能由这些文件复算——[`data/README.md`](data/README.md) 说明怎么复算，
  并**点名列出唯一一个不能复算的列**
- `.env.tp4.example` — 本仓库实际运行的配置（脱敏模板；现网 `.env.tp4` 已 gitignore）
- `BUILD-IDENTITY.md` — 镜像 ID、SGLang commit、组件版本、发布件哈希，
  以及用于核对镜像的**内容身份公式**
- `docs/` — 部署方案、上游 ISSUE/PR 调研、基准横向对比、终版指标板、
  以及[版本更新报告](docs/release-notes/)和
  [算子全景清单与回退台账](docs/operators/)（§4 的证据底座）

---

## 7. 镜像下载（发布件）

服务镜像（13.5 GiB）经网盘分发：

- **百度网盘**：https://pan.baidu.com/s/1FUJUQ8ZYK5ZIsYZBK8aqkg?pwd=luzi（提取码 `luzi`）
- **文件**：`LuZ-0.2.4-dsv41-tp4-dgxspark.tar.zst`
- **大小**：14,462,447,532 字节（13.5 GiB）
- **MD5**：`9daeb2ba314a1380988ed6f8afbe4657`
- **SHA256**：`f98af3b5a40ad83150b3f0e0fd3b373fad50e34cbfbc4b7b8786324b36818a3d`
- **镜像内容身份**：`4ebef21b6aedbd70` —— 与四台生产机报出的值完全一致，且**可由发布包本身离线复现**（与 v0.2.2 时代分发的镜像内容相同；v0.2.4 文件为更名重打包——在新文件上离线重跑 `verify_release_artifact.py` 同样复现此身份）

载入之前先**离线自证**（无需集群、无需 docker 守护进程、无需 GPU）：

```bash
pip install zstandard
python scripts/verify_release_artifact.py LuZ-0.2.4-dsv41-tp4-dgxspark.tar.zst --md5
# md5 吻合 · 123/123 个 blob 的 sha256 全部自洽 · 0 个未引用 blob
# 内容身份 4ebef21b6aedbd70 · RESULT: PASS  （退出码 0）
```

然后在四机分别载入，并按内容身份自检：

```bash
docker load -i LuZ-0.2.4-dsv41-tp4-dgxspark.tar.zst   # 需要 zstd；解压为 dsv41-sglang-optimized:v7
docker image inspect -f '{{join .RootFS.Layers " "}}' dsv41-sglang-optimized:v7 \
  | sha256sum | cut -c1-16      # 期望：4ebef21b6aedbd70
```

该一行式**就是 `start.sh` 自检用的同一条公式**，所以本机算得过＝集群断言也过得。
**不要**用层数或 `docker image inspect --format '{{.Id}}'` 验收：head 报 `03587ce9…`、
worker 报 `9e1036bc…`，是因为那**是同一份归档里的两个不同对象**（OCI index blob 与
image config blob），而 123 层的内容完全相同。完整论证、**同一条层清单的五个序列化
口径**（它们哈希出五个不同值）、以及空输入陷阱（`01ba4719c80b6fe9` 表示**镜像缺失**，
不是身份）见 [BUILD-IDENTITY.md](BUILD-IDENTITY.md)。

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

仓库默认分支是 **`main`**，**适配内容就在 `main` 上**——本仓库是一份独立的工程快照，
**不是**上游项目的某个分支。上游归属见下表与 [BUILD-IDENTITY.md](BUILD-IDENTITY.md)。

| 组件 | 来源 | 许可证 |
|---|---|---|
| SGLang 配方（boot、适配器、Engram 行存储、DSpark 设置） | [`ntxf31415/DeepSeek-v4.1-Flash-DGX-Sparks`](https://github.com/ntxf31415/DeepSeek-v4.1-Flash-DGX-Sparks)（亦以 `MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks` 发布） | AGPL-3.0-or-later |
| 配方谱系 / 基准方法 | [`0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000`](https://github.com/0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000) | MIT |
| 宿主 ring-only NCCL 2.30.7 构建 + `libncclpin` 核绑定 shim（宿主侧，仓库不含） | [`luxingcom/aicad-nccl-optimization`](https://github.com/luxingcom/aicad-nccl-optimization)（LuZ 谱系） | **未声明许可证** |
| 模型权重 | `deepseek-ai/DeepSeek-V4.1-Flash`（Hugging Face） | 见模型卡 |

**姊妹项目：** [DeepSeek-V4-Flash-Vision-Exp TP4 无交换机环网](https://github.com/ntxf31415/deepseek-v4-vision-exp-dgxspark-tp4-switchless-ring)（vLLM，同一环网底座）· [GLM-5.3-Flash NVFP4 TP4 无交换机环网](https://github.com/ntxf31415/glm-5.3-flash-nvfp4-4x-dgx-spark-switchless)（同底座配方）。

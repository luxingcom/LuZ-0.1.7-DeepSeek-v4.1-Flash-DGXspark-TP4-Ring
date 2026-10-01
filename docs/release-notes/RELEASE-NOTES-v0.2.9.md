# RELEASE-NOTES-v0.2.9 · dsv41-sglang-optimized:0.2.9-ep1q2-fin2（旧基座最后稳定版）· 2026-09-30

> **一句话**：0.2.9 是「**ep1 系列**」工程代——把 MoE 的专家并行推到 `EP_SIZE=1`（**EP1 使能链**），
> 并把 P1a 三件 adapter（`draft_head_fp8_tp4` / `hc_fused` / `draft_tau`）+ memwatch + PREFLIGHT
> `v1-fin2` + 横幅 16 门一并烘进镜像。相对上一稳定版 `0.2.9-ep1q2-fin`（fin），
> **c8/c12 解码档 +4.0 %/+4.8 %**，262k/131k 预填在靴噪声带内持平，**QA 17/0 门通过**。
> 发布件 `LuZ-0.2.9-dsv41-tp4-dgxspark.tar`（14,055,778,304 B）已随包分发，
> 内容身份 **`355a5e45cb2725ae`**。
>
> ⚠️ **本文件是发布版**：与 0.2.9 发布包（`~/release/0.2.9-ep1q2-fin2/`）内的
> `docs/README-RELEASE.md`、`docs/CHANGELOG-0.2.9.md` 同源；两份内容在**脱敏口径**上不同
> （见 §7），本文件按本仓的**发布约定**重述，不复制包根视角的表格。

## 1. 构建身份

| | 值 |
|---|---|
| 镜像 | `dsv41-sglang-optimized:0.2.9-ep1q2-fin2` |
| **内容身份（验收值）** | **`355a5e45cb2725ae`** = `sha256(join RootFS.Layers " ")` 前 16 位（**5 层**；四机实测全等） |
| 基座 | `0.2.9` ep1 系列的 fin2 增量烘焙终态（`base_cid=fa825cd26bd2c1a6`，即 fin；见 §1.1） |
| 横幅门数 | **16**（`banner_gates=16`） |
| PREFLIGHT | `v1-fin2` |
| 引擎血统 | sglang `da64c5cbb`（dsv41-tp8-hopper-decode 线）+ b12x `1.3.0` + 本仓 overlay/adapter |
| 发布 tar | `LuZ-0.2.9-dsv41-tp4-dgxspark.tar` · **14,055,778,304 B**（13.09 GiB） |
| tar SHA256 | `c1840255408f8b8b012279153580d1310f5d7d9bc4f5aa4e4181bcc8bf23fb0d` |
| tar MD5 | `3562a789ec0e9aa4bc80a7e54ba1be65` |
| 镜像身份 JSON | [`data/release-artifact-20260930/IMAGE-IDENTITY.txt`](../../data/release-artifact-20260930/IMAGE-IDENTITY.txt) |
| 镜像内 adapter 清单 | [`data/release-artifact-20260930/ADAPTER-MANIFEST.txt`](../../data/release-artifact-20260930/ADAPTER-MANIFEST.txt)（29 件） |

### 1.1 谱系

```
0.2.8（生产定板，内容身份 4cca364c46778423，3 层）
  → 0.2.9 基线                adaf7f24f67434f3
  → ep1q2                     22422fa3cd120d57   SPARK_PREFILL_TP_SPLIT 转正（PR +5~12%）
  → ep1q2-fin                 fa825cd26bd2c1a6   部署门禁层镜像（fin2 的直接父）
  → ep1q2-fin2（本发布）      355a5e45cb2725ae   P1a 三件 adapter + memwatch + PREFLIGHT v1-fin2 + 横幅 16 门
```

**认证载体**：镜像链以 `content_id` 血统表 + `image-patches/0.2.9/` 构建上下文认证；
git 提交承载部署面（`start.sh` / env / gates / preflight）与主干工程。ep1 系列各代窗口报告
见 [`RESEARCH-INDEX.md`](../RESEARCH-INDEX.md)。

> **口径注意**：`355a5e45cb2725ae` 是 `{{join .RootFS.Layers " "}}` 接 `sha256sum` 前 16 位，
> 与 `start.sh` 预检同口径。**不要**用层数之外的元数据判跨机等价——理由与七种序列化写法
> 见 [`BUILD-IDENTITY.md`](../../BUILD-IDENTITY.md)。

## 2. 改动内容

### 2.1 EP1 使能链（本版核心）

0.2.9 的工程代名 `ep1` 即指 **MoE 专家并行降到 1**。生产 env 实测的对应键：

| 键 | 0.2.8 定板 | **0.2.9-ep1q2-fin2** | 位置 |
|---|---|---|---|
| `EP_SIZE` | `2` | **`1`** | 顶层键 |
| `DSV41_MOE_B12X` | `1` | **`0`** | `EXTRA_DOCKER_ENV` 子键 |

同批新增的 28 个 `EXTRA_DOCKER_ENV` 子键与 1 个顶层键见 §3。

### 2.2 P1a 三件 adapter（本版性能来源）

`identity/ADAPTER-MANIFEST.txt` 所列 `/opt/dsv41/adapter` 29 件中的三件，是 §4 性能数字的直接来源：

| adapter | 兑现证据 |
|---|---|
| `draft_head_fp8_tp4` | c8/c12 双靴双兑现（四键臂 24.37/21.35 + 确认靴 24.95/21.45）；c1 持平微升 |
| `hc_fused` | **位等四证**（113 行数 GPU 位等 ×2 + 两靴引擎首调 1071 行逐位同）；kernel census 净省 **915 ms/32 步窗** = 28.6 ms/chunk |
| `draft_tau` | τ=0.8 判负 ⇒ **不设**（见 §6 负结论） |

### 2.3 其余烘入件

memwatch、PREFLIGHT `v1-fin2`、横幅 16 门（`banner_gates=16`）。

### 2.4 与上一稳定版的对照

本版性能只与 **fin**（`ep1q2-fin`，`base_cid=fa825cd26bd2c1a6`）并列；**不**与 0.2.8 的
PR 40 格矩阵互引——那是**另一基座**（45 层次 KC 与 EP2 形态），两套数字不可换。

## 3. 配置面变更（逐键，实测 diff）

两侧各按 `^[A-Za-z_][A-Za-z0-9_]*=` 提取后机械比对（复算命令见 §3.3）。

### 3.1 顶层键

| 键 | 0.2.8 模板 | 0.2.9 生产 | 性质 |
|---|---|---|---|
| `IMAGE` | `dsv41-sglang-optimized:0.2.8` | **`0.2.9-ep1q2-fin2`** | 代际推进 |
| `EP_SIZE` | `2` | **`1`** | **EP1 使能链**（§2.1） |
| `CTN_MEMORY` | （模板无此键） | **`32g`** | **新增**；见下 |

**`CTN_MEMORY=32g` 的来路与风险（不要照抄）**：`start.sh` 的容器内存帽默认值是 `24g`
（`--memory ${CTN_MEMORY:-24g}`，两处）；0.2.9 生产按 2026-09-28 裁定放宽到 `32g`，
理由是武装探针的 flush 峰达 21.7 G 以上。**这是与站点负载有关的放宽，不是优化**：
`24g` 这道闸压住的是**可回收页缓存**而非 anon（0.2.8 期实测四机 `memory.peak` 顶在上限、
`oom_kill` 四机全 0、anon 峰距上限还有 13 GiB，见 [`CONFIG-v0.2.8-ENV.md`](../CONFIG-v0.2.8-ENV.md)）。
⇒ **模板保持 `24g` 默认**；要放宽请先确认你自己的宿主水位。

### 3.2 `EXTRA_DOCKER_ENV` 子键

**改值 2 项**：

| 子键 | 0.2.8 | 0.2.9 | 备注 |
|---|---|---|---|
| `DSV41_MOE_B12X` | `1` | **`0`** | EP1 使能链（§2.1） |
| `DSV41_DENSE_INDEXER_LOGITS_BUDGET_BYTES` | `134217728` | **`536870912`** | 回到 512 MiB 档 |

**新增 28 项**（0.2.9 生产已在用，0.2.8 模板没有）：
`B12X_ROCE_HCA` · `B12X_ROCE_PEER_HCA_MAPS` · `B12X_ROCE_TWO_WAVE_THRESHOLD_BYTES` ·
`DSV41_DRAFT_HEAD_FP8` · `DSV41_DRAFT_HEAD_FP8_IMPL` · `DSV41_DRAFT_MAIN_PROJ_SPLIT` ·
`DSV41_EAGER_GLUE` · `DSV41_ENGRAM_PREFETCH` · `DSV41_FOLDED_FENCE` · `DSV41_HC_FUSED` ·
`DSV41_L2_PREFETCH` · `DSV41_LAUNCHER` · `DSV41_LOOP_ABORT` · `DSV41_MOE_B12X_NEXT` ·
`DSV41_MOE_B12X_NEXT_DETERMINISTIC` · `DSV41_REPLICATED_SPLIT` · `DSV41_ROCE_GATHER` ·
`DSV41_ROCE_RING` · `DSV41_ROUTER_LIVE` · `DSV41_SPARK_PREFILL_TP_SPLIT` ·
`DSV41_SPEC_SYNC_FREE` · `DSV41_VERIFY_CAP` · `DSV41_VERIFY_PRUNE` · `DSV41_VERIFY_PRUNE_LOG` ·
`DSV41_WO_A_W8` · `DSV41_WO_A_W8_DROP` · `DSV41_WO_A_W8_MID` · `SGLANG_ROCE_ALLREDUCE` ·
`SGLANG_ROCE_MAX_SIZE`

其中 `B12X_ROCE_PEER_HCA_MAPS` 是**布线指纹的第二种编码**——它与 `PEER_HCA_RANK*` 表达同一张
物理接线图（详见 §7）。

### 3.3 `EXTRA_SGLANG_ARGS` flag

| 变化 | flag |
|---|---|
| **新增** | `--enable-encoder-swa-bounded-replay` |
| **移除** | `--enable-mixed-chunk` |

> ⚠️ **两处一致性提醒**：
> 1. 改这些键**只能改 `EXTRA_DOCKER_ENV` / `EXTRA_SGLANG_ARGS` 这一行**。写成顶层独立行
>    **不会进容器**（`start.sh` 只透传白名单顶层变量，其余静默丢弃、仅打一行 `warn`）。
> 2. 本仓 `.env.tp4.example` 是**公开模板**，其职责是「忠实记录生产键集」并标注站点占位符。
>    **2026-10-01 已同步**：本模板现为 **0.2.9 键集 + `IMAGE=0.2.9-ep1q2-fin2`**，照它起栈
>    得到的即本版形态（`EP_SIZE=1`、`EXTRA_DOCKER_ENV` 61 子键、`B12X_ROCE_PEER_HCA_MAPS`
>    以 `<PINNING>` 占位）。同步由生成器完成而非手抄——布线指纹有两个编码，手抄是它再次
>    泄漏的路径（见 §7.2）。模板此前停在 0.2.8 键集，是对「是否公开一份 EP1 生产配置」的
>    悬置；该悬置已随本版解除。
>    `CTN_MEMORY` 是**唯一有意不同步**的键：生产放宽到 `32g` 属站点负载相关调整，
>    模板保持 `start.sh` 的 `24g` 默认并注记原因（见 §3.1）。

## 4. 性能定板

对照锚 = 上一稳定版 `ep1q2-fin`（同硬件同口径）。量具 = sparkDash 三件套
（`bench/sd_bench.py` DE、`bench/wpr1-kit/pr_prefill_probe.py` PR、`bench/gates_suite.py` QA17）。
**先读 [`PERFORMANCE-SUMMARY-0.2.9.md`](../03-final-metrics/PERFORMANCE-SUMMARY-0.2.9.md)**——
那里每个数字都带「哪一靴 / 哪个窗口」。

| 指标（窗口 + 口径） | fin 基线 | **fin2（本版）** | 变化 |
|---|---|---|---|
| PR 262k（repeated，墙钟） | 160.0 s | **160.7 / 161.6 s**（两靴） | 带内持平（±3 % 靴噪声内） |
| PR 131k（repeated，墙钟） | 76.5 s | **77.5 / 77.5 s**（两靴同值） | −1.3 %，带内 |
| DE prose c1（tok/s） | 70.42 / 71.20 | **69.95 / 70.47** | 持平微升（τ 移除后） |
| DE prose c8（tok/s） | 23.98 | **24.95** | **+4.0 %** |
| DE prose c12（tok/s） | 20.46 | **21.45** | **+4.8 %** |
| QA | 17/0 | **17/0** | 门 |

**沿用而非重测的锚**（写明以免误引）：PR 32768 / 4096 与 DE code c1（113.49 / 116.01）
**沿用 fin 锚，本版未重测**。⇒ **`71.20` / `160.0` / `76.5` 是 fin 列的数，不是 fin2**，
引用本版时不要混用。

**稳定性记录**：确认窗 + 复证窗全程**无守卫止损触发**（唯一一次 oom-gate 止损系测试协议
违纪所致，非镜像缺陷）。内存形态：boot 基线 ~17.8 G `MemAvailable`；262k PR 后 ~10 G
= 引擎合法驻留；memcg 32 G 下稳态 ~12.75 GiB。

## 5. 发布件（release artifact）

| | 值 |
|---|---|
| 文件 | `LuZ-0.2.9-dsv41-tp4-dgxspark.tar`（**未压缩 OCI tar**） |
| 大小 | **14,055,778,304 字节**（13.09 GiB） |
| SHA256 | `c1840255408f8b8b012279153580d1310f5d7d9bc4f5aa4e4181bcc8bf23fb0d` |
| MD5 | `3562a789ec0e9aa4bc80a7e54ba1be65` |
| 内容身份 | **`355a5e45cb2725ae`**（5 层，四机一致） |
| 下载 | 见 [README §7](../../README.md#7-image-download-release-artifact)（双网盘通道） |
| 归档落点 | [`data/release-artifact-20260930/`](../../data/release-artifact-20260930/) |
| 镜像内 sha256 | [`…/dsv41-sglang-optimized_0.2.9-ep1q2-fin2.tar.sha256`](../../data/release-artifact-20260930/dsv41-sglang-optimized_0.2.9-ep1q2-fin2.tar.sha256) |

**四机分发校验**（部署后、压测前必跑；随本版首次发布，源码在
[`scripts/verify_fleet_distribution.sh`](../../scripts/verify_fleet_distribution.sh)）：

```bash
./scripts/verify_fleet_distribution.sh \
  --image dsv41-sglang-optimized:0.2.9-ep1q2-fin2 \
  --identity 355a5e45cb2725ae --expect-layer-count 5 \
  --nodes <head-node> <worker-rank1> <worker-rank2> <worker-rank3>
# → 四机 identity 一致 + 跨机一致 ⇒ RESULT: PASS (exit 0)
```

该脚本的判据是**存在性前置 + 空哈希双拦**：镜像缺失时
`docker image inspect … | sha256sum` 会产出**看似合法的常量**
（`e3b0c442…` = `sha256("")`、`01ba4719…` = `sha256("\n")`）；两台机同缺 ⇒ **假绿**。
故存在性必须先判、identity 永不从缺失镜像算。

> ⚠️ **相邻版本的发布件尺寸几乎不可分辨**（0.2.8 与 0.2.4 仅差 +0.0043 %；0.2.8 → 0.2.9
> 差 +0.38 %，同样不足以凭肉眼）⇒ **取用必核哈希，禁凭大小或文件名判版本。**

### 5.1 发布数字自审（`scripts/audit_release_claims.py`）

包内每一处计数、体积、哈希断言都应由脚本产出而非手打：**手打的数字是没人验证过的数字**。
该脚本把这轮发现的 7 类缺陷固化成 fail-closed 守卫，**事实全部取自 git**、永不取自它正在检查的文档：

```bash
# 正确用法：--bundle 指向 0.2.9 发布包内的历史 bundle，--pkg 指向 0.2.9 包根
python3 scripts/audit_release_claims.py --bundle deploy/git-history-v0.2.9-fin2.bundle \
                                        --pkg    <0.2.9 包根>        # 15 项 → RESULT: ALL PASS
```

它先做**作用域守卫**，且该守卫**区分三种状态**（把三者都说成「浅克隆」会把读者引向一个
修不好另两种的处方）：

| 状态 | 判据 | 诊断 |
|---|---|---|
| 基线提交**根本不存在** | `3959f739` 不可解析 | `FAIL/WRONG-TARGET` —— 这是**另一个仓库**，不是浅克隆 |
| **真浅克隆** | `.git/shallow` 存在＋父不可达 | `FAIL/GUARD`（浅克隆），处方 `git fetch --unshallow` |
| **其它截断** | `.git/shallow` 缺席但父不可达 | `FAIL/GUARD`（graft / promisor / 手工过滤） |

三态都**非零退出**。之所以要分开：父提交不可达会让后面每个计数变成「下界冒充总数」，且由浅
克隆导出的 bundle **无法被克隆**（而 `git bundle verify` 仍报告「完整历史」）。**bundle 的验收
判据是「能在空目录克隆成功」，不是 `verify` 的输出。**

> ⚠️ **本仓不是该脚本的审计对象。** `--bundle` 要的是一份 **0.2.9 部署历史 bundle**，而该
> bundle **不属于本仓的发布件**（见 §6「有意不随本仓分发」）。本仓收录该脚本，是为了让**拿到
> 0.2.9 发布包的人**能在自己那侧复算。在本仓内直接：
>
> - `--repo .` ⇒ `FAIL/WRONG-TARGET`（基线提交在本仓不存在，**不是浅克隆**）
> - `--pkg` 忘了指向 0.2.9 包根 ⇒ `FAIL: package is missing a required file`
>
> 两者都**不会**静默给出一个「看着合理」的数字——这正是它们存在的意义。

## 6. 诚实声明（开源发布必读）

1. **本仓不包含 0.2.9 的 git 历史 bundle，也不包含 tar 快照。** 0.2.9 的部署历史
   （`deploy/git-history-v0.2.9-fin2.bundle`，可达 86 提交）与其树快照
   （`deploy/repo-snapshot-…tar.gz`，1220 文件）**随发布包（网盘）分发，不入本仓**。
   理由有二：(a) 本仓是**独立工程快照**（root `27cd03a`），与部署仓不是同一条历史；
   (b) 那份历史内含**只应在发布包语境下出现的内部面**，见 §7。
2. **`.env.tp4`（生产）不公开**；公开的是模板 `.env.tp4.example` + 本文对照表。
   0.2.9 的脱敏 env 副本（`env/.env.tp4.fin2-c4f13f93`）**在发布包内但不在本仓**——
   本仓自己的 `.gitignore` 规则 `.env.tp4.*` 会**静默忽略**它（`git check-ignore` 退出码 0），
   且它承载的是**生产值集合**。模板已足够起栈。
3. **ep1 镜像链（09-25~29，ep1c→ep1q2-fin2）未逐件产生 git 提交**——该时代以
   「镜像 + `image-patches` 构建上下文 + 窗口报告」三件套认证，全部材料在 v0.2.9-fin2 树
   与 [`RESEARCH-INDEX.md`](../RESEARCH-INDEX.md) 指向的归档中。
4. **0.2.9 之后的新基座开发不在本发布范围**：LuZ-0.3.0（= 上游 main-`79cafec0` + L10 修复合集）
   在独立战役仓进行，其与 0.2.9 的对照见归档 101/102。
5. **本版把 0.2.9 的性能数字与 0.2.8 的矩阵分开陈述**，且**不提供跨基座归一表**——
   两个基座的层数、EP 形态、chunk 档都不同，任何「归一」都会引入口径切换
   （本项目的历史教训：相邻句换基准 = 隐性口径切换）。

## 7. 脱敏说明（publish note）

本仓（发布版）相对 0.2.9 内部产物，仅做以下处置，**未改任何数值、结论或因果表述**：

| # | 对象 | 处置 | 依据 |
|---|---|---|---|
| 1 | 内部主机名列表（`docs/README-RELEASE.md`、`scripts/verify_fleet_distribution.sh`） | → `<head-node> <worker-rank1> <worker-rank2> <worker-rank3>` | 本仓既有约定（`docs/operators/AUTOTUNE-GOLDEN-RUNBOOK.md`、`scripts/gate.sh` 同用） |
| 2 | `PEER_HCA_RANK0..3` 的值 | → `<PINNING>` | 本仓既有约定（`.env.tp4.example` 早在 0.2.8 即如此） |
| 3 | **`B12X_ROCE_PEER_HCA_MAPS` 的值** | → `<PINNING>` | **本版新增的 blocker 类**，见下 |
| 4 | 构建机私有顶层目录（4 项） | → `<archive-root>/`、`<handover-root>/`、`<luZ030-campaign-checkout>`、`<release-pack-root>/` | 该布局只存在于我方构建机，读者无从对照 |
| 5 | 生产 env 副本、包根视角的 `docs/README-RELEASE.md` | **不随本仓分发** | 见 §6.1 / §6.2 |

**保留不动的（有意）**：`~/dsv41-flash-dgxsparks`、`~/w6-kit`、`/data/models/…`、
`/opt/b12x`、`/opt/dsv41`、`/opt/nccl-ringonly` —— 这些**本仓早已作为自身约定公开**
（`README.md` / `BUILD-IDENTITY.md` / `.env.tp4.example` / `scripts/gate.sh` / 运算符手册均用），
不属于新增暴露面。

### 7.1 为什么没有「映射表」（旧值 → 新值）

**给脱敏表提供旁表等于没有脱敏。** 对第 2、3 项而言，被掩掉的正是**物理环网接线图**
——它是整套配置里唯一「公开即失效」的量。发布一张「原值 → `<PINNING>`」的对照表，
就是把 `PEER_HCA_RANK*` 的原值印在 `<PINNING>` 旁边。因此本版**只给新值（`<PINNING>`）**
并说明推导方式，**不给映射表**。要自己的映射，请从一次 `NCCL_DEBUG=INFO` 首靴读
`NET/IB/<idx>=<hca>` 再翻译成对端 rank 编号，并用 `./start-tp4.sh ncclcheck` 验证；
模板注释里写着同样的三步。

### 7.2 本版修的一个脱敏缺陷：同一指纹的第二种编码

**这是本版最值得记住的一条。** 本仓检查器 `scripts/check_redaction.py` 的类
`peer-hca-pinning-map` 长期把 `PEER_HCA_RANK<n>` **掩码**而非分类，理由写得很清楚：
这张图**就是**物理接线。但 0.2.9 的包另有一对键：

```
B12X_ROCE_HCA=<name0>,<name1>,<name2>,<name3>        ← 索引序
B12X_ROCE_PEER_HCA_MAPS=<peer>=<idx>/<idx>,...       ← 同一张图，写成索引
```

把后者用前者的索引序解码后，**被掩码的 12 条 `PEER_HCA_RANK` 值逐条逐位全部可还原**，
且后者还**多带 4 条** peer 条目。⇒ **只掩码一种拼法是表面功夫**：这个类在一种拼法上被掩掉，
在另一种拼法上原样发布。

修法（本版已落地）：检查器新增 blocker 类 `b12x-peer-hca-map`，并加自测
（**19 → 22 例**）。lesson 记在检查器 docstring 里：
**「a class is not a value, it is every encoding of that value.」**（一个类不是某个值，
而是该值的**全部编码**。）

### 7.3 已登记、未在本版闭合的一项

0.2.9 的 git bundle 内有三段**不属于文件树**的载体携带内部面：annotated tag 的消息、
一条提交的消息、以及若干提交的 author/committer 身份。**文件树扫描与 `git grep`
结构性看不见它们**——后者只走工作树。这是本版发现的一条发布面盲区，
其处置（重写这些载体 / 只发快照不发历史 / 接受并登记）**属发布决策，尚未裁定**。
本仓因此**不随本仓分发该 bundle**（§6.1），该决策不影响本仓内容。

## 8. 与本文档相关

| 想知道 | 去哪 |
|---|---|
| 本版性能与 QA 锚点（逐靴逐窗口） | [`PERFORMANCE-SUMMARY-0.2.9.md`](../03-final-metrics/PERFORMANCE-SUMMARY-0.2.9.md) |
| 0.2.9 本仓工程线 58 提交全列 + 镜像血统表 | [`CHANGELOG-0.2.9.md`](../CHANGELOG-0.2.9.md) |
| 研究归档总索引（118 件 + 34 窗口） | [`RESEARCH-INDEX.md`](../RESEARCH-INDEX.md) |
| 第三方组件许可与归属（正式清单） | [`THIRD-PARTY-NOTICES.md`](../../THIRD-PARTY-NOTICES.md) |
| 镜像下载与离线校验 | [README §7](../../README.md#7-image-download-release-artifact) |
| 0.2.8 的部署配置逐键对照（0.2.8 基线键集） | [`CONFIG-v0.2.8-ENV.md`](../CONFIG-v0.2.8-ENV.md) |
| 历史重写的机械判据与先例 | [`HISTORY-REWRITE-2026-09-24.md`](../HISTORY-REWRITE-2026-09-24.md) |

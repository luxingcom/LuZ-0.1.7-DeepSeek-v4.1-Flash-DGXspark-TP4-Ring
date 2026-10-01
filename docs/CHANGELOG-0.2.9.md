# 0.2.9 系列变更日志（旧基座最后稳定版 = 0.2.9-ep1q2-fin2）

- **git 锚**：tag `v0.2.9-fin2` @ `598616c3`（含全量部署物料）。**提交计数有三个不同的口径，互不可换**：本仓自有的 LuZ 工程线 **58** 条（`3959f739..HEAD`，含 `3959f739`）；其下**继承自上游的祖先 26 条**；`HEAD` 的**完整血缘 84 条**。附录逐条枚举的是**我们这条线**的 58 条，不是 84 条 —— 见下方「计数口径」。
- **bundle 口径**：`deploy/git-history-v0.2.9-fin2.bundle` 含 8 个 ref（2 分支 + 6 tag），可达提交 **86** 条（= 84 条完整血缘 ∪ 旁支 `v40exp-20260928` 的 2 条独占提交）。
- **镜像锚**：`dsv41-sglang-optimized:0.2.9-ep1q2-fin2`，content_id **355a5e45cb2725ae**（四机对齐复算吻合）
- **env 锚**：`.env.tp4` md5 `c4f13f93`（发布包内 `env/.env.tp4.fin2-c4f13f93` 已脱敏 API_KEY）
- **引擎血统**：sglang da64c5cbb（dsv41-tp8-hopper-decode 线）+ b12x + 本仓 overlay/adapter

## 一、版本语义与认证方式

0.2.9 是"ep1 系列"工程代：以 0.2.9 基线镜像为底、经 ep1c→…→ep1q2→ep1q2-fin→ep1q2-fin2 的增量烘焙链演进。**镜像链的认证载体是 content_id 血统表+image-patches 构建上下文（已全部入库于 52e8c7b 树内 `image-patches/0.2.9/`），git 提交承载部署面（start/env/gates/preflight）与主干工程**。ep1 系列各代窗口报告见研究索引（R1/R2 与 window-* 目录）。

### 镜像血统表（content_id）
| 代 | content_id | 要点 |
|---|---|---|
| 0.2.8 | 4cca364c46778423 | 生产定板（ctx600k+四键） |
| 0.2.9 基线 | adaf7f24f67434f3 | |
| ep1q2 | 22422fa3cd120d57 | SPARK_PREFILL_TP_SPLIT 转正（PR +5~12%） |
| ep1q2-fin | fa825cd26bd2c1a6 | 部署门禁层镜像（fin2 的直接父） |
| **ep1q2-fin2** | **355a5e45cb2725ae** | **本发布**：P1a 三件 adapter（draft_head_fp8_tp4/hc_fused/draft_tau）+memwatch 烘入+PREFLIGHT v1-fin2+横幅 16 门 |

## 二、按时代的提交脉络（**我们这条线**的 58 提交全列见附录）

> **计数口径（本节数字由脚本产出，非手写）**：六个时代的提交数之和 = **58**，与附录 58 条、与 `git log --count HEAD` = 58 三者相等。划分按**主题**而非纯日期——时代⑤（0.2.8pre 冻结/可复现构建）与时代⑥（#40352 回移）**同在 09-23**，故单靠日期直方图无法分离；脚本按 `(日期, 主题)` 归类，并断言归类是 58 条的**完全且不重叠划分**（无未归类、无重复、总数相等，fail-closed）。

**① LuZ 起源（09-13~09-17，4 提交）**：环网 NCCL 姓氏归属（3959f73）；LuZ-0.1.7-DSV41F 600K 上下文投产+S 系治理收口（3ec66cd）；gsm8k 路径通用化为公开发布做准备（536f7c5）；600K 生产定板文档（c34d4da）。

**② R 轮工程（09-19，11 提交）**：b12x E4M3 subnormal 反移植+MXFP8 边界（977f022）；单驻留原始 scale 快照回收 ~4.3GiB/rank（07d7d9c）；调度器每请求 prefill 份额帽（cd17bee，源自上游 #34554）；autotune 多数表决修慢靴（8f9c67a）；RoCEnante one-shot AR/AG（2cc7d4e）；chunk 三态开关+NCCL lint（19b42f8）；v0.2.5 发布晋级（1bdde97）等。

**③ 0.2.7 定版与事故修复（09-20~09-21，10 提交）**：H 车道防静默五件（d6691a5/8ec0af4）；F1-F6 运维件（ce9a261）；冻结连环事故后的诚实包络（ctx 封顶 147456、ec=0 卸载，9963fa4）；检测层（golden 锁+六层门+PD 时钟楔死防御，f1b4e66）；5 代理加固关 13 个 fail-open（db7236f）。

**④ 加固与观测（09-22，16 提交）**：worker overlay split-brain 修复+熔断（551db01/98dd023）；FIX-B idle-release 键名定谳（94e2415）；FIX-D dense indexer 宽度分桶（4843f11，绞死病源头治理）；SIGUSR1 内存快照钩子（7ef9e3f）；「意图==实效」断言（598ffdd）；indexer K 回读 3D 视图 361→53MiB（3e99294）；mm 禁集五断言（53f8712）等。

**⑤ 0.2.8pre 冻结+可复现构建（09-23，11 提交）**：ctx600k 谱系入库（cbfbd04）；载荷完整性断言两坑修复（02dedb6）；冷构建零写入只读 AST 门（7f60416）；context 一次性目录（c4620da）；身份重钉与口径两坑（d09c14d）等。

**⑥ #40352 回移与收尾（09-23~09-30，6 提交）**：候选块选择拆 ids/展开两步（b5ddb40）；协议层块 id 表落地（63c631b，73.2× 实测）；空发布项 dtype 修复（2786431）；账本未绑定 bug+判别器（517aca8）；**52e8c7b pre-W1 冻结快照**（把 ep1/fin 时代工作树的 75 个未提交文件整体入库=本 tag 的直接内容）；**598616c3 清掉两个 shell 重定向伪影并对该类加 ignore**（本 tag 的落点）。

> **证据边界（必读）**：本节六个提交**全部在 tag `v0.2.9-fin2` 的血缘内**（脚本比对：附录 58 条与 `git log HEAD` 58 条互为子集，无差集）。另有两个 V4.0exp 视觉臂提交 `d78b9d5` / `22fd5ca`（09-28，`feat(v40exp): …`）**不在这条血缘上**——它们位于分支 `v40exp-20260928`（该分支随 bundle 一并分发，`git rev-list --all` 共 60 提交，比血缘多这 2 条）。**引用它们时不可当作本 tag 的内容**：本发布含的是旧基座稳定版，V4.0exp 视觉臂未烘入 `0.2.9-ep1q2-fin2` 镜像。

## 三、诚实声明（开源发布必读）

1. **ep1 镜像链（09-25~29，ep1c→ep1q2-fin2）未逐件产生 git 提交**——该时代以"镜像+image-patches 构建上下文+窗口报告"三件套认证，全部材料已包含在 v0.2.9-fin2 树与本研究索引指向的归档中；git 的连续提交密度在 09-24 至 09-28 间由 V40exp/#40352 线与最终冻结快照补齐。
2. `.env.tp4` 含运行时 API_KEY，不入库（.gitignore）；发布包 env/ 提供脱敏副本。
3. 0.2.9-ep1q2-fin2 之后的新基座开发（LuZ-0.3.0=main-79cafec0 线）在独立战役仓 `<luZ030-campaign-checkout>` 进行，不在本发布范围。

## 附录：本仓 LuZ 工程线 58 提交全列（`git log --format='%h|%ad|%s' 3959f739..HEAD`，含 `3959f739`）

```
598616c|09-30|fix(hygiene): drop the two shell-redirect artifacts, and ignore the class
52e8c7b|09-30|pre-W1 snapshot: 75 dirty files frozen (boot/bench/overlay 工作区)
517aca8|09-23|fix(dsv4): 协议分支账本未绑定 bug + definite-assignment 判别器（窗口 D2 实测）
2786431|09-23|fix(dsv4): 空发布项随发布形态定 dtype —— bool [0,0] 混进 int32 块 id 表
63c631b|09-23|feat(dsv4): #40352 语义级回移落地 —— 候选协议层（块 id 表）+ 三文件迁移 + 命门修复
b5ddb40|09-23|feat(indexer): #40352 语义级回移第一刀 —— 候选块选择拆成 ids 与展开两步（旧函数保留为薄包装；CPU 等价门 10 用例+危险格 PASS，未烘入任何镜像）
d09c14d|09-23|docs(identity): 0.2.8pre 身份重钉 b177409e539ea38e —— 复现验证用同名 FORCE=1；补 "TAG 烘进内容" 与 "config 含墙钟 ⇒ .Id 不可复现" 两坑
c4620da|09-23|fix(build): context 改一次性目录 —— 归一化 mtime 反噬 BuildKit 本地源过期检测
7f60416|09-23|fix(build): 让冷构建真正可复现（RUN 改为零写入的只读 AST 语法门）
02dedb6|09-23|fix(build): 载荷完整性断言①的两个实测坑（comm locale / MD5SUMS 自引用）
9c29ef5|09-23|docs: QA 修复轮（AUTOTUNE 口径分叉 / 镜像身份钉版 / 引用换行名锚点）
b3dc42f|09-23|fix(start.sh): 重复目标键与"只挂到一半"从静默变出声
21ecf59|09-23|chore(payload): 0.2.8pre 载荷源与构建器入库（含 QA 修复）
b805657|09-23|docs(version): luz0.2.8pre 冻结口径校准（BUILD-IDENTITY/README/RUNBOOK）
74d6176|09-23|fix(boot.py): 仓库根同步为镜像内的 H4 warmup.json 版（反向漂移）
cbfbd04|09-23|feat(overlay): ctx600k 谱系入库 —— 0.2.8pre 的修复源（此前仅存在于工作树）
2891241|09-23|fix(start.sh,.env.tp4.example): 默认镜像 0.2.4/v7 → 0.2.7（裸跑静默拿远古镜像的陷阱）
53f8712|09-22|guard(gate): mm 禁集生效性五断言 + 形态真身解析（原 overlay 块是死代码）
c7d1239|09-22|fix(start.sh P0): engine_env_assert 归一化 CR —— PTY 回传 CRLF 导致真起栈被自己的断言拦下
82e6073|09-22|obs(indexer mask_b): 无界路径出声（首次+每 1.5× 记峰值）
3e99294|09-22|perf(indexer K readback): 3D 页内视图取数，单次调用瞬态 361→53 MiB（n=600k）
598ffdd|09-22|feat(start.sh 客户坑9 同族): 引擎门控键 lint + 起栈后「意图==实效」断言
2597c2c|09-22|fix(QA): gate overlay-md5 断言补 ROOT 定义（F-1 死代码）+ ctx600k 两件入库（F-2 溯源链）
dfdeabd|09-22|feat(gate P1-1 收尾): overlay 容器内 md5 断言——内容级跨 rank 一致性
9410fb6|09-22|fix(审计 P2 批): FIX-D log-once+不变式注释+成本注释精确化；start.sh local/空格断言/dup-key 告警
44b8bc2|09-22|fix(FIX-B P2 批): 审计四条加固——护栏①内在化/旋钮解析一次钳位/铁令台账措辞/失败退避
a9ace1a|09-22|docs(注释定稿): FIX-D 宽度不变式 + FIX-B 铁令例外三重护栏
f910e83|09-22|fix(P1-1): worker overlay 熔断升级为精确计数等值——head 预期挂载数 vs worker 实挂数
4843f11|09-22|feat(FIX-D): dense indexer logits 宽度分桶钉尺寸——绞死病源头治理（#57105 药方变体）
94e2415|09-22|fix(FIX-B v2): idle-release 键名定谳——torch 扁平键带 .current 后缀，v1 .get 恒 0 永不 fire
551db01|09-22|fix(worker-overlay): 修复 9/21 版 worker overlay 挂载引号 bug + split-brain 熔断
7ef9e3f|09-22|diag overlay: SIGUSR1 memory-snapshot hook + idle-release FIX-B (env-gated DSV41_IDLE_RELEASE); FIX-A max_split_size_mb=256 REVERTED after A/B (64K nonce ate 6.7G -> oom_gate floor kill; split-forbid makes interleaved allocs open fresh segments)
98dd023|09-22|healthcheck lite: SGLANG_ENABLE_HEALTH_ENDPOINT_GENERATION=0 in env files (fix 30s real-generation probe stranding memory); start.sh CTX600K overlay map (R1/R2) + worker overlay dir fix (split-brain); overlay.dir ctx600k staging
db7236f|09-21|hardening pass (5-agent audit): close 13 fail-open paths, env-shadow guard, probe timeouts
f1b4e66|09-21|0.2.7 detection layer: golden cache lock + 6-layer gates + PD clock-wedge defense + canary final (PRv3-native) + SPF arm NO-GO
9963fa4|09-21|0.2.7 final form after freeze incidents: ctx 600000->147456 (honest envelope cap, >128K structurally 400-rejected), ec=0 (hook uninstall; empty_cache under overlap+UM contention proved unsafe: 3 failure modes evidenced), gate needle watchdog + memory pre-gate, start.sh ENV_FILE divergence warning; dev adapter experiment reverted
a4ab407|09-21|0.2.7 image batch: #39482 SM121 packed-scale + #40024 shortest-prefill-first port + ec default 0 + warmup.json + tools baked
6c43a23|09-21|bench: t7a channel-diff tool (chat vs native, flush-race tolerant); window V4B artifacts
8ec0af4|09-20|fix(H7): drop stray line-continuation after worker_env_lines subst
d6691a5|09-20|batch-7 H-lane: anti-silent-failure mechanisms (H4/H7/H8/H9/H10)
ce9a261|09-20|ops(F1-F6): warmup 8192-tier / status weights per-rank / gate IB dynamic+NV_ERR / CODE_VOL guard / DE segment tool
1bdde97|09-20|release(v0.2.5): promote 40217prep after full window gates
35b792e|09-20|prep(round-20260920): #40217 minimal native port + engram stats v2 + bake-off harnesses
b0fdac6|09-19|fix(moe): W4A8 default + safe hybrid fallback gating
17453f1|09-19|fix(function-call): port vLLM #52645 truncation semantics to DSML detector
a2c2086|09-19|audit: customer pitfall report P2 fixes + IMAGE tag alignment
d690812|09-19|chore: exclude bench-results/ runtime artifacts from git
2cc7d4e|09-19|feat(roce): RoCEnante one-shot allreduce/allgather (b12x comm.roce)
2fa1462|09-19|fix(bench): gsm8k DATA path parameterized (sanitize blocker) + gate.sh layout-aware suite staging
19b42f8|09-19|feat(launcher): chunk 3-way switch + NCCL env lint + misc hardening
8f9c67a|09-19|fix(autotune): majority-vote instead of discard-all (slow-boot root cause)
cd17bee|09-19|feat(scheduler): per-request prefill share cap (idea from upstream #34554)
07d7d9c|09-19|perf(adapter): single-hold raw scale snapshots (reclaim ~4.3 GiB/rank)
977f022|09-19|fix(b12x): backport upstream E4M3 subnormal decode + MXFP8 swizzle bounds
c34d4da|09-17|docs: 600K production board (DE free-form + structured, PR, GSM8K) + fp4idx A/B + RoCEnante verdict
536f7c5|09-17|bench: genericize gsm8k data path for public release
3ec66cd|09-17|LuZ-0.1.7-DSV41F: 600K context in production, S-series governance closed
3959f73|09-13|Attribute the host ring-only NCCL and libncclpin shim to the LuZ lineage
```

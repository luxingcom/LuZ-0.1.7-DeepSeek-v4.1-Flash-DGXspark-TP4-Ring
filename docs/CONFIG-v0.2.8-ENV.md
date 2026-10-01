# 0.2.8 部署配置：模板 ↔ 生产逐键对照与改动说明

**这份文档回答一个问题**：公开仓的 `.env.tp4.example` 与 0.2.8 的生产 `.env.tp4`
到底差什么？差的部分为什么可以差？以及 0.2.8 相对上一代改了哪些**行为相关**的键。

- 生产侧取证时间：**2026-09-24**（只读 `grep`，四机未改动）
- 生产 `.env.tp4` **不公开**（含 `API_KEY` 与 fabric 布线），公开的是模板 + 本文对照表
- 对照方法：两侧各按 `^[A-Za-z_][A-Za-z0-9_]*=` 提取，复合行（`EXTRA_DOCKER_ENV` /
  `EXTRA_SGLANG_ARGS`）再按子键 / flag 拆分比对。复算命令见 §5

---

## 1. 一句话结论

| 层 | 口径 | 结果 |
|---|---|---|
| 顶层标量键 | 模板 73 · 生产 73 | **53 项逐值一致** · **20 项为站点占位符**（有意脱敏）· **0 项缺失** |
| `EXTRA_DOCKER_ENV` | 模板 32 子键 · 生产 32 子键 | **32/32 逐值一致** |
| `EXTRA_SGLANG_ARGS` | 12 token | **逐 token 一致** |

> 口径：**73 = 75 个顶层 `KEY=` 行 − 2 个复合键**（`EXTRA_DOCKER_ENV` /
> `EXTRA_SGLANG_ARGS`，二者单列于下两行）。§5.1 的检查器报的 **75** 是含复合键的
> 总数，两处不矛盾。

⇒ **除站点相关键外，模板与生产没有差异。** 照模板起栈得到的优化集与 0.2.8 生产相同。

> 本文替换了此前模板里那句失效的指针：旧模板声称由
> `evidence/delivery-20260916/gen_env_example.py` 生成 —— 该路径不在公开仓内，
> 生成链在公开侧是断的。自 0.2.8 起以「人工同步 + 本文逐键对照表」作为校验面。

---

## 2. `IMAGE` 出现在四处，**任一处落后都会静默生效**

| # | 位置 | 作用 |
|---|---|---|
| 1 | `.env.tp4`（生产） | 实际被 `start-tp4.sh` 读取的值 |
| 2 | `.env.tp4.example`（本仓） | 新部署从它复制；落后 ⇒ 照模板起栈拉到旧镜像 |
| 3 | `guards.conf` 的 `sglang-image` envpin（**生产侧治理件，不在本仓**） | 守卫比对面；不一致时 preflight 拦下 |
| 4 | `start.sh` 的 `IMAGE="${IMAGE:-…}"` 默认值（本仓） | 两侧 env 文件都未提供 `IMAGE` 时才生效；**不在任何判据覆盖内** |

**这处曾经真的落后过（两层）**：

- **模板 / 公开副本**长期停在 `v7`（0.1.7 世代，125 层）；
- **`start.sh` 默认值**自 09-13 引入后一直不跟随生产：`dsv41-3x-spark:local`（→09-19）
  → `0.2.4`（09-20–09-22）→ `0.2.7`（09-23 提交）→ **`0.2.8`**（09-23 服务器侧修正；
  本仓于 2026-09-24 前向移植时同步取得）。

判据查的都是 `.env.tp4`，默认值不在覆盖内 ⇒「忘了带 `ENV_FILE`」的起栈会静默拿到
旧世代镜像，**没有任何告警面**。

⚠️ 移植后本仓 `start.sh` 的默认值**跟随生产 pin**。该值已于 0.2.9 窗口推进到
**`dsv41-sglang-optimized:0.2.9-ep1q2-fin2`**（本仓 `start.sh` 实测值），
`.env.tp4.example` 亦于 **2026-10-01** 同步到同一 pin（此前停在 `0.2.8`，落后一格）。
⇒ 第 1、2、4 处现均为 0.2.9；第 3 处在生产侧，须与 `.env.tp4` 同提交同改。
3-Spark profile 由 `.env` **显式**提供 `IMAGE=dsv41-3x-spark:local`，不依赖该默认值；
TP4 一律由 `.env.tp4` 显式提供。默认值只在两个 env 文件都缺失时生效。

**本节的教训在 0.2.9 又复发了一次，且是同一格**：模板落后一版 ⇒ 部署者按 README §7
下载并加载 0.2.9 后，`image_preflight()` 会以「镜像不存在」拦下，而它点名的镜像
正是模板里那个部署者从未下载过的 `0.2.8`。**失败是 fail-closed 的（好事）**，
但这说明「四处一致」不是纪律问题而是**判据覆盖问题**：只要第 2 处不被任何检查器读，
它就会在每次代际推进时再落后一次。`scripts/check_env_coverage.py` 现在覆盖模板键集，
仍不覆盖「模板 pin 与 README §7 当前发布件是否同版」——那是下一步该加的门。

---

## 3. 20 项站点相关键（有意占位符，**非**差异）

这些键在生产是有实值的，在模板里是占位符。它们**全是站点/拓扑/账户相关**，
不携带方案信息；公开它们才会出问题（尤其 PEER_HCA 编码了物理布线）。

| 键 | 模板形态 | 说明 |
|---|---|---|
| `HEAD_IP` / `WORKER_IPS` / `WORKER_HOSTS` / `WORKER_USER` | 占位符 | 节点地址与账户 |
| `MODEL_DIR` / `WORKER_MODEL_DIR{,_1,_2,_3}` / `ENGRAM_DIR` / `WORKER_DIR` | `$HOME/...` | 权重与工作目录布局 |
| `COMMON_MODEL` | `/var/tmp/DeepSeek-V4.1-Flash` | 通用 staging 路径，与站点无关，故**不是**占位符 |
| `ENG_SH47` / `ENG_SH48` | `$HOME/...` | Engram 两个本地分片的**路径**——⚠️ **本仓启动器不读它**（见下） |
| `WORKER_EXTRA_MOUNTS_2` / `WORKER_EXTRA_MOUNTS_3` | `$HOME/...` | Engram 两个本地分片的挂载——**实际生效的那一路** |
| `PEER_HCA_RANK0..3` | `<PINNING>` | **每 rank 的对端 HCA 对**；4 节点环网上它等价于物理布线图 |
| `API_KEY` | 空（自动生成） | 生产为 `chmod 600` 的 `$STATE_DIR/api-key` |

> **更正（2026-09-24 第二轮）**：本文早前把 `ENG_SH47` / `ENG_SH48` 与
> `WORKER_EXTRA_MOUNTS_*` 合列，描述为"Engram 两个本地分片的挂载"。**这个描述是错的**：
> `ENG_SH47/48` 被每一个 `.env.tp4*` 变体写入（生产 `.env.tp4` 亦在），但**没有任何
> 启动器读它**——`git log -S'ENG_SH' -- start.sh` 在全部历史中为空，即它从未被
> `start.sh` 消费过；部署根内也无其他 `.sh`/`.py` 提及。真正的挂载由
> `WORKER_EXTRA_MOUNTS_2/3` 以 `-v` 完成，那两个键**是**生效的。
>
> 保留它们在模板里，是因为模板的职责是**忠实记录生产键集**；但请勿以为设了它们
> 会产生效果。这一类（"键在文件里正确、却没有任何通道到达引擎"）已由
> `scripts/check_env_coverage.py` 落成 fail-closed 检查，见 §5.1。

`PEER_HCA_RANK*` 的推导步骤写在模板注释里（从一次 `NCCL_DEBUG=INFO` 首靴里读
`NET/IB/<idx>=<hca>`，再翻译成对端 rank 编号）。`./start-tp4.sh ncclcheck` 可验证结果。

---

## 4. 0.2.8 相对上一代改了什么（行为相关键）

**只有 4 处**。其余全部继承。

| # | 键 | 上一代 | 0.2.8 定板 | 为什么 |
|---|---|---|---|---|
| 1 | `IMAGE` | `0.2.7` | **`0.2.8`** | 代际推进（模板此前停在 `v7`，落后三代） |
| 2 | `CHUNKED_PREFILL_SIZE` | `4096` | **`8192`** | 524288-token prompt **能装下**的前提；**0.2.8 每一格 PR 数据都在此档测得** |
| 3 | `EXTRA_SGLANG_ARGS` | 5 flag | **+3 flag** | `--prefill-decode-interval 4` · `--enable-mixed-chunk` · `--max-queued-requests 32` |
| 4 | `EXTRA_DOCKER_ENV` | 24 子键 | **+7 子键，1 项改值** | 见下表 |

### 4.1 `EXTRA_DOCKER_ENV` 的 8 处变化（相对上一代模板）

| 键 | 值 | 作用 |
|---|---|---|
| `DSV41_IDLE_RELEASE` | `1` | **FIX-B** 空闲窗释放（镜像缺省 `0`） |
| `DSV41_SCHED_SNAPSHOT` | `1` | **FIX-B′** SIGUSR1 内存快照钩子（诊断；整链 fail-open） |
| `DSV41_IDX_PROTOCOL` | `1` | **#40352** 候选块协议（缺省 `0`）—— 256K/512K 单流存活开关 |
| `DSV41_PREFILL_SHARE_TOKENS` | `4096` | scheduler prefill share cap（#34554） |
| `DSV41_PREFILL_EMPTY_CACHE_TOKENS` | `0` | 长 prefill chunk 间的瞬时内存归还 |
| `SGLANG_ENABLE_HEALTH_ENDPOINT_GENERATION` | `0` | — |
| `SGLANG_DSV4_PAGETABLE_PAGES_GRID` | `1` | **R2 page-table 网格"关"**（注意：`1` 表示网格关，非网格在） |
| `DSV41_DENSE_INDEXER_LOGITS_BUDGET_BYTES` | `134217728` | **改值**：`536870912`(512 MiB) → `128 MiB` |

⚠️ **要改这些键，只能改 `EXTRA_DOCKER_ENV` 这一行**。写成顶层独立行**不会进容器**
（`start.sh` 只透传白名单内的顶层变量；其余顶层键静默丢弃，仅打一行 `warn`）。
旧模板恰好在 `DSV41_PREFILL_EMPTY_CACHE_TOKENS` 上踩过这个坑：它把 `=8192`
写在顶层，而生产把 `=0` 写在 `EXTRA_DOCKER_ENV` 内 —— 前者从未生效。该行已删除。

### 4.2 fp4 indexer 的现状

**0.2.8 定板生产：关闭。** 生产 `EXTRA_SGLANG_ARGS` 里
`--enable-deepseek-v4-fp4-indexer` 的出现次数实测为 **0**。

- 形态 A（2026-09-17 → 0.2.8 定板前）曾开启；其 A/B（code-256，同口径）测得
  c1 −6.4 % / c8 −0.9 % / c16 −3.3 %，轻微负向、当时知情保留。
- 形态 A 与形态 B（1 M ctx / 5 M 池 / 12 路）是**不同配置**，数据不得互引。
- ⚠️ **运维禁令**：未先修 FIX-D 的 logits 宽度分桶前不得开启 —— 现制在 2 K 宽度上
  是 1024× 过分配。详见 [RELEASE-NOTES-v0.2.8 §3.1](release-notes/RELEASE-NOTES-v0.2.8.md)。

---

## 5. 怎么复算这张对照表

两侧各自提取，再比对（生产侧为**只读**）：

```bash
# 1) 生产侧（在部署机上执行；只读，不要写入）
grep -vE '^[[:space:]]*#' .env.tp4 | grep -E '^[A-Za-z_][A-Za-z0-9_]*=' > /tmp/prod.keys

# 2) 模板侧（在仓库根执行）
grep -vE '^[[:space:]]*#' .env.tp4.example | grep -E '^[A-Za-z_][A-Za-z0-9_]*=' > /tmp/tmpl.keys

# 3) 键集差异（应为空）
diff <(cut -d= -f1 /tmp/prod.keys | sort) <(cut -d= -f1 /tmp/tmpl.keys | sort)

# 4) 逐值差异（应只剩 §3 的 20 项站点键）
diff /tmp/prod.keys /tmp/tmpl.keys
```

> **⚠️ 正则必须是 `^[A-Za-z_][A-Za-z0-9_]*=`，不能写成 `^[A-Za-z_]+=`** ——
> 后者不匹配含数字的键名，会把**全部 `DSV41_*` 键静默漏掉**，从而给出一个
> 少 21 行、看起来"更一致"的假绿。本轮取证的第一次运行就踩了这个坑。

`EXTRA_DOCKER_ENV` / `EXTRA_SGLANG_ARGS` 是复合行，需按空白拆成子键/flag 再比，
否则整行字符串不同会被误判成"配置不同"。

### 5.1 另一件必须查的事：模板的键，启动器真的读得到吗？

§5 只证明**两侧文件一致**。一致的文件仍可能有一半不生效——键在文件里是对的，但
启动器从不读它，于是不报错、不告警、日志里也没有，只是行为和你以为的不一样。
本仓历史上出过两次这个病：`.env.tp4-600k` 把 `DSV41_IDLE_RELEASE=1` 写成**顶层**
变量（该键只在 `EXTRA_DOCKER_ENV` 内才进容器）；一次 SPF 臂里 `EXTRA_SGLANG_ARGS`
的传值被吞、引擎仍跑默认调度，其后所有测量测的都是另一套配置。§5 的 diff
**一次都发现不了这两件事**。

```bash
python3 scripts/check_env_coverage.py             # default: repo root
python3 scripts/check_env_coverage.py --selftest  # scanner regression only
```

判定按四条通道，四条都不沾的键 ⇒ **扫描失败**：

| 通道 | 含义 |
|---|---|
| **A** | 键名出现在 `start.sh` 的**代码**里（`-e` 列表 / `${KEY}` 读取 / 白名单分支）。**注释不算** —— 注释是让一个键"看起来接好了"最省事的办法，而启动器仍然不会读它 |
| **B** | 该键是 `EXTRA_DOCKER_ENV` 的**子键**（整值透传，启动器无需知道它存在） |
| **C** | 属于启动器**运行时拼出**的编号族：`WORKER_MODEL_DIR_2` 经 `WORKER_MODEL_DIR_${rank}` 到达。整词文本搜索看不见这类，把 8 个键报成"惰性"就是假警报 —— 而一个乱叫的检查器会被学会跳过，代价比它抓到的高 |
| **D** | 在脚本内 `DECLARED_UNUSED` 里**带证据**声明 |

当前结果（0.2.8 定板）：**63 按名 + 8 编号族 + 2 声明未用 + 2 通道载体 = 75 顶层键，`PASS`**。
两个声明未用者即 `ENG_SH47` / `ENG_SH48`（见 §3 的更正）。

> 为什么通道 A 可以忽略注释：`start.sh` 向容器传 env 只有**显式 `-e` 列表 +
> `EXTRA_DOCKER_ENV` 值**两条路 —— 无 `env \|`、无 `--env-file`、无整表导出
> （`grep -c 'env |' start.sh` 为 0）。所以上面四条就是全部。

---

## 6. 与本仓其他文档的关系

| 想知道 | 去哪 |
|---|---|
| 0.2.8 装了什么（镜像载荷、文件级 md5、镜像身份） | [RELEASE-NOTES-v0.2.8.md](release-notes/RELEASE-NOTES-v0.2.8.md) |
| 镜像下载与离线校验 | [README §7](https://github.com/luxingcom/LuZ-0.1.7-DeepSeek-v4.1-Flash-DGXspark-TP4-Ring#7-image-download-release-artifact) · `scripts/verify_release_artifact.py` |
| 性能数字的口径（SD-1、误差棒、可分辨性） | [FINAL-METRICS-600K-2026-09-18.md](03-final-metrics/FINAL-METRICS-600K-2026-09-18.md) |
| 关键 fix 的开关与风险 | [README §4](https://github.com/luxingcom/LuZ-0.1.7-DeepSeek-v4.1-Flash-DGXspark-TP4-Ring#4-experimental-operator-optimization-what-we-changed-and-the-risks) |

# B12x 大 M 回退根因分析（第三方 PR-v3 评测回应）— 2026-09-19

**现象**（第三方 PR-v3 评测（本仓库镜像部署））：B12x 开 = 性能与基准部署接近（16K 输入 C1≈3500 tok/s）；
**B12x 关 = 长输入大幅提升**，且增益随输入长度单调放大（2048≈0% → 8192 +30~42% → 32768 +56~73% → 131072 +84~89%，对上游同口径）。

## 一、根因（三层证据链）

### 1. 交叉点就在我们自己的 bake-off 数据里（M=2048）
`moe-bakeoff-20260914.json`（2026-09-14，真实 layer-2 权重，E=192 K=5120 N=2304 topk=6，单 rank）：

| M | FI CUTLASS W4A8 | b12x W4A16 | a16 vs FI | b12x W4A8 | a8 vs FI |
|---|---|---|---|---|---|
| 6 | 0.020ms | 0.018 | **-10.0%** | 0.018 | -10.0% |
| 48 | 0.637 | 0.581 | **-8.8%** | 0.588 | -7.7% |
| 256 | 4.394 | 4.021 | **-8.5%** | 4.036 | -8.1% |
| 2048 | 41.4 | 44.383 | **+7.2%（b12x 已输）** | 39.245 | -5.2% |

**b12x W4A16 在 M=2048 就已比 FI CUTLASS W4A8 慢 7.2%**；a8 档优势也从 -8.5% 收窄到 -5.2%。
趋势：M 越大，b12x 优势单调收窄直至反超——交叉点就在 2048 附近。

### 2. `moe_b12x.py` docstring 把 a8 的数字误标成了 a16
`adapter/moe_b12x.py:6-10` 写"b12x ahead at every M -- … M=2048 -5.2% (w4a16)"。
实测 **-5.2% 是 a8 的数字；a16 在 2048 是 +7.2%（落后）**。当初按此结论把
`DSV41_MOE_B12X=1`（默认 QUANT=a16）定为生产默认——该结论只在 M≤256 成立。

### 3. bake-off 测量上限 = 2048 = 当时 chunk 大小；生产 chunk 早已越过
- bake-off 与 docstring 注明"Production prefill batch tokens … **zero above chunked_prefill_size**(=2048)"（2026-09-14 口径）。
- 此后 chunk 切换功能上线（4096/6144/8192 三档），`start.sh` 自动把 `DSV41_MOE_B12X_CAPS` 补到 chunk 档——
  阶梯**容量**跟上了，但**性能交叉点**没人重测：prefill m=4096-8192 运行在已判负的区间外推段。
- 第三方 PR-v3 长输入（8K-128K）prefill 恰好全落在这个未验证区间 ⇒ 关 B12x（= 回 FI CUTLASS W4A8，
  见 `moe_b12x.py:3` 门注释）大幅提升，且 M 越大差距越大（与字节经济一致：W4A16 激活 bf16 是 W4A8 的 2×，
  大 M 时激活流量随 M 线性放大而专家权重一次摊销；叠加 b12x 小 M 特化 tile 在大 M 的形状低效）。

## 二、为什么不简单改成"全线关 B12x"
decode/verify（m≤96 精确档 + 图 bs≤12）是 b12x **已验证**的优势区（-8~12%），
我们的生产流量以 decode 为主。全线关闭 = 用 prefill 的收益换 decode 的回退，净效应取决于负载画像。
**prefill 密集基准 ⇒ 对该负载而言 DSV41_MOE_B12X=0 就是正确配置**（立即可用的缓解）。

## 三、建议修复（混合路由，单一开关）—— ⚠已被实施并**当场判负**，见 §五

## 五、【追记 2026-09-19 晚】混合路由实施判负：与 single-hold 布局不兼容

当日 v17 按 §三实施了 MMAX=2048 委派回 FI 的混合路由，**质量门当场抓获**：
- needle 30K：答案 `', the code word is the same as the code '`（乱答）；max_tokens 放大到 256 后
  答案为 "The secret code word is PELICAN."——**找到针但丢数字后缀**；mt=64 出现贪心复读退化。
- 所有短 prompt 项（算术/JSON/tool-call/code-gate 12/12/终止性 18/18）全绿；36K probe 应答连贯。

**根因**：single-hold 优化（`DSV41_MOE_B12X_DUAL_HOLD=0` 默认）在装载期把
`flashinfer.block_scale_interleave` 替换为恒等——活权重 scale 永远停在 **checkpoint 序**
（b12x 的消费格式）。而 FlashInfer CUTLASS W4A8 消费的是 **interleaved 布局**。
MMAX 委派把这些 m>2048 的 prefill 调用交给拿着错布局 scale 的 FI 核 ⇒ 大 M chunk 的 KV
静默污染 ⇒ needle 所在 chunk 被污染。短 m≤2048 走 b12x 不受影响——症状剖面完全吻合。

**v18 修复**：
1. `DSV41_MOE_B12X_MMAX` 默认 999999（全 b12x）；**仅 `DSV41_MOE_B12X_DUAL_HOLD=1` 时
   FI 委派才武装**（dual-hold 让 interleave 原地发生、b12x 拿克隆，两路都可消费；代价 ~4.3GiB/rank）。
2. 使用方指引不变：**prefill 密集负载直接 `DSV41_MOE_B12X=0`**（hook 链整体不装、权重正常
   interleave、全 FI W4A8——他们实测的大幅提升路径，且无布局冲突）。
3. `gates_suite.py` needle 补 run 唯一前缀（固定 seed 全量缓存命中 → 复测读旧 KV 假 FAIL/
   假 PASS，本次三连假 FAIL 实证）。

**残留开放问题**：b12x-**a8** 在 M=4096/6144/8192 vs FI W4A8 无实测（第三方对比的是 a16）。
若窗口扫描显示 a8 大 M 仍守不住，则本部署长 prefill 的最优解 = dual-hold + MMAX 混合路由
（付 4.3GiB/rank）或 per-chunk 换 B12X=0 的部署形态。

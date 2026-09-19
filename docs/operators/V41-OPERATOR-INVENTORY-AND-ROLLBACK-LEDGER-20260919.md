# V4.1 权重计算路径：算子全景清单 + 回退台账（2026-09-19）

按用户指令编制：全部算子优化按来源分类（上游开源/闭源/自研），各自作用与效率、
剩余优化空间、全部回退及理由。**事实基线 = 本日双子代理交叉普查 + 当日实机验证**。

---

## 0. 血统与许可总纲

| 组件 | 来源 | 许可 | 备注 |
|---|---|---|---|
| SGLang 基座 | `lmsysorg/sglang:dev-dsv41`（digest 4a5d132a） | Apache-2.0 | 全部 overlay 的宿主 |
| FlashInfer 0.6.18 | 上游开源 | Apache-2.0 | MoE W4A8 CUTLASS / dense MXFP8 / autotune |
| DeepGEMM | 上游开源 | MIT | FP4 indexer logits GEMM |
| Triton | 上游开源 | Apache-2.0 | attn/dequant/engram_hash/fast_argmax |
| SGLang JIT（nvcc sm_121a + ninja + tvm_ffi，独立第四条编译链） | 上游开源 | Apache-2.0 | c1/c2/store/main_norm_rope/topk 等 19 变体 |
| **b12x 1.3.0** | PyPI 公开包（github.com/local-inference-lab/b12x） | **Apache-2.0（非闭源）** | ⚠自述"不面向生产/数据中心"= 合规唯一注意点；本仓 wheel 解包 + 2 个自研回移补丁 |
| **NCCL ring-only 2.30.7 + libncclpin.so** | LuZ 系（luxingcom/aicad-nccl-optimization） | **⚠无许可证声明** | 全清单唯一真正无许可外部二进制 |
| NCCL 上游 | NVIDIA | BSD | ring-only 构建的源头 |
| 自研 adapter（8 文件）+ overlay（45 条） | 本仓 | 随仓 | 见 §2/§3 |

---

## 1. 按路径段的算子清单（作用 × 效率 × 状态）

### 1.1 稀疏 MLA 注意力（权重字节大头之一）
| 项 | 作用 | 效率 | 状态 |
|---|---|---|---|
| FlashInfer `_sparse_mla_sm120` + `flash_mla_sm120.py` | SM121 稀疏 MLA 主核 | decode attn 仅 1.1ms/步(2%) | 在役 |
| `repack_fp4_to_v4.py`（PR#39123 fork + H1-H5 加固） | FP4 主 KV→584B V4 形态桥 | bytes/token 1670.75→912.25，池 ≈×1.9 | 在役（`fork-v4-fp4`） |
| `dequant_k_cache.py`（Triton） | V4 布局 KV 反量化 | — | 在役 |
| C4 indexer（`dsv4_indexer.py` + topk JIT + DeepGEMM FP4） | 低比压缩+top-512 候选 | logits 预算锁 512MiB | 在役 |
| `dsv4_prefill_reuse.py`（PR#38979 回移） | 相邻查询行复用 | 曾测 −17~24%@232K，**后证挂错分支** | **死代码/关** |
| `--enable-deepseek-v4-fp4-indexer` | FP4 索引器全量 | 500K 冷 prefill −11%、c12 无增益 | **回退关** |

### 1.2 MoE 路由专家（本次事故中心，37 层）
| 项 | 作用 | 效率 | 状态 |
|---|---|---|---|
| `adapter/moe_b12x.py`（b12x W4A8-MX 换路） | MoE grouped GEMM 走 b12x | 小/中 M 对 FI W4A8：M=6 −10%、M=256 −8.1%、M=2048 −5.2%（a8）；a16@2048 **+7.2% 反超** | 在役（QUANT=a8，MMAX 全 b12x） |
| 容量阶梯（_EXACT_MAX=96 + caps） | 防 per-M 新 plan JIT 冻结 + decode 精确档 | boot24 实证防 24× 慢桶；a8 梯 493 个 m 扫描 0 失败 | 在役 |
| single-hold（中和 block_scale_interleave） | 省 scale 双持 | **−4.3GiB/rank** | 在役（`DUAL_HOLD=0`） |
| b12x intrinsics/dense_gemm 两补丁 | E4M3 解码修正/SFB 越界防护 | 修 1.07-4.5× 数值错/防 OOB | 在役（上游 commit 回移） |
| FlashInfer CUTLASS W4A8 | 原 MoE 路径 | **大 M（>2048）优势区**（第三方评测实测 +30~84% 随输入长度放大） | 回退档（`B12X=0` 时全量在役） |

**⚠大 M 事故全程（2026-09-19，当日闭环）**：详见 [V41-B12X-LARGEM-REGRESSION-ANALYSIS-20260919.md](V41-B12X-LARGEM-REGRESSION-ANALYSIS-20260919.md)。
一句话：bake-off 只测到 M=2048=当时 chunk；chunk 升 4096-8192 后 prefill 落入未测外推段；
docstring 把 a8 的数字误标成 a16 使"W4A16 全区间占优"成为默认依据。当日 v17 的 MMAX→FI
混合路由又被质量门当场判负（single-hold 下 FI 消费错布局 scale ⇒ 大 M KV 污染）——v18 终态：
**a8 默认 + 全 b12x + 回退仅在 dual-hold 下武装**。gate 9/9 复绿。

### 1.3 MoE 共享专家 / dense 投影
| 项 | 作用 | 效率 | 状态 |
|---|---|---|---|
| `shared_pad_k.py`（K 576→640 零填充） | 共享专家 down_proj 重获 b12x 资格 | 58.0→17.2µs（−70.3%），步时 +1.47%，bitwise 0 差异 | 在役 |
| `mxfp8_b12x.py`（dense MXFP8→FI b12x 后端） | 全 dense 投影 GEMM | M=6 decode 50-75GB/s → 大幅提升（2026-09-10 profile） | 在役（**⚠§4-O2 同款大 M 未测风险**） |
| wo_a bmm（BF16 孤岛） | n_local_groups 批量投影 | 3.90ms/步，SM121 无 tcgen05 | **立项待办**（fp8 重打包 −2.4ms，另有 #39193 守卫冲突未入计划） |
| lm_head（bf16 全 vocab ×2 遍） | logits | 2.73ms/步，读 331MB=242GB/s 贴墙 | **合并立项待办**（−1.37ms）；W4A8 量化 C-2 数值门 FAIL 判负 |

### 1.4 通信 / Engram / spec-decode / KV 池
| 项 | 作用 | 效率 | 状态 |
|---|---|---|---|
| NCCL ring-only 2.30.7 + ncclpin | 五类集合通信全 ring + 核绑定 | EP 4→2：500K prefill 595→345s；LL128/8ch 重测判负 | 在役（最优已核） |
| `engram_backend.py` + row_store.cpp | Engram 文件后端（O_DIRECT pread+16 路缓存） | 命中 0→99.1%，c12 +6%，prefill 100K +10.5% | 在役（CACHE_GIB=1） |
| DSPARK spec-decode（draft+verify+argmax Triton） | k=5 投机 | acceptance 3.98 tok/步（rate 0.595） | 在役 |
| SPS 表 + RAGGED_VERIFY_MODE=static | 预算排程表 | **表在位但 static 下 no-op**；compact 门=上游 #39257/#40162（09-19 仍 open） | 待上游（+10.5% 挂起） |
| FP4 主 KV 池（22 文件） | paged KV | pin 9.6M（16×600K），full_token≈17.4-17.8M，余量=地板保留 | 在役 |
| `flashinfer_autotune.py` 多数票 | 消除 per-boot tactic 彩票 | 慢靴根因修复（2026-09-19） | 在役 |
| CED opt1（非末 chunk 跳 19 解码层） | prefill 减无效计算 | 11K 热态 3799-3982 t/s | 在役 |
| `deepseekv32/v41_detector.py`（vLLM #52645 回移） | 工具调用截断三保证 | 离线桩 13/13 + 线上 D 档全过 | 在役（v18） |

---

## 2. 回退/判负/不采纳 全台账（决定+理由+日期）

| # | 决定 | 理由 | 日期 |
|---|---|---|---|
| 1 | nvfp4 KV 判死 | 四重闸门（SM/后端白名单/仅 1.78×/584B envelope） | 09-12~15 |
| 2 | lm_head/投机头 W4A4-W4A16 量化（C-2） | top1 0.86<<0.995，验收率塌 24.3% | 09-12 |
| 3 | W4A4 激活 FP4（vLLM N1 的 decode 面） | decode −6~−9%，只取 prefill 面 | 09-13 |
| 4 | scratch 512→4096MB | 切片归零但 e2e 无收益 +1.2GB | 09-16 |
| 5 | expandable_segments:True | SM121 NaN 前科 | 09-15 |
| 6 | CACHE_GIB=4 | 900K 单 prompt 打失败（地板 3.53→1.50GB） | 09-16 |
| 7 | chunk 6144（W5）→后推翻 | 地板 −4GiB 论据失效；8192 复测采纳 | 09-16→18 |
| 8 | RoCEnante one-shot RDMA | 物理环型布线与 one-shot 不兼容，QP RTR 超时 | 09-17/18 |
| 9 | NCCL LL128/8 通道/pinned-RAM 回收 | 两臂重测判负/早已在役 | 09-15/16 |
| 10 | prefill_reuse uniform-w4（#38979） | 挂错死分支（ratio-4），flag 已删 | 09-16 |
| 11 | fp4-indexer 全量 | 轻微负向（c1 −6.4%），保留观察 | 09-17 |
| 12 | torch.compile max-autotune/PD 分离 | FULL graph 冲突面大 | 09-12 |
| 13 | **MMAX→FI 混合路由（v17）** | **single-hold 布局冲突 ⇒ 大 M KV 污染，needle 门判负**（当日修复为 dual-hold 门控） | **09-19** |
| 14 | E 轨 draft 预测预取 / B3′ mhc warmup / APC 轮 | 命中率 40.3%<80% / 无的放矢 / 污染证伪 | 09-12 |
| 15 | 异构 PD（Ultra） | 跨引擎 KV 桥高风险 | 09-13 |
| 16 | per-rank PEER_HCA | ring-only 库内二进制零命中=死信（已标注） | 09-19 |
| 17 | SGLANG_FLASHINFER_AUTOTUNE_EXTEND | 无效果面（dense 被 pin、MoE 走梯桶） | 09-19 |

**默认关但已实现（备弹）**：`DSV41_PREFILL_SHARE_TOKENS`（prefill 份额门，无 A/B 记录）、
`DSV41_MOE_B12X_MMAX`（dual-hold 门控下才武装）、`DSV41_MOE_B12X_DUAL_HOLD`（+4.3GiB/rank 换双路兼容）。

---

## 3. 与"用户明确指示"的对齐核查（本次任务专项）

| 指示 | 落实状态 |
|---|---|
| **FI 路径 W4A8 采纳** | **此前被 a16 默认遮蔽（bake-off 误标）→ 09-19 已纠正**：生产 a8 全区间 W4A8（b12x w4a8_mx），大 M 场景使用方 B12X=0 全 FI W4A8。残留：b12x-a8 vs FI 在 M=4096-8192 无实测（§4-O1） |
| chunk 三档（4096/6144/8192）可切换 | start.sh 白名单+CAPS 联动在役；生产 8192 |
| S1+S2 调度组合 | mixed-chunk+PDI=4 在役（live 已核） |
| KV 池容量用起来 | 2M→3.5M→9.6M（16×600K）已落地 |
| 工具调用截断语义（#52645） | v18 在役，全档验证 |
| 慢靴根因 | 多数票在役，本靴日志实证 |
| 脱敏检查+检查点命名 | 发布包按 `LuZ-<版>-dsv41-tp4` 命名导出 |

---

## 4. 剩余优化空间（按预期收益排序）

- **O1【高·prefill】b12x-a8 vs FI W4A8 @ M=4096/6144/8192 三臂窗口扫描**：决定基准部署长
  prefill 终态（全 b12x-a8 / dual-hold+MMAX 混合 / 域分割部署）。第三方的 +30~84% 是对 a16 的，
  a8 差距应显著小于此但方向未定。
- **O2【中·prefill】dense b12x 大 M 同款风险**：`mxfp8_b12x.py` 无 M 路由、bake-off 只测过
  decode 形状（284 次/步全 decode 口径）。prefill M=8192 的 dense GEMM 未测——与 MoE 事故
  同构的隐患，列入下一窗口。
- **O3【中·decode】wo_a fp8 重打包（−2.4ms/步）+ lm_head 双遍合并（−1.37ms/步）**：立项
  在案未执行；wo_a 须先解 #39193 守卫冲突。
- **O4【中·吞吐】compact verify**（SPS 表解锁 +10.5%）：卡上游 #39257/#40162，合并即复评。
- **O5【低】PREFILL_SHARE_TOKENS 份额门 A/B**（ITL p99 第二道门）。
- **O6【合规】b12x"非生产用途"自述**与 **LuZ NCCL shim 无许可**：开源发布前需法务口径
  （替换 shim 或取得授权）。

---

## 5. 生产 board 参考（v18 落位后）

decode prose 抽查 c1≈27/c12≈126 tok/s（快速抽查口径，非正式基准）；
gate 9/9（needle 30K/229K/470K 全过）；工具调用截断全档过；boot 签名
`fi-fallback=off` + majority-vote 无彩票。正式 PR-v3 对照待用户侧基准。

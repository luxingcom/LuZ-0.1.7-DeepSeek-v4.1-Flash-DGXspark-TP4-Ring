# RELEASE-NOTES-v0.2.5 · v19-40217prep（#40217 minimal native port）· 2026-09-20

> **一句话**：#40217 最小原生移植（dense indexer candidate mask 无界项修复）+ engram stats v2
> 上车；PR-v3 全 40 格重测，**全表中位 +8.1%、峰值 4,803.2 t/s @8192×C2（对 v18 峰 +11.7%）**；
> 窗口门禁 18/18、4×245.7K needle 4/4 后提升生产（governance pin → 0.2.5）。
> ops 仓提交：`86f688b`（prep）→ `0cc8c5c`（promote，tag `v0.2.5`）。

## 1. 构建身份

| | 值 |
|---|---|
| 镜像 | `dsv41-sglang-optimized:0.2.5`（别名 `v19-40217prep`，**同一 image ID**） |
| Image ID | `sha256:ab5a109f5f056613cadac76829cff6a7012bc0558c461b788113e6eb00fc75c2` |
| 内容身份（join RootFS.Layers sha256 前 16 位） | **`b4ca63d71bbe8557`**（01 机实测；125 层） |
| 对 0.2.4（`e4fe9dc13017e5d7`） | 前 72 层一致，后 53 层随 overlay 重建全部更新（buildkit 时间戳进层）；`org.dsv41.built_at=2026-09-20T02:10:59Z` · overlay 45 文件 · map md5 `bcb4cde4d9b3` |
| SGLang | `da64c5cbb8cf6bfd39be19da43573fdfd484c43a`（与 0.2.4 同一 commit） |

⚠️ **内容身份随 overlay 重排全部变化属预期**（`docker build` 的时间戳进层 + 层链重算）。
跨版本验收判据是**归档内容身份**（BUILD-IDENTITY 表），不是「身份不变」——0.2.5 与 0.2.4 是
不同的构建，发布包/验收流程以新值为准。

## 2. 改动内容（ops 仓 `86f688b`）

1. **T1 · #40217 minimal native port**（本轮唯一可能影响性能的项）：
   `--enable-mixed-chunk` 下混合批次曾回退全行发布，candidate mask 变成无界
   `[chunk≤8192, lc]` bool（245K 前缀 ≈2.0 GiB、600K 角 ≈4.9 GiB——dense indexer 瞬态
   最后一个无界项）。现改为骑 `full_batch_tail_lens_cpu` 发布，mask_b 收界到
   **`[tail≤128, lc]`**。上游全量 blockID 形态在 B200 131K 冷 prefill 有 −8% 回退——
   本移植只针对无界项，不引入该回退。
2. **Z2 · engram stats ABI v2**：evictions / unique-row bitmap / 按 n-gram 阶的 hit/miss
   拆分（观察性改动，不在推理热路径）。
3. **T3 · dense MXFP8 bake-off harness**（`bench/dense_mxfp8_bakeoff.py`）：补大 M 盲区；
   发现 FI cutlass 拒收 dense 形状（记录为 finding）。

## 3. 窗口验证（提升前门禁）

- 门禁套件 **18/18**；4×245.7K needle **4/4**
- serve 日志确认 engram stats v2 生效（evictions / unique_rows 有计数）
- governance pin → 0.2.5（guards.conf md5 `04fe84d6e14a` ×4 机）

## 4. PR-v3 全 40 格重测（本仓 §3 与 data/ 已接替为权威）

- 归档：[`data/prv3-v19-40217prep-20260920/`](../../data/prv3-v19-40217prep-20260920/)
  （summary.json + TABLE.md + CONCURRENCY.md + raw/ 40 格逐流原始记录）
- 运行脉络：2026-09-20 08:21（512–4096 短档）→ 08:35（长档，
  `prv3-v19-long-tiers.log`）→ 09:28 合并定稿 `prv3-v19-40217prep-20260920`
- 采集器同 v18 版（`prv3_collector.py`），chunk 8192 同口径 ⇒ **v18↔v19 同工具对照**；
  v19 全部 manifest_sha256 = `8deaffae12…`（同一提示词 manifest，冷前缀 nonce 逐流唯一）

**读数**（逐格明细见 FINAL-METRICS §3；括号内为对 v18 同格）：

- **峰值 4,803.2 t/s @8192×C2**（4,299.6，**+11.7%**）；8192 行 C1–C4 **+36~+55%**
- **全表中位 +8.1%**（40 格：31 升 9 降）；长档（≥16384）中位 **+8.1%**
- 最大增益 +69.7%（2048×C8，2,261.9→3,838.1）；16 格增益 ≥+15%
- **9 格回退，其中 >5% 的 7 格**（全部单波、无误差棒，对照意义有限）：
  512×C4 −36.6%、65536×C8 −21.7%、16384×C2 −15.5%、16384×C8 −11.6%、
  8192×C8 −9.0%、4096×C16 −8.7%、65536×C1 −5.0%——512×C4 与 65536×C8 同时是
  v18 轮的行内离群格，与 v18 的 512 行 C8>C16 倒挂同型，单波方差嫌疑最大，已列补测
- 准入律 `min(C, max(1, ⌊8192/input⌋))` **27/40 精确**（与 v18 完全同型）；
  真并行步 11/40 格（512 最高宽 10、2048 宽 5、4096 宽 3、8192 宽 2 系 mixed-chunk
  decode 搭载）

## 5. 未随本轮重测的臂（诚实标注）

- **DE 20 格 / GSM8K / grammar / fp4 / 网关**：数字仍测于 v18（0.2.4）栈
  （2026-09-20 晨），v19 上**未重跑**。Z2 属观察面、T1 属 prefill 热路径，
  理论上不碰 decode 形态；在 DE 补测前，§4 的 DE 数字**标注 v18 而非 v19**。
- **512K 单流（2,257.2 t/s）**：v18 轮补测值，未在 v19 重测，同上标注。

## 6. 治理与发布面

- guards.conf pin → `0.2.5`（四机 md5 `04fe84d6e14a`）
- start.sh / start-tp4.sh `IMAGE=` 默认 → `0.2.5`
- 网盘发布包**仍为 0.2.4**（`LuZ-0.2.4-dsv41-tp4-dgxspark.tar.zst`，内容身份
  `4ebef21b6aedbd70`）；0.2.5 发布件**尚未打包分发**，README §7 下载节如实标注

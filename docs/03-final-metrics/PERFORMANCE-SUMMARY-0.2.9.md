# 0.2.9-ep1q2-fin2 性能与 QA 证据摘要（4×DGX Spark TP4，2026-09-28/29）

对照锚=上一稳定版 ep1q2-fin（同硬件同口径 fin 终锚）。量具=sparkDash 三件套（bench/sd_bench.py DE、bench/wpr1-kit/pr_prefill_probe.py PR、bench/gates_suite.py QA17）。

## 一、终锚数字

| 指标 | fin 基线 | **fin2（本发布）** | 变化 |
|---|---|---|---|
| PR 262k（repeated，wall） | 160.0s | **160.7 / 161.6s**（两靴） | 带内持平（±3% 靴噪声内） |
| PR 131k | 76.5s | **77.5 / 77.5s**（两靴同值） | −1.3% 带内 |
| PR 32768 / 4096 | 20.0s / 4.3s | 沿用 fin 锚（未重测，同面） | — |
| DE prose c1（tok/s） | 70.42 / 71.20 | **69.95 / 70.47** | 持平微升（τ 移除后） |
| DE prose c8 | 23.98 | **24.95** | **+4.0%**（draft_head_fp8_tp4 修 16 行瓦重读自伤） |
| DE prose c12 | 20.46 | **21.45** | **+4.8%** |
| DE code c1 | 113.49 / 116.01 | 沿用 fin 锚 | — |
| QA | 17/0 | **17/0** | 门 |

## 二、本版三键的兑现证据

- **draft_head_fp8_tp4**：c8/c12 双靴双兑现（四键臂 24.37/21.35 + 确认靴 24.95/21.45，两次独立靴均正向）；c1 持平微升。
- **hc_fused**：位等四证（113 行数 GPU 位等×2+两靴引擎首调 1071 行逐位同）；kernel census 净省 915ms/32 步窗=28.6ms/chunk；PR 墙钟增益在单靴噪声（±3%≈±5s）之下不可分辨——判"非负保留"。
- **τ 不设/gather 512K**：τ=0.8 判负（DE flat-负）；gather 1M 判负 C29（nccl.AR +36%/call 争用，131k −5.6% 回归，回 512K 后收复）。

## 三、长上下文与稳定性

- ctx 600000 上限、chunked prefill 4096；262k 双档带内；容许 KV 池 9.6M tokens。
- 稳定性记录：确认窗+复证窗全程无守卫止损触发（唯一一次 oom-gate 止损系测试协议违纪所致，非镜像缺陷，报告见归档 90 §六）。
- 内存形态：boot 基线 ~17.8G MemAvailable；262k PR 后 ~10G=引擎合法驻留（KV/池+容器 tmpfs trace）；memcg 32G 下稳态 ~12.75GiB。

## 四、原始产物位置

归档主库 90 号报告（判决全表+census 归因）与 <handover-root>/window-20260928-wfin/{t2-anchor, fin2-arm, fin2-confirm, fin2-boot2}（各靴 QA/DE/PR JSON、横幅、三合一快照）。

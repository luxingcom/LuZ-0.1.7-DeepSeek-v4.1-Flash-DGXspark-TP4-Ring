# PR-v3 concurrency verdict — prv3-v14-final (chunk 8192)

Recomputed from the per-stream first-token instants in `raw/` by
`benchmarks/pr_v3_concurrency.py <this-dir>/raw 0.010 8192`. Method and
tolerance rationale are in that script's docstring (default tol 10 ms,
stable over 0.005-0.05 s; verdicts re-checked at chunk = 4096 for
cross-reference: the 4096-row cells show width 2 there, i.e. the run
really executed at chunk 8192, not 4096).

This engine run used `--chunked-prefill-size 8192` (the 2026-09-19
benchmark form). Admission law: `min(C, max(1, floor(8192/input)))`.

```
tolerance = 0.01s   chunked_prefill_size = 8192

| Input | C | predicted width | observed width | clusters | median gap s | max within-cluster spread s | admission law holds |
|---:|---:|---:|---:|---:|---:|---:|---|
| 512 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 512 | 2 | 2 | **2** | 1 | None | 0.0001 | yes |
| 512 | 4 | 4 | **2** | 2 | 0.55 | 0.0003 | NO |
| 512 | 8 | 8 | **7** | 2 | 1.37 | 0.0014 | NO |
| 512 | 16 | 16 | **13** | 2 | 2.553 | 0.0014 | NO |
| 2048 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 2048 | 2 | 2 | **1** | 2 | 0.765 | 0.0 | NO |
| 2048 | 4 | 4 | **3** | 2 | 2.065 | 0.0003 | NO |
| 2048 | 8 | 4 | **4** | 3 | 2.956 | 0.0004 | yes |
| 2048 | 16 | 4 | **4** | 5 | 2.819 | 0.0006 | yes |
| 4096 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 4096 | 2 | 2 | **2** | 1 | None | 0.0001 | yes |
| 4096 | 4 | 2 | **2** | 2 | 2.562 | 0.0001 | yes |
| 4096 | 8 | 2 | **2** | 5 | 2.461 | 0.0001 | yes |
| 4096 | 16 | 2 | **2** | 9 | 2.599 | 0.0001 | yes |
| 8192 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 8192 | 2 | 1 | **1** | 2 | 2.647 | 0.0 | yes |
| 8192 | 4 | 1 | **1** | 4 | 2.45 | 0.0 | yes |
| 8192 | 8 | 1 | **1** | 8 | 2.606 | 0.0 | yes |
| 8192 | 16 | 1 | **1** | 16 | 3.051 | 0.0 | yes |
| 16384 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 16384 | 2 | 1 | **1** | 2 | 6.519 | 0.0 | yes |
| 16384 | 4 | 1 | **1** | 4 | 7.499 | 0.0 | yes |
| 16384 | 8 | 1 | **1** | 8 | 7.526 | 0.0 | yes |
| 16384 | 16 | 1 | **1** | 16 | 8.788 | 0.0 | yes |
| 32768 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 32768 | 2 | 1 | **1** | 2 | 19.586 | 0.0 | yes |
| 32768 | 4 | 1 | **1** | 4 | 19.244 | 0.0 | yes |
| 32768 | 8 | 1 | **1** | 8 | 19.329 | 0.0 | yes |
| 32768 | 16 | 1 | **1** | 16 | 19.394 | 0.0 | yes |
| 65536 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 65536 | 2 | 1 | **1** | 2 | 46.962 | 0.0 | yes |
| 65536 | 4 | 1 | **1** | 4 | 44.959 | 0.0 | yes |
| 65536 | 8 | 1 | **1** | 8 | 43.656 | 0.0 | yes |
| 65536 | 16 | 1 | **1** | 16 | 43.044 | 0.0 | yes |
| 131072 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 131072 | 2 | 1 | **1** | 2 | 72.634 | 0.0 | yes |
| 131072 | 4 | 1 | **1** | 4 | 89.977 | 0.0 | yes |
| 131072 | 8 | 1 | **1** | 8 | 97.448 | 0.0 | yes |
| 131072 | 16 | 1 | **1** | 16 | 85.816 | 0.0 | yes |

admission law: 35/40 cells match min(C, max(1, floor(8192/input))) exactly
cells with a real parallel step (observed width >= 2): 11/40
  512 x C2: width 2, clusters 1, sizes [2]
  512 x C4: width 2, clusters 2, sizes [2, 2]
  512 x C8: width 7, clusters 2, sizes [1, 7]
  512 x C16: width 13, clusters 2, sizes [3, 13]
  2048 x C4: width 3, clusters 2, sizes [1, 3]
  2048 x C8: width 4, clusters 3, sizes [1, 4, 3]
  2048 x C16: width 4, clusters 5, sizes [1, 4, 4, 4, 3]
  4096 x C2: width 2, clusters 1, sizes [2]
  4096 x C4: width 2, clusters 2, sizes [2, 2]
  4096 x C8: width 2, clusters 5, sizes [1, 2, 2, 2, 1]
  4096 x C16: width 2, clusters 9, sizes [1, 2, 2, 2, 2, 2, 2, 2, 1]
```

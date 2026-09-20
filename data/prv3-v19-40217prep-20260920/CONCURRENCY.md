# PR-v3 concurrency verdict — prv3-v19-40217prep-20260920 (chunk 8192)

Recomputed from the per-stream first-token instants in `raw/` by
`benchmarks/pr_v3_concurrency.py <this-dir>/raw 0.010 8192`. Method and
tolerance rationale are in that script's docstring.

Engine form at run time (from the head container launch args):
`--chunked-prefill-size 8192 --enable-mixed-chunk --prefill-decode-interval 4`.
Admission law: `min(C, max(1, floor(8192/input)))` — the baseline holds 27/40
exactly (same shape as v18). 13 cells deviate, ALL in the arrival-dominated
small-prompt band:
- 10 cells fall BELOW the law (512/2048/4096 rows; batches of 2-4 arrived
  merged into one step — scheduler coalescing of ready requests);
- 3 cells show a step width of 2 where the law predicts 1 (8192 x C8/C16,
  4096 x C8/C16): with `--enable-mixed-chunk`, a decode piggybacks on the
  prefill step, and at 8192 the streamed first tokens of consecutive
  requests can land inside the 10 ms cluster tolerance. These width-2 steps
  are NOT prefill parallelism: wall-clock per cell matches serialized
  service time (see TABLE.md gaps).

```
tolerance = 0.01s   chunked_prefill_size = 8192

| Input | C | predicted width | observed width | clusters | median gap s | max within-cluster spread s | admission law holds |
|---:|---:|---:|---:|---:|---:|---:|---|
| 512 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 512 | 2 | 2 | **1** | 2 | 0.383 | 0.0 | NO |
| 512 | 4 | 4 | **3** | 2 | 1.31 | 0.0009 | NO |
| 512 | 8 | 8 | **7** | 2 | 1.757 | 0.0034 | NO |
| 512 | 16 | 16 | **10** | 3 | 1.43 | 0.0039 | NO |
| 2048 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 2048 | 2 | 2 | **1** | 2 | 0.64 | 0.0 | NO |
| 2048 | 4 | 4 | **3** | 2 | 1.495 | 0.0013 | NO |
| 2048 | 8 | 4 | **5** | 3 | 1.802 | 0.0031 | NO |
| 2048 | 16 | 4 | **5** | 4 | 2.548 | 0.0035 | NO |
| 4096 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 4096 | 2 | 2 | **1** | 2 | 0.977 | 0.0 | NO |
| 4096 | 4 | 2 | **2** | 3 | 1.415 | 0.0015 | yes |
| 4096 | 8 | 2 | **3** | 4 | 2.491 | 0.0029 | NO |
| 4096 | 16 | 2 | **3** | 7 | 2.569 | 0.0034 | NO |
| 8192 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 8192 | 2 | 1 | **1** | 2 | 1.676 | 0.0 | yes |
| 8192 | 4 | 1 | **1** | 4 | 2.436 | 0.0 | yes |
| 8192 | 8 | 1 | **2** | 6 | 2.436 | 0.0022 | NO |
| 8192 | 16 | 1 | **2** | 12 | 2.446 | 0.0027 | NO |
| 16384 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 16384 | 2 | 1 | **1** | 2 | 1.593 | 0.0 | yes |
| 16384 | 4 | 1 | **1** | 4 | 2.507 | 0.0 | yes |
| 16384 | 8 | 1 | **1** | 8 | 4.218 | 0.0 | yes |
| 16384 | 16 | 1 | **1** | 16 | 2.503 | 0.0 | yes |
| 32768 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 32768 | 2 | 1 | **1** | 2 | 7.559 | 0.0 | yes |
| 32768 | 4 | 1 | **1** | 4 | 8.558 | 0.0 | yes |
| 32768 | 8 | 1 | **1** | 8 | 11.411 | 0.0 | yes |
| 32768 | 16 | 1 | **1** | 16 | 11.716 | 0.0 | yes |
| 65536 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 65536 | 2 | 1 | **1** | 2 | 18.549 | 0.0 | yes |
| 65536 | 4 | 1 | **1** | 4 | 22.889 | 0.0 | yes |
| 65536 | 8 | 1 | **1** | 8 | 23.691 | 0.0 | yes |
| 65536 | 16 | 1 | **1** | 16 | 24.602 | 0.0 | yes |
| 131072 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 131072 | 2 | 1 | **1** | 2 | 48.436 | 0.0 | yes |
| 131072 | 4 | 1 | **1** | 4 | 51.675 | 0.0 | yes |
| 131072 | 8 | 1 | **1** | 8 | 53.855 | 0.0 | yes |
| 131072 | 16 | 1 | **1** | 16 | 52.184 | 0.0 | yes |

admission law: 27/40 cells match min(C, max(1, floor(8192/input))) exactly
cells with a real parallel step (observed width >= 2): 11/40
  512 x C4: width 3, clusters 2, sizes [1, 3]
  512 x C8: width 7, clusters 2, sizes [1, 7]
  512 x C16: width 10, clusters 3, sizes [1, 10, 5]
  2048 x C4: width 3, clusters 2, sizes [1, 3]
  2048 x C8: width 5, clusters 3, sizes [1, 5, 2]
  2048 x C16: width 5, clusters 4, sizes [1, 5, 5, 5]
  4096 x C4: width 2, clusters 3, sizes [1, 2, 1]
  4096 x C8: width 3, clusters 4, sizes [1, 2, 3, 2]
  4096 x C16: width 3, clusters 7, sizes [1, 2, 3, 3, 3, 3, 1]
  8192 x C8: width 2, clusters 6, sizes [1, 1, 1, 2, 1, 2]
  8192 x C16: width 2, clusters 12, sizes [1, 1, 1, 2, 1, 2, 1, 2, 1, 2, 1, 1]
```

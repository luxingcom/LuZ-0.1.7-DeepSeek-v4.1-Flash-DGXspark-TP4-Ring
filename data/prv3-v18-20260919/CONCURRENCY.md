# PR-v3 concurrency verdict — prv3-v18-20260919T234318 (chunk 8192)

Recomputed from the per-stream first-token instants in `raw/` by
`benchmarks/pr_v3_concurrency.py <this-dir>/raw 0.010 8192`. Method and
tolerance rationale are in that script's docstring.

Engine form at run time (from the head container launch args):
`--chunked-prefill-size 8192 --enable-mixed-chunk --prefill-decode-interval 4`.
Admission law: `min(C, max(1, floor(8192/input)))` — the baseline holds 27/40
exactly. 13 cells deviate, ALL in the arrival-dominated small-prompt band:
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
| 512 | 2 | 2 | **1** | 2 | 0.409 | 0.0 | NO |
| 512 | 4 | 4 | **3** | 2 | 0.713 | 0.0012 | NO |
| 512 | 8 | 8 | **7** | 2 | 1.734 | 0.0035 | NO |
| 512 | 16 | 16 | **10** | 3 | 2.32 | 0.0044 | NO |
| 2048 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 2048 | 2 | 2 | **1** | 2 | 0.653 | 0.0 | NO |
| 2048 | 4 | 4 | **3** | 2 | 2.025 | 0.0018 | NO |
| 2048 | 8 | 4 | **5** | 3 | 3.06 | 0.0035 | NO |
| 2048 | 16 | 4 | **5** | 4 | 3.446 | 0.0039 | NO |
| 4096 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 4096 | 2 | 2 | **1** | 2 | 0.956 | 0.0 | NO |
| 4096 | 4 | 2 | **2** | 3 | 1.85 | 0.001 | yes |
| 4096 | 8 | 2 | **3** | 4 | 2.723 | 0.0018 | NO |
| 4096 | 16 | 2 | **3** | 7 | 2.659 | 0.0032 | NO |
| 8192 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 8192 | 2 | 1 | **1** | 2 | 2.06 | 0.0 | yes |
| 8192 | 4 | 1 | **1** | 4 | 3.266 | 0.0 | yes |
| 8192 | 8 | 1 | **2** | 6 | 3.216 | 0.0018 | NO |
| 8192 | 16 | 1 | **2** | 12 | 3.195 | 0.0034 | NO |
| 16384 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 16384 | 2 | 1 | **1** | 2 | 2.099 | 0.0 | yes |
| 16384 | 4 | 1 | **1** | 4 | 2.772 | 0.0 | yes |
| 16384 | 8 | 1 | **1** | 8 | 3.078 | 0.0 | yes |
| 16384 | 16 | 1 | **1** | 16 | 4.415 | 0.0 | yes |
| 32768 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 32768 | 2 | 1 | **1** | 2 | 9.307 | 0.0 | yes |
| 32768 | 4 | 1 | **1** | 4 | 9.813 | 0.0 | yes |
| 32768 | 8 | 1 | **1** | 8 | 12.214 | 0.0 | yes |
| 32768 | 16 | 1 | **1** | 16 | 11.272 | 0.0 | yes |
| 65536 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 65536 | 2 | 1 | **1** | 2 | 20.012 | 0.0 | yes |
| 65536 | 4 | 1 | **1** | 4 | 25.305 | 0.0 | yes |
| 65536 | 8 | 1 | **1** | 8 | 17.863 | 0.0 | yes |
| 65536 | 16 | 1 | **1** | 16 | 24.45 | 0.0 | yes |
| 131072 | 1 | 1 | **1** | 1 | None | 0.0 | yes |
| 131072 | 2 | 1 | **1** | 2 | 51.292 | 0.0 | yes |
| 131072 | 4 | 1 | **1** | 4 | 54.966 | 0.0 | yes |
| 131072 | 8 | 1 | **1** | 8 | 56.363 | 0.0 | yes |
| 131072 | 16 | 1 | **1** | 16 | 51.191 | 0.0 | yes |

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

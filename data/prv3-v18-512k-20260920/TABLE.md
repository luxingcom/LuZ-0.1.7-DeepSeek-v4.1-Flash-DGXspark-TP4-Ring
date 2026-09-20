# PR-v3 — pure-prefill total-throughput matrix (v18/0.2.4)

One request = `max_tokens=1` (pure prefill; no decode tail). Fresh nonce per request; `/flush_cache` between cells. **total t/s = Σ(prompt tokens) / wall-clock from arm start to last stream end**.

| Cell | OK/Streams | Σ prompt tok | Wall s | **Total t/s** | median TTFT s | overlap peak | serialized |
|---|---:|---:|---:|---:|---:|---:|---|
| 524288-c1-w0 | 1/1 | 524288 | 232.27 | **2257.22** | 233.02 | 1 | serialized=⚠ |

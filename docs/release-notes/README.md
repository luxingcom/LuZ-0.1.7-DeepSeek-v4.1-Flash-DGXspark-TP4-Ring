# Release notes

| version | date | what it is | doc |
|---|---|---|---|
| **v0.2.9** | 2026-09-30 | Last stable build of the old base — the **EP1 enablement chain** (`EP_SIZE` 2→1, `DSV41_MOE_B12X` 1→0) plus the P1a adapter trio (`draft_head_fp8_tp4`, `hc_fused`, `draft_tau`) baked into the image; **c8 +4.0 % / c12 +4.8 %** decode, 262k/131k prefill flat inside boot noise, QA 17/0. Packaged artifact shipped (content identity `355a5e45cb2725ae`, **5 layers**) | [RELEASE-NOTES-v0.2.9.md](RELEASE-NOTES-v0.2.9.md) |
| v0.2.8 | 2026-09-24 | OOM-era engineering close-out (FIX-B/B', FIX-D, `mm_ban`, R2 grid, #40352 semantic backport, default off) — **pure increment, nothing reduced vs 0.2.4**; PR-v3 full 40-cell re-run (peak **5,823.11 t/s @65536×C2**, 512K single-stream **5,042.18 t/s**) + DE SD-1 20/20 cells positive, zero regressions; packaged artifact shipped (content identity `4cca364c46778423`) | [RELEASE-NOTES-v0.2.8.md](RELEASE-NOTES-v0.2.8.md) |
| v0.2.5 (`v19-40217prep`) | 2026-09-20 | #40217 minimal native port + engram stats v2; PR-v3 all 40 cells re-measured (peak 4,803.2 t/s @8192×C2, median +8.1% vs v18) | [RELEASE-NOTES-v0.2.5.md](RELEASE-NOTES-v0.2.5.md) |
| v0.2.4 (`v18`) | 2026-09-19/20 | MoE W4A16 → W4A8-MX production switch; PR-v3 40/40 + DE 20/20 + 512K single-stream re-baseline | [RELEASE-NOTES-v0.2.4.md](RELEASE-NOTES-v0.2.4.md) |
| v0.2.3 (`v14`) | 2026-09-19 | PR-v3 chunk-8192 full re-run (40/40), SD-1 board rewrite | [RELEASE-NOTES-v0.2.3.md](RELEASE-NOTES-v0.2.3.md) |

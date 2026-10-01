# Third-party components, licences and attribution

This file is the formal component manifest for this repository and for the published
serving image `dsv41-sglang-optimized:0.2.9-ep1q2-fin2`. It complements [`NOTICE`](NOTICE)
(inherited upstream attribution, kept verbatim) and [`LICENSE`](LICENSE) (AGPL-3.0-or-later
for this repository's own engineering work).

**How every row below was established.** Versions and licence strings were read out of the
running image, not from memory:

```bash
docker run --rm --entrypoint sh dsv41-sglang-optimized:0.2.9-ep1q2-fin2 -c \
  'python3 -c "
import importlib.metadata as md
for p in (\"sglang\",\"flashinfer-python\",\"torch\",\"triton\"):
    d=md.distribution(p)
    print(p, d.version, d.metadata.get(\"License-Expression\") or d.metadata.get(\"License\"))"'
```

Where a licence was declared only as a trove classifier, the classifier string is quoted.
Where a package ships a licence file, the file's first line is quoted. Rows that could not
be verified are marked as such — they are not guessed.

---

## 1. This repository's own work

| Scope | Licence |
|---|---|
| `start.sh`, `start-tp4.sh`, `stop.sh`, `boot.py`, `adapter/`, `scripts/`, `files/`, `runtime/` glue, `gateway/`, `bench/`, `benchmarks/`, `data/`, documentation | **AGPL-3.0-or-later** (see [`LICENSE`](LICENSE)) |

The AGPL choice is deliberate and was adjudicated: the upstream recipe this repository is
built on is AGPL-3.0-or-later, and this is a derived deployment of it. See
[`NOTICE`](NOTICE) and `docs/4DGX-DSV41-Flash-部署方案-20260911.md` §license chain.

## 2. Upstream lineage

| Component | Origin | Licence |
|---|---|---|
| SGLang serving recipe — `boot.py` skeleton, `benchmarks/`, `tests/`, the Engram row-store idea, the Docker layout | [`ntxf31415/DeepSeek-v4.1-Flash-DGX-Sparks`](https://github.com/ntxf31415/DeepSeek-v4.1-Flash-DGX-Sparks) (also published as [`MiaAI-Lab/DeepSeek-V4.1-Flash-DGX-Sparks`](https://github.com/MiaAI-Lab/DeepSeek-V4.1-Flash-DGX-Sparks)) | **AGPL-3.0-or-later** |
| Recipe skeleton / benchmark methodology | [`0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000`](https://github.com/0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000) | **MIT** — notice retained in [`LICENSE.upstream-MIT`](LICENSE.upstream-MIT) as that licence requires |
| Host ring-only NCCL 2.30.7 build + `libncclpin` core-pinning shim | [`luxingcom/aicad-nccl-optimization`](https://github.com/luxingcom/aicad-nccl-optimization) (LuZ lineage) | **Apache-2.0.** Host-side only — **not redistributed in this repository or in the image tar**. The licence file is read directly from that project: `LICENSE` (201 lines, "Apache License / Version 2.0"), added by commit `894719d` on **2026-09-20** alongside a NOTICE reading "Copyright 2026 luxingcom". An earlier revision of this row said "no licence declared" — that was true when the operator ledger first recorded it (2026-09-19) and false from the next day onward; the lineage project's own README also carries the Apache-2.0 badge |
| Model weights | `deepseek-ai/DeepSeek-V4.1-Flash` (Hugging Face) | see the model card. **Not redistributed here.** |

### 2.1 Files adapted from vLLM — newly recorded

Two files in `sglang-overlay/` carry vLLM provenance in their headers. This was not
reflected in any attribution file before now:

| File | Header | Licence |
|---|---|---|
| [`sglang-overlay/roce_parallel_state.py`](sglang-overlay/roce_parallel_state.py) | `SPDX-FileCopyrightText: Copyright contributors to the vLLM project` / `Adapted from …/vllm/distributed/parallel_state.py` | **Apache-2.0** (SPDX declared in the file) |
| [`sglang-overlay/roce_pynccl.py`](sglang-overlay/roce_pynccl.py) | `SPDX-FileCopyrightText: Copyright contributors to the vLLM project` / `Adapted from …/vllm/distributed/device_communicators/pynccl.py` | **Apache-2.0** (SPDX declared in the file) |

> The paths in the first column are the names **as they exist in this repository**; the
> upstream module names (`parallel_state.py` / `pynccl.py`) appear only inside each file's
> own `Adapted from …` URL. An earlier draft of this table linked the upstream names, which
> resolved to nothing here (`scripts/check_relative_links.py` reported both). A licence
> notice that 404s is still a notice, but it is not a *checkable* one — hence this note.

The Apache-2.0 text that governs them is the same text shipped as
[`LICENSE.sglang`](LICENSE.sglang) (Apache-2.0 is not per-project), so no additional
licence file is required by §4 of that licence; the copyright notice is retained in each
file's own header.

## 3. Software redistributed inside the image

These are present in the image tar. The image tar is the thing being distributed, so their
notices travel with it.

| Component | Version (as verified in the image) | Licence |
|---|---|---|
| **SGLang** | `0.0.0.dev1+gda64c5cbb` — commit `da64c5cbb8cf6bfd39be19da43573fdfd484c43a` | **Apache-2.0** (trove classifier `License :: OSI Approved :: Apache Software License`; `/sgl-workspace/sglang/LICENSE` first line: `Apache License / Version 2.0`) |
| **sglang-kernel** | `0.4.6.post1` | **Apache-2.0** (`License:` field begins `Apache License`) |
| **sgl-deep-gemm** | `0.1.7` | **Apache-2.0** (shipped `LICENSE`, first line `Apache License / Version 2.0`) |
| **FlashInfer** (`flashinfer-python`, `flashinfer-cubin`, `flashinfer-jit-cache`) | `0.6.18` / `0.6.18` / `0.6.18+cu130` | **Apache-2.0** |
| **b12x** — vendored under `b12x-site/` (261 files) and at `/opt/b12x` in the image | `1.3.0`, author *Luke Alonso* | **Apache-2.0** (`License-Expression: Apache-2.0`; `b12x-1.3.0.dist-info/licenses/LICENSE` = the Apache text) |
| **PyTorch** | `2.13.0+cu130` | **Apache-2.0** *and* Apache-2.0 WITH LLVM-exception *and* BSD-2-Clause (composite, as declared) |
| **Triton** | `3.7.1` | **MIT** |
| **transformers** | `5.12.1` | **Apache-2.0** |
| **cuda-python** | `13.4.1` | **Apache-2.0** |
| **apache-tvm-ffi** | `0.1.11` | **Apache-2.0** |
| **outlines** | `0.1.11` | **Apache-2.0** |
| **pydantic** | `2.13.5` | **MIT** |
| **fastapi** | `0.141.1` | **MIT** |
| **uvicorn** | `0.52.4` | **BSD-3-Clause** |
| **NumPy** | `2.3.5` | **BSD-3-Clause** (declared as a `Copyright (c) 2005-2025, NumPy Developers … Redistribution` block) |
| **NCCL** (host ring-only build, `/opt/nccl-ringonly/libnccl.so.2.30.7`) | `2.30.7` | NVIDIA NCCL licence (see the NVIDIA redistribution terms bundled with NCCL). The algorithm-matrix patch is the LuZ lineage change described in `BUILD-IDENTITY.md` |

> **`LICENSE.sglang` is verifiably the SGLang licence text.** `md5sum` of the Apache text
> shipped in this repository equals the `md5sum` of the text inside the image:
> `be8aa0c6ee216b5b4a50d9c20130c77b` for both. That is a checkable claim, not an assertion.
>
> ```bash
> md5sum LICENSE.sglang
> docker run --rm --entrypoint sh dsv41-sglang-optimized:0.2.9-ep1q2-fin2 \
>   -c 'md5sum /sgl-workspace/sglang/LICENSE'
> ```

## 4. Dependencies with restrictive terms — read this if you redistribute

| Component | Version | Licence | Why it matters |
|---|---|---|---|
| **`nvidia-cutlass-dsl`** and its `-libs-*` companions | `4.6.2` | **NVIDIA Software License Agreement — proprietary**, *not* Apache-2.0. Verified: `License-Expression` is absent; the trove classifier reads `License :: Other/Proprietary License`; the shipped `LICENSE` begins *"NVIDIA Software License Agreement … This Agreement can be accepted only by an adult of legal age of majority…"* | b12x imports `cutlass`, `cutlass.cute`, `cutlass.pipeline` and `cutlass.utils` at module level (e.g. `b12x/_lib/dense_gemm.py`), so **the b12x kernels in this image cannot run without it.** b12x's *own* code is Apache-2.0; the DSL it is built on is not. If you redistribute this image or a derivative, **NVIDIA's terms — not Apache-2.0 — govern that component**, and Apache-2.0's patent grant does not extend to it. |

This is the one row that can genuinely constrain a downstream redistribution, so it is
called out rather than left inside a table. It does **not** change the licence of b12x's
own source, which stays Apache-2.0.

## 5. Not redistributed, but required to run

| Item | Note |
|---|---|
| Model weights (`deepseek-ai/DeepSeek-V4.1-Flash`) | obtained separately; this repository and image carry none |
| NVIDIA driver `580.173.02`, CUDA 13.0 runtime | NVIDIA terms; host-side |
| `nvidia-cutlass-dsl` | see §4 — present in the image, proprietary |

## 6. Known documentation defect (recorded, not silently fixed)

[`NOTICE`](NOTICE) line 1 reads **"DeepSeek-V4.1-Flash on 3x NVIDIA DGX Spark"**. This
repository and the deployment it describes are **4×** DGX Spark (`README.md` §1:
*"4× NVIDIA DGX Spark (GB10) wired as a switchless RoCE ring"*; `.env.tp4.example` defines
3 workers + 1 head = 4 ranks).

The `NOTICE` file is **inherited upstream text** — it credits `zurih` and describes the
upstream recipe's own scope, and upstream publishes itself as *"3-4x NVIDIA DGX Spark"*.
Editing an inherited copyright statement to match our topology would rewrite someone else's
attribution. It is therefore **left verbatim and flagged here instead**. If the intent is
for `NOTICE` to describe *this* deployment, that is a deliberate decision to take — not a
typo to correct in passing.

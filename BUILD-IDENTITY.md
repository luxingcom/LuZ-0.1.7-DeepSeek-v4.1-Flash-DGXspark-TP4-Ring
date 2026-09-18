# Build identity — what the fleet actually runs

Use this to tell whether *your* build is the same one the `[measured]` numbers in
`.env.tp4.example`, the READMEs and `docs/03-final-metrics/` came from.

---

## Images

| | value |
|---|---|
| Production tag | **`dsv41-sglang-optimized:v7`** |
| **Content identity — the acceptance value** | **`4ebef21b6aedbd70`** (identical on all four nodes) |
| Content identity, full | `4ebef21b6aedbd70d5a2563ab512c31a85fc3b3e221c3b2beac6a9d06e2c12c1` |
| RootFS layer count | 123 (identical on all four nodes) |
| `Config` field hash (all four nodes) | `77799e6ce3de5824` |
| Reported image ID — node 01 (head) | `sha256:03587ce92d08be1a1a567fe20d350ee6d0d620785fe8089b385b37331e064cc4` |
| Reported image ID — nodes 02/03/04 | `sha256:9e1036bc6a106e76c90b639c572d7171d3ef466a3df0746700035b64a1692082` |
| Base image | `lmsysorg/sglang:dev-dsv41`, 70 layers — present on **01 and 02 only**. 01 = `sha256:4a5d132a06a77c8331e15845f2e925adc788b00105097ad55409afa3f4fa4860`, 02 = `sha256:381b27ffa19bfbade2bf69bb103395e59a7e82ab0adf176b15b492e9df5aaf7b` (same 70 layers, different reported ID). **Absent on 03/04.** |
| Registry digest | **`<none>`** for both — the overlay is built locally and shipped by `docker save` / `docker load`, never pushed to a registry, so `docker images --digests` shows none either |

**The reported image ID is *not* expected to match across nodes — but the content is.**
Measured: the head reports `03587ce9…` and the workers report `9e1036bc…`, yet on all
four nodes the rootfs layer list, the `Config` section, the creation timestamp and every
`org.dsv41.*` label are **byte-hash-identical** (`.Config` → `77799e6ce3de5824`,
`.RootFS` → `cdd980943dfe9e6b`, `.Created` → `0203e92cacf2a896` on all four).

The mechanism is a **storage-driver split plus a two-object DAG, not a content
difference**. The head runs the containerd `overlayfs` snapshotter while the workers run
classic `overlay2` (also recorded in `start.sh:772-776`), and — measured against the
release archive itself — the two IDs are **different objects inside the same archive**,
each sha256-consistent with its own bytes:

| reported `.Id` | what it is in the archive | size |
|---|---|---|
| node 01 `03587ce9…` | the **OCI image-index blob** referenced by `index.json` — the key containerd's image store uses | 857 B |
| nodes 02-04 `9e1036bc…` | the **image-config blob** referenced by the image manifest — what classic `overlay2` docker reports | 81,769 B |

Both are reachable from `index.json` in one graph; neither describes content. The diffID
list does. Verify content, not IDs.

> ⚠️ **Do not use layer count or image ID as an acceptance criterion.** This fleet also
> carries a rollback-anchor tag (`dsv41-4x-spark:local`) whose **tag is reused across
> builds — three different contents across four nodes**. Compare the content identity and
> the fingerprints below instead.

**Other images present on the hosts, NOT current:** `dsv41-4x-spark:local` (rollback
anchor, tag reused across builds), `dsv41-4x-spark:flat` (absent on node 02),
`lmsysorg/sglang:dev-dsv41` (base), and the `dsv41-sglang-optimized:v1…v6` lineage.

---

## Content fingerprints (per-file identity)

```bash
docker run --rm --entrypoint sh dsv41-sglang-optimized:v7 -c \
  'md5sum /opt/dsv41/boot.py \
          /opt/dsv41/adapter/librow_store.so \
          /sgl-workspace/sglang/python/sglang/kernels/ops/attention/flash_mla_sm120.py'
```

| file | md5 (v7) |
|---|---|
| `/opt/dsv41/boot.py` | `a7381d95d1560a3b2363a34d222df064` |
| `/opt/dsv41/adapter/librow_store.so` | `1f820aef687d0f9685c0e4b51585ece6` |
| `…/kernels/ops/attention/flash_mla_sm120.py` | `d91b0cda319e8a9b57e73e71020fb7bb` |

### How to compute the content identity

This is the **same formula `start.sh` uses** (`IMGID_TPL` at `start.sh:777` +
`img_content_id()` at `start.sh:778`), so the value below is exactly what
`image_preflight()` asserts across the fleet:

```bash
docker image inspect -f '{{join .RootFS.Layers " "}}' dsv41-sglang-optimized:v7 \
  | sha256sum | cut -c1-16
# measured on all four nodes: 4ebef21b6aedbd70
```

> ⚠️ **The formula is byte-exact — publish it together with the value.** `docker image
> inspect -f` emits the joined layer list **with a trailing newline**, and that newline is
> part of the hashed input. Hashing the *same* 123-entry list under five different
> serializations yields five different 16-hex strings, all of them correct hashes of a
> real serialization of the real layer list:
>
> | hashed byte stream | sha256[:16] |
> |---|---|
> | space-joined + trailing `\n` ← **authoritative** (`{{join .RootFS.Layers " "}}` piped to `sha256sum`) | **`4ebef21b6aedbd70`** |
> | space-joined, no trailing newline | `bb7c2d4b38af0514` |
> | newline-joined, no trailing newline | `c8751accc458138c` |
> | newline-joined + trailing newline | `38bbe8265458f328` |
> | newline-joined + two trailing newlines | `0050285e87c6f408` |
>
> All five were re-derived **offline from the release archive** by
> `scripts/verify_release_artifact.py`. **The defect to avoid is not "hashing the wrong
> thing" — it is publishing a hash without its byte-exact pipeline**, which makes several
> different quantities look like competing claims about one quantity. Only
> `4ebef21b6aedbd70` is asserted by production code, so only it is *the* identity.

> ⚠️ **Empty-input trap (this pipeline fails *open*, not closed).** If the image is
> absent, `docker image inspect` writes nothing to stdout and exits non-zero — but the
> pipeline still prints a **well-formed-looking** hash:
>
> | input | sha256 (first 16) |
> |---|---|
> | no stdout at all | `e3b0c44298fc1c14` |
> | a single newline (what the template emits for a missing image) | `01ba4719c80b6fe9` |
>
> So `01ba4719c80b6fe9` is what a **missing** image looks like — it is *not* an identity.
> Any consumer must (a) assert image existence **before** hashing, and (b) blacklist
> both constants. `start.sh` does both (`image_preflight()` step ③); the comment at
> `start.sh:814-819` records why. Note the same constant also appears when
> `docker image inspect -f` is asked for an empty field: **one value, two sources.**

> ⚠️ **One orphan.** `e541746d26e31a3f` — carried in this repo as "layers-json sha256" —
> is reproduced by **none** of the 32 candidate serializations tested against the release
> archive: not any serialization of the diffID list, not the image config blob, not either
> manifest, not `index.json`, not the compressed-layer list. No production script asserts
> it either. Most likely it belongs to an image revision from **before** the redaction
> rebuild. Treat it as **unverifiable**, not as a wrong number — and never as an
> acceptance criterion.

### Additional build anchors carried by the image

These are stamped into the image config at build time and are identical on all four
nodes — useful as a second, independent check:

| label / env | value |
|---|---|
| `org.dsv41.built_at` | `2026-09-17T00:40:26+00:00` |
| `org.dsv41.overlay_files` | `41` (must equal the number of `SGLANG_OVERLAY_MAP` entries in *your* `start.sh`) |
| `org.dsv41.overlay_map_md5` | `f0a10321907b` |
| `org.dsv41.source` | `start.sh:SGLANG_OVERLAY_MAP` |
| `ai.sglang.build.commit` / `SGLANG_BUILD_COMMIT` | `da64c5cbb8cf6bfd39be19da43573fdfd484c43a` |
| `SGLANG_IMAGE_TAG` | `lmsysorg/sglang:dev-dsv41` |
| `Entrypoint` / `WorkingDir` | `["python3","-u","/opt/dsv41/boot.py"]` / `/opt/dsv41` |

`start.sh`'s preflight compares `org.dsv41.overlay_files` against the local map length
and warns on mismatch — a cheap way to catch "the image was baked from a different
overlay set than this checkout".

---

## Software stack (inside the production image)

| Component | Version |
|---|---|
| SGLang | `0.0.0.dev1+gda64c5cbb` — **commit `da64c5cb`** |
| FlashInfer | `0.6.18` (`flashinfer-python`) |
| PyTorch | `2.13.0+cu130` (CUDA 13.0) |
| Grammar backend | `xgrammar` |
| Attention backend | `dsv4` (`--attention-backend dsv4`) |
| MoE runner | `flashinfer_mxfp4` |
| FP8 GEMM runner | `flashinfer_cutlass` |

> The local rollback-anchor image `dsv41-4x-spark:local` was built from SGLang commit
> **`e087e662b`**. Kernels are **not** interchangeable between the two commits; if a
> document names `e087e662b` it is describing that earlier build.

**Model**: `deepseek-ai/DeepSeek-V4.1-Flash` at `/models/DeepSeek-V4.1-Flash` inside the
image. From its `config.json`: 40 layers, hidden 5120, `num_attention_heads` 64,
`num_key_value_heads` 1, `head_dim` 512, `q_lora_rank` 1280, `o_lora_rank` 1024,
384 routed experts/layer at `moe_intermediate_size` 2304 with top-6 routing plus 1
shared expert, `vocab_size` 129280, `max_position_embeddings` 1048576 (YaRN, factor 16
over a 65536 original window), expert weights `fp4` inside an `fp8` checkpoint.
Parameter count computed from this config: **≈550 B total** (543.6 B routed experts
+ 1.4 B shared + ~3.7 B attention + 1.3 B embed/head).

---

## Host stack (all four nodes identical)

| | value |
|---|---|
| GPU | NVIDIA GB10 (SM121) |
| Unified memory per node | **121.63 GiB** (Grace–Blackwell UMA: host RAM and device memory are one pool) |
| Driver | `580.173.02` |
| CUDA | 13.0 |
| Kernel | `6.17.0-1031-nvidia` |
| NCCL (host, ring-only) | `/opt/nccl-ringonly/libnccl.so.2.30.7` — **LuZ lineage**, 2.30.7 |

The NCCL is the LuZ ring-only build, *not* a sparkring patched library: it contains
neither `SWITCHLESS_RING_ONLY` nor `SKIP_TREE_CONNECT` and achieves ring-only by
disabling the Tree algorithm in NCCL's algorithm matrix (`Tree=0 / Ring=1` for all five
collectives) rather than by skipping the tree transport connect.
`scripts/nccl_selfcheck.sh` identifies which lineage a given library is.

> **UMA consequence you must know about.** Because host RAM and device memory are the
> same pool, device allocations made outside the container's cgroup are **not** visible
> to cgroup accounting, and `OOMKilled=false` is therefore *expected* even during a
> fatally over-committed run. The only precise device-side channel is
> `nvidia-smi --query-compute-apps`. Do not conclude "no OOM happened" from
> cgroup counters.
>
> A second consequence, for measurement: because the pool is shared, `eff_free`
> (`MemFree + Cached + SReclaimable − Shmem`) sits at **6.8–9.9 GiB while the engine is
> resident** and stays flat there. The 110 GiB figure the launch gate (`oom_gate pre -t
> 110`) uses is a **pre-launch admission** threshold, not a steady-state health line.
> Comparing a steady-state reading against it produces false alarms in both directions.

---

## Runtime configuration actually in force

Full launch line, read out of the running container's `/proc/<pid>/cmdline` (flag order
preserved; the head's real ring address is shown as `<head-ring-ip>`):

```
--model-path /models/DeepSeek-V4.1-Flash  --served-model-name deepseek-v4.1-flash
--trust-remote-code  --load-format safetensors
--tp 4  --ep-size 2  --attention-backend dsv4  --moe-runner-backend flashinfer_mxfp4
--mem-fraction-static 0.90  --chunked-prefill-size 4096
--context-length 600000  --max-running-requests 16  --cuda-graph-max-bs-decode 16
--random-seed 0  --enable-decoder-swa-bounded-replay
--tool-call-parser deepseekv41  --reasoning-parser deepseek-v41
--host 127.0.0.1  --port 8899
--speculative-algorithm DSPARK  --speculative-dspark-block-size 5
--nnodes 4  --node-rank <n>  --dist-init-addr <head-ring-ip>:20000
--max-total-tokens 9600000  --fp8-gemm-backend flashinfer_cutlass
--watchdog-timeout 1800  --enable-metrics  --min-free-slots-delay 1
--enable-deepseek-v4-fp4-indexer  --api-key <redacted>
```

`--served-model-name` is the **engine-side** name. Do not confuse it with the names
exposed by the client-facing gateway — four distinct name strings are in play (image tag,
gateway alias, engine self-report, upstream probe) and they are not interchangeable.

Resulting engine state, as reported by the engine on startup:
`max_total_num_tokens=9600000, context_len=600000, max_running_requests=16`,
`kv_cache_dtype=fp8_e4m3`.

Notable environment gates (full list in `.env.tp4.example`):

| variable | value |
|---|---|
| `EP_SIZE` | `2` |
| `DSV41_CACHE_GIB` / `DSV41_CACHE_WAYS` | `1` / `16` |
| `DSV41_SHARED_PAD_K` | `1` |
| `DSV41_MOE_B12X` / `_CAPS` / `_QUANT` | `1` / `128,256,512,1024,2304,4096` / `a8` |
| `DSV41_MXFP8_BACKEND` | `b12x` |
| `SGLANG_DSV4_KV_LAYOUT` | `fork-v4-fp4` |
| `SGLANG_RAGGED_VERIFY_MODE` | `static` |
| `NCCL_ALGO` / `NCCL_IB_GID_INDEX` | `RING` / `3` |
| `NCCL_MIN_NCHANNELS` / `NCCL_MAX_NCHANNELS` | `4` / `4` |

---

## Release artifact

| | value |
|---|---|
| File | `LuZ-0.1.7-DSV41F-image.tar.zst` |
| Size | 14,463,467,578 bytes (13.5 GiB) |
| MD5 | `10307040cd70ab23436bf34eee829d24` — recomputed over the local artifact copy; byte count and hash both match |
| Produced by | `docker save dsv41-sglang-optimized:v7 \| zstd -T0` on node 01. Because that node uses the containerd image store, the result is an **OCI layout** (`oci-layout`, `index.json`, `manifest.json`, `blobs/sha256/*`), not the plain `<layer>/layer.tar` form |
| Tar anatomy | 128 members = **123 blobs** + `index.json` + `manifest.json` + `oci-layout` + 2 directory entries. Payload 14,686,175,317 bytes (uncompressed) |
| Internal integrity | **all 123 blobs verified**: `sha256(bytes) == its own filename` ⇒ the archive is a self-consistent content-addressed store, nothing truncated |
| Reference closure | **0 unreferenced blobs** — every blob member is reachable from `index.json` |
| Content graph | `index.json` → OCI index `03587ce9…` (857 B) → { **image manifest** `be741c20…` (23,717 B, arm64/linux, 123 layers, config `9e1036bc…`), docker **attestation manifest** `4ca1fb49…` (566 B, SBOM/provenance, config `eed6883c…`, 1 layer) }. Budget: 5 metadata blobs + 118 layer blobs (117 image + 1 attestation) = 123 |
| Layer anatomy | 123 diffIDs, **117 distinct**; `sha256:5f70bf18…` (an empty tar = 1024 NUL bytes) appears **7×** ⇒ 6 of the 123 layers carry no content. The config's `history` marks 108 of its 231 steps `empty_layer` |
| **Offline reproduction** | the archive **reproduces content identity `4ebef21b6aedbd70` with no cluster, no docker daemon and no GPU** — see `scripts/verify_release_artifact.py` |

The identity is therefore re-derivable from the artifact alone:

```bash
pip install zstandard
python scripts/verify_release_artifact.py LuZ-0.1.7-DSV41F-image.tar.zst --md5
# md5 MATCH · 123/123 blobs verified · 0 unreferenced
# content identity 4ebef21b6aedbd70  (full: 4ebef21b6aedbd70d5a2563ab512c31a85fc3b3e221c3b2beac6a9d06e2c12c1)
# RESULT: PASS   (exit 0)
```

The script is fail-closed: a missing file, a truncated archive, an unreferenced blob or a
mismatch exits non-zero and never prints a plausible-looking hash. Its recorded run output
and the full blob manifest are published under
[`data/release-artifact-20260918/`](data/release-artifact-20260918/) so the run can be
checked without re-downloading 13.5 GiB.

After loading, the image must report content identity **`4ebef21b6aedbd70`** and 123
layers. (The downloaded artifact and the four production nodes are the same content; only
the *reported* image ID varies — see the two-object DAG at the top of this file.)

Load on all four nodes (workers need the image too):

```bash
docker load -i LuZ-0.1.7-DSV41F-image.tar.zst   # requires zstd; restores dsv41-sglang-optimized:v7
```

---

## Verification recipe

```bash
# 0. OFFLINE — verify the downloaded archive before loading it anywhere.
#    No cluster, no docker daemon, no GPU required.
pip install zstandard
python scripts/verify_release_artifact.py LuZ-0.1.7-DSV41F-image.tar.zst --md5
# expect: md5 MATCH · 123/123 blob sha256 verified · 0 unreferenced blobs
#         content identity 4ebef21b6aedbd70 · RESULT: PASS  (exit 0)

# 1. content identity — the single fleet-wide acceptance value.
#    Assert presence FIRST: a missing image yields 01ba4719c80b6fe9, not an error.
for h in node01 node02 node03 node04; do   # your node aliases: head + 3 workers
  echo "--- $h"
  ssh "$h" 'docker image inspect dsv41-sglang-optimized:v7 >/dev/null 2>&1 || { echo "  ABSENT"; exit 0; }
            printf "  id     %s\n" "$(docker image inspect -f "{{join .RootFS.Layers \" \"}}" dsv41-sglang-optimized:v7 | sha256sum | cut -c1-16)"
            printf "  layers %s\n" "$(docker image inspect -f "{{len .RootFS.Layers}}" dsv41-sglang-optimized:v7)"'
done
# expect, per node: id 4ebef21b6aedbd70 / layers 123

# 2. content fingerprints — run on every node and compare the three md5s
for h in node01 node02 node03 node04; do   # your node aliases: head + 3 workers
  ssh "$h" docker run --rm --entrypoint sh dsv41-sglang-optimized:v7 -c \
    'md5sum /opt/dsv41/boot.py /opt/dsv41/adapter/librow_store.so \
            /sgl-workspace/sglang/python/sglang/kernels/ops/attention/flash_mla_sm120.py'
done

# 3. software stack
docker run --rm --entrypoint sh dsv41-sglang-optimized:v7 -c \
  'python -c "import sglang,flashinfer,torch;print(sglang.__version__,flashinfer.__version__,torch.__version__)"'
# expect: 0.0.0.dev1+gda64c5cbb 0.6.18 2.13.0+cu130

# 4. build anchors stamped into the config
docker image inspect dsv41-sglang-optimized:v7 --format \
  '{{index .Config.Labels "org.dsv41.overlay_files"}} {{index .Config.Labels "org.dsv41.overlay_map_md5"}} {{index .Config.Labels "org.dsv41.built_at"}}'
# expect: 41 f0a10321907b 2026-09-17T00:40:26+00:00

# 5. NCCL lineage
scripts/nccl_selfcheck.sh
```

> Checks 0–5 are the acceptance set. **RootFS layer counts and reported image IDs are
> not** valid pass/fail criteria (see the warnings above), and an identity computation
> returning `01ba4719c80b6fe9` or `e3b0c44298fc1c14` means **the image is missing**, not
> that it mismatches.
>
> Check 0 needs nothing but the archive, so it is the one to run **first** and the only one
> a reader without cluster access can run at all. Letting a distribution be verified
> offline turns "trust the publisher's hash" into "re-derive the publisher's number",
> which is the whole point of publishing it.

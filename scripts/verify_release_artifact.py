#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_release_artifact.py — verify the shipped image archive WITHOUT a cluster,
a docker daemon, or a GPU.

    pip install zstandard        # only needed for the .tar.zst artifacts
    python verify_release_artifact.py LuZ-0.2.8-dsv41-tp4-dgxspark.tar --md5
    python verify_release_artifact.py LuZ-0.2.4-dsv41-tp4-dgxspark.tar.zst --md5

What it proves, in order:

  1. the tar is a complete, self-consistent content-addressed store
     (every blob member's sha256 == its own filename  => nothing truncated)
  2. the reference graph closes (every blob member is referenced by the DAG)
  3. the *content identity* -- sha256[:16] of the rootfs diffID list, serialized
     exactly as `docker image inspect -f '{{join .RootFS.Layers " "}}'` emits it --
     equals the value `start.sh`'s image_preflight() asserts fleet-wide
  4. every other digest that has ever been published as "the image identity" for
     this build is accounted for as a *different serialization of the same list*
     (or reported as an orphan)

Exit status is 0 only if the content identity matches EXPECTED and every blob
verifies. The pipeline deliberately fails CLOSED: a missing file, a truncated
archive, a blob mismatch, an unknown artifact with no explicit expectation, or a
false-empty constant is an error — never a plausible-looking hash.

Artifact profiles (expected identity / md5 / layer count):

    LuZ-0.2.9-dsv41-tp4-dgxspark.tar      355a5e45cb2725ae  (5 layers, raw tar)
    LuZ-0.2.8-dsv41-tp4-dgxspark.tar      4cca364c46778423  (3 layers, raw tar)
    LuZ-0.2.4-dsv41-tp4-dgxspark.tar.zst  4ebef21b6aedbd70  (123 layers, zstd)
    LuZ-0.1.7-DSV41F-image.tar.zst        4ebef21b6aedbd70  (123 layers, zstd;
                                          the pre-rename distribution of the
                                          same 0.2.4-era content)

For an artifact this script does not know, pass --expect-identity HEX (and
--expect-md5 HEX if you want the md5 checked); without either it refuses to
print a verdict rather than guessing an expectation.

Flags:
    --md5              also compute the file md5 (reads the file twice; ~30-60 s
                       on 14 GB) and compare with the profile / --expect-md5
    --expect-md5 HEX   override the profile's md5
    --expect-identity HEX   override the profile's content identity
    --json PATH        write the machine-readable audit result
    --blob-manifest PATH   write all tar members with sizes (evidence trail)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import time
from collections import Counter

# constants that mean "nothing was there" -- must never be accepted as an identity
FALSE_EMPTY = {
    "e3b0c44298fc1c14": "sha256(b'')",
    "01ba4719c80b6fe9": "sha256(b'\\n')",
}

# per-artifact expected values, keyed by basename.
# The identity is ALWAYS `sha256(join(diff_ids, " ") + "\n")[:16]` -- the formula
# start.sh's IMGID_TPL emits -- regardless of archive compression.
PROFILES = {
    "LuZ-0.2.9-dsv41-tp4-dgxspark.tar": {
        "identity": "355a5e45cb2725ae",
        # registered from the release audit; see this file's module
        # docstring note -- not re-measured by this edit.
        "md5": "3562a789ec0e9aa4bc80a7e54ba1be65",
        "layers": 5,
        "compression": "none",
    },
    "LuZ-0.2.8-dsv41-tp4-dgxspark.tar": {
        "identity": "4cca364c46778423",
        "md5": "a9d4cdf932203f173df7556aa511fee1",
        "layers": 3,
        "compression": "none",
    },
    "LuZ-0.2.4-dsv41-tp4-dgxspark.tar.zst": {
        "identity": "4ebef21b6aedbd70",
        "md5": "9daeb2ba314a1380988ed6f8afbe4657",
        "layers": 123,
        "compression": "zstd",
    },
    "LuZ-0.1.7-DSV41F-image.tar.zst": {
        "identity": "4ebef21b6aedbd70",
        "md5": "10307040cd70ab23436bf34eee829d24",
        "layers": 123,
        "compression": "zstd",
    },
}

SMALL = 4 << 20


def h16(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def md5_file(path: str, chunk: int = 1 << 22) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def detect_compression(path: str) -> str:
    """zstd streams start with the magic 28 B5 2F FD; anything else is raw tar."""
    with open(path, "rb") as fh:
        magic = fh.read(4)
    return "zstd" if magic == b"\x28\xb5\x2f\xfd" else "none"


def scan(path: str, compression: str):
    """Single streaming pass: keep small members, hash every member."""
    members = []
    small = {}
    failures = []
    fh = open(path, "rb")
    st = fh
    zr = None
    if compression == "zstd":
        try:
            import zstandard
        except ImportError:  # pragma: no cover
            fh.close()
            sys.stderr.write("missing dependency for .tar.zst: pip install zstandard\n")
            raise SystemExit(2)
        zr = zstandard.ZstdDecompressor().stream_reader(fh, read_size=1 << 22)
        st = zr
    try:
        tf = tarfile.open(fileobj=st, mode="r|")
        for m in tf:
            members.append((m.name, m.size, m.type))
            if not m.isfile():
                continue
            base = m.name.rsplit("/", 1)[-1]
            is_blob = m.name.startswith("blobs/sha256/") and len(base) == 64
            if m.size < SMALL:
                data = tf.extractfile(m).read()
                small[m.name] = data
                if is_blob and hashlib.sha256(data).hexdigest() != base:
                    failures.append(m.name)
            elif is_blob:
                h = hashlib.sha256()
                src = tf.extractfile(m)
                for blk in iter(lambda: src.read(1 << 22), b""):
                    h.update(blk)
                if h.hexdigest() != base:
                    failures.append(m.name)
    finally:
        if zr is not None:
            zr.close()
        fh.close()
    return members, small, failures


def blob(digest: str) -> str:
    return "blobs/sha256/" + digest.split(":", 1)[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("--md5", action="store_true")
    ap.add_argument("--expect-md5", default=None)
    ap.add_argument("--expect-identity", default=None)
    ap.add_argument("--json")
    ap.add_argument("--blob-manifest")
    ap.add_argument("--layer-chain", action="store_true",
                    help="additionally gunzip every layer blob and assert its decompressed "
                         "sha256 equals the config's diff_id (reads the archive a second time)")
    a = ap.parse_args()

    if not os.path.isfile(a.archive):
        sys.stderr.write("FAIL: no such file: %s\n" % a.archive)
        return 1

    base = os.path.basename(a.archive)
    prof = PROFILES.get(base)
    expect_identity = a.expect_identity or (prof and prof["identity"])
    expect_md5 = a.expect_md5 or (prof and prof["md5"])
    if not expect_identity:
        sys.stderr.write(
            "FAIL: unknown artifact %r and no --expect-identity given.\n"
            "      Known profiles: %s\n"
            "      Refusing to print a verdict against a guessed expectation.\n"
            % (base, ", ".join(sorted(PROFILES)))
        )
        return 1

    size = os.path.getsize(a.archive)
    compression = detect_compression(a.archive)
    out = {
        "archive": base,
        "bytes": size,
        "compression": compression,
        "expected": expect_identity,
    }

    print("=" * 74)
    print("FILE")
    print("=" * 74)
    print("  path              :", a.archive)
    print("  bytes             : {:,}".format(size))
    print("  compression       : %s%s" % (compression, "  (profile)" if prof else "  (no profile)"))
    if prof:
        print("  profile           : identity %s | layers %s | md5 %s"
              % (prof["identity"], prof["layers"], prof["md5"]))
    md5 = None
    if a.md5:
        if not expect_md5:
            sys.stderr.write("FAIL: --md5 asked but no expected md5 (no profile, no --expect-md5)\n")
            return 1
        t = time.time()
        md5 = md5_file(a.archive)
        ok = (md5 == expect_md5)
        print("  md5               : %s   (%s, %.1fs)"
              % (md5, "MATCH" if ok else "MISMATCH expected " + expect_md5, time.time() - t))
        out["md5"] = md5
        out["md5_ok"] = ok
        if not ok:
            sys.stderr.write("FAIL: archive md5 mismatch\n")
            return 1
    print()

    t0 = time.time()
    members, small, failures = scan(a.archive, compression)
    print("=" * 74)
    print("1. INTEGRITY  (single streaming pass, %.1fs)" % (time.time() - t0))
    print("=" * 74)
    blobs = [n for n, s, t in members if n.startswith("blobs/sha256/") and t == tarfile.REGTYPE]
    print("  tar members       : {}".format(len(members)))
    print("  blob members      : {}".format(len(blobs)))
    print("  payload bytes     : {:,}".format(sum(s for n, s, t in members)))
    print("  blob hash failures: {}".format(len(failures)))
    out["tar_members"] = len(members)
    out["blob_members"] = len(blobs)
    out["blob_hash_failures"] = failures
    if failures:
        for n in failures[:10]:
            print("      MISMATCH", n)
        sys.stderr.write("FAIL: blob integrity\n")
        return 1
    print("  => every blob member's sha256 equals its own filename")
    print("     the archive is a self-consistent store; nothing truncated")
    print()

    # ---------------- 2/3. DAG ----------------
    missing = [k for k in ("index.json", "manifest.json") if k not in small]
    if missing:
        sys.stderr.write("FAIL: archive is not a docker-save/OCI layout (missing %s)\n" % missing)
        return 1

    print("=" * 74)
    print("2. REFERENCE GRAPH")
    print("=" * 74)
    idx = json.loads(small["index.json"])
    top = blob(idx["manifests"][0]["digest"])
    nested = json.loads(small[top])
    refs = {top}
    layer_refs = set()
    print("  index.json         : OCI index, %d descriptor(s) -> index blob %s"
          % (len(idx["manifests"]), top.rsplit('/', 1)[-1][:16]))
    kinds = []
    for ent in nested["manifests"]:
        b = blob(ent["digest"])
        if b not in small:
            sys.stderr.write("FAIL: referenced blob absent: %s\n" % b)
            return 1
        man = json.loads(small[b])
        cfg = blob(man["config"]["digest"])
        refs.add(b)
        refs.add(cfg)
        ls = [blob(l["digest"]) for l in man.get("layers", [])]
        layer_refs |= set(ls)
        refs |= set(ls)
        kind = "attestation" if "attestation-manifest" in json.dumps(ent) else "image"
        kinds.append((kind, b, cfg, len(ls), len(set(ls))))
        print("    %-11s manifest %s  layers=%-4d distinct=%-4d config=%s"
              % (kind, b.rsplit('/', 1)[-1][:16], len(ls), len(set(ls)), cfg.rsplit('/', 1)[-1][:16]))
    unreferenced = sorted(b for b in blobs if b not in refs)
    print("  blob members referenced by the DAG : %d / %d" % (len(refs & set(blobs)), len(blobs)))
    print("  unreferenced                       : %d %s" % (len(unreferenced), unreferenced[:3]))
    out["dag"] = [{"kind": k, "manifest": b, "config": c, "layers": n, "distinct": d}
                  for k, b, c, n, d in kinds]
    out["unreferenced_blobs"] = unreferenced
    if unreferenced:
        sys.stderr.write("FAIL: %d blob(s) in the archive are not reachable from index.json\n"
                         % len(unreferenced))
        return 1
    print()

    print("=" * 74)
    print("3. CONTENT IDENTITY")
    print("=" * 74)
    legacy = json.loads(small["manifest.json"])
    cfg_path = legacy[0]["Config"]
    cfg = json.loads(small[cfg_path])
    dids = cfg["rootfs"]["diff_ids"]
    cc = Counter(dids)
    print("  image config blob  : %s (%d bytes, sha256 self-consistent)"
          % (cfg_path.rsplit('/', 1)[-1][:16], len(small[cfg_path])))
    print("  RepoTags           : %s" % legacy[0].get("RepoTags"))
    print("  created            : %s" % cfg.get("created"))
    print("  diffIDs            : %d entries, %d distinct" % (len(dids), len(cc)))
    for k, v in cc.items():
        if v > 1:
            print("      repeated %dx   : %s" % (v, k))
    if prof and "layers" in prof and len(dids) != prof["layers"]:
        sys.stderr.write("FAIL: diffID count %d != profile expectation %d\n"
                         % (len(dids), prof["layers"]))
        return 1
    print()

    J = " ".join(dids)
    L = "\n".join(dids)
    serializations = {
        "space-joined + trailing newline  [AUTHORITATIVE: docker image inspect -f '{{join .RootFS.Layers \" \"}}' | sha256sum]":
            J + "\n",
        "space-joined, no trailing newline": J,
        "newline-joined, no trailing newline": L,
        "newline-joined + trailing newline": L + "\n",
        "newline-joined + two trailing newlines": L + "\n\n",
    }
    print("  every published \"identity\" for this build, against the SAME %d-entry list:" % len(dids))
    print("  %-100s %s" % ("serialization", "sha256[:16]"))
    for k, v in serializations.items():
        val = h16(v.encode())
        tag = ""
        if val == expect_identity:
            tag = "  <== ACCEPTED (== start.sh IMGID_TPL)"
        elif val in FALSE_EMPTY:
            tag = "  !! FALSE-EMPTY CONSTANT"
        print("  %-100s %s%s" % (k, val, tag))
    print()

    got = h16((J + "\n").encode())
    full = hashlib.sha256((J + "\n").encode()).hexdigest()
    print("  content identity   : %s" % got)
    print("  content identity, full : %s" % full)
    print("  expected           : %s" % expect_identity)
    out["content_identity"] = got
    out["content_identity_full"] = full
    out["serializations"] = {k: h16(v.encode()) for k, v in serializations.items()}
    out["config_digest"] = cfg_path.rsplit("/", 1)[-1]
    out["oci_index_digest"] = top.rsplit("/", 1)[-1]

    if got in FALSE_EMPTY:
        sys.stderr.write("FAIL: identity is a false-empty constant -- pipeline failed OPEN\n")
        return 1
    if got != expect_identity:
        sys.stderr.write("FAIL: content identity %s != %s\n" % (got, expect_identity))
        return 1
    print()

    if a.layer_chain:
        import zlib
        print("=" * 74)
        print("4. LAYER CHAIN  (second streaming pass: gunzip every layer blob)")
        print("=" * 74)
        layers_ordered = [l if l.startswith("blobs/") else blob(l) for l in legacy[0]["Layers"]]
        want = {name: i for i, name in enumerate(layers_ordered)}
        chain_ok = True
        fh2 = open(a.archive, "rb")
        st2 = fh2
        zr2 = None
        if compression == "zstd":
            zr2 = zstandard.ZstdDecompressor().stream_reader(fh2, read_size=1 << 22)
            st2 = zr2
        try:
            tf2 = tarfile.open(fileobj=st2, mode="r|")
            for m in tf2:
                if m.name not in want or not m.isfile():
                    continue
                i = want[m.name]
                d = zlib.decompressobj(31)
                h = hashlib.sha256()
                raw = 0
                src = tf2.extractfile(m)
                for blk in iter(lambda: src.read(16 << 20), b""):
                    out_b = d.decompress(blk)
                    h.update(out_b)
                    raw += len(out_b)
                out_b = d.flush()
                h.update(out_b)
                raw += len(out_b)
                g = "sha256:" + h.hexdigest()
                ok = (g == dids[i])
                chain_ok = chain_ok and ok
                print("  %s  decompressed %14d B  %s"
                      % (m.name.rsplit("/", 1)[-1][:16], raw,
                         "MATCH  (== diff_id %s)" % dids[i][7:23] if ok
                         else "!!MISMATCH!! expected " + dids[i]))
        finally:
            if zr2 is not None:
                zr2.close()
            fh2.close()
        out["layer_chain_ok"] = chain_ok
        if not chain_ok:
            sys.stderr.write("FAIL: layer chain broken (compressed blob does not decompress "
                             "to its diff_id)\n")
            return 1
        print("  => every layer blob decompresses to exactly its config diff_id")
        print()

    print("  RESULT: PASS -- this archive is the same content the fleet runs.")
    print()

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print("wrote", a.json)
    if a.blob_manifest:
        with open(a.blob_manifest, "w", encoding="utf-8") as f:
            for n, s, t in sorted(members, key=lambda x: -x[1]):
                f.write("%16d  %s\n" % (s, n))
        print("wrote", a.blob_manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

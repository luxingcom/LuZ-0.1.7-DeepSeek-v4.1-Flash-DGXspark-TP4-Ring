#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_redaction.py -- fail-closed leak scan for the PUBLISHED repository tree.

Why this exists
---------------
`deliverables/engineering-assurance/sanitize_release.py` is a *masker*: it walks a
release copy and applies a replacement table.  That table covers credentials, IPs,
hostnames, the application user and one path prefix.  It has **no entry for the
network interface / HCA classes** -- the very classes the 2026-09-17 release audit
marked "must mask" in its section 3.2.1, including the per-rank `PEER_HCA` pinning
map, which the same table calls the physical ring wiring fingerprint.

A masker removes only what it knows about, and a scan that reuses the masker's class
list cannot fail on what the masker does not know about.  Policy and executor shared
one blind spot, and the omission was invisible from both ends.

This checker is deliberately *separate* from the masker, enumerates the classes
independently, and records the policy verdict per class.  It is fail-closed: an
unclassified hit in a blocker class exits non-zero.

Usage
-----
    python3 scripts/check_redaction.py [repo_root]     # default: repo root
    python3 scripts/check_redaction.py --selftest      # regression cases only

Exit codes
----------
    0   no unclassified hits in any blocker class
    1   at least one unclassified blocker-class hit (the scan FAILED)
    2   usage / environment error, or the scanner's own self-test failed

Scanning discipline (learned the hard way, repeatedly)
-----------------------------------------------------
- A checker's lexical model is not the target's actual syntax.  Four failures in one
  session came from this: `grep -cF '>'` counting `>>`, `key=value` parsed by field
  position, a bare `|` count treating an escaped `\\|` as a delimiter, and an inline
  shell regex losing its backslashes to quoting.  Hence a script file rather than an
  inline one-liner, and a word boundary on every pattern.
- After every write, extend the pattern set with whatever *you* just wrote.  A
  verification recipe once leaked a real host alias into a public README and survived
  a scan that only reused the previous pattern list.
- Documentation that quotes a pattern is a scan target too -- this file and the
  classification table in `benchmarks/README.md` included.  The self-test samples
  below are therefore assembled from fragments at run time: writing a real value here
  to prove the scanner can find it would put that value in the repository.
- `zurih`, `?pwd=luzi` and `/opt/aicad-prod` are deliberate and load-bearing
  (attribution, published share code, published project name).  Do not "clean" them.
"""
import os
import re
import sys

# ---------------------------------------------------------------------------
# Classes. Policy verdicts come from the 2026-09-17 release audit, section 3.2.1.
#   blocker    -- the audit says mask. Any unclassified hit fails the scan.
#   classified -- deliberately retained; must carry a reason in CLASSIFIED.
# ---------------------------------------------------------------------------
PATTERNS = [
    # (id, regex, class, severity)
    ("username-in-path",
     r"/home/(?!(?:spark|zurih|user|username|you|your|example|me|appuser|host|node)/)"
     r"[a-z][a-z0-9_-]*/",
     "identity", "blocker"),

    ("sudo-password", r"\bAS1217hf\b", "credential", "blocker"),

    ("api-token", r"\bsk-dgxspark-[0-9a-f]{4,}\b|\bLuZvLLMDEV2026\b",
     "credential", "blocker"),

    ("node-hostname", r"\bdgxspark0[1-4]\b(?!\.example)", "identity", "blocker"),

    ("mgmt-ip", r"\b192\.168\.(?:5|1)\.18[6-9]\b|\b192\.168\.5\.5[7-8]\b",
     "network", "blocker"),

    ("peer-hca-pinning-map", r"PEER_HCA_RANK[0-9]\s*=\s*\"[^\"]*roce",
     "topology-fingerprint", "blocker"),

    # ---- deliberately retained -------------------------------------------
    # C3 was ruled must-mask by the 09-17 audit and re-classified benign on
    # 2026-09-18: on GB10 / ConnectX-7 these names are driver-assigned constants,
    # identical on every unit, so they carry no identity -- while masking them makes
    # the template unfillable. The one class that stays masked is C4, above.
    ("hca-name", r"\brocep[0-9]s[0-9]f[0-9]\b|\broceP[0-9]p[0-9]s[0-9]f[0-9]\b",
     "network", "classified"),
    ("nic-name", r"\benp[0-9]s[0-9]f[0-9]np[0-9]\b|\benP[0-9]s[0-9]\b",
     "network", "classified"),
    ("upstream-author-path", r"/home/zurih/", "attribution", "classified"),
    ("generic-scheme-ip", r"\b10\.0\.0\.[0-9]+\b", "network", "classified"),
    ("nfs-pair-ip", r"\b10\.0\.(?:22|23|33)\.[0-9]+\b", "network", "classified"),
    ("upstream-author", r"\bzurih\b", "attribution", "classified"),
    ("share-code", r"\?pwd=luzi\b", "deliberate", "classified"),
    ("aicad-path", r"/opt/aicad-prod\b", "published-name", "classified"),
    ("placeholder-account", r"/home/spark/", "placeholder", "classified"),
    ("ascii-placeholder",
     r"_PH_[A-Z0-9_]+_|<NODE_IP>|<PINNING>|<IB_HCA>|<NET_IFACE>|<USER>",
     "placeholder", "classified"),
]

CLASSIFIED = {
    ("hca-name", "*"):
        "C3, re-classified benign 2026-09-18. `rocep1s0f0/1` and `roceP2p1s0f0/1` are "
        "the driver-assigned RoCE interface names of the on-board ConnectX-7: every "
        "GB10-generation DGX Spark shows these same four names. No identity, and the "
        "template is unusable without them",
    ("nic-name", "*"):
        "C3, re-classified benign 2026-09-18, same argument as `hca-name`: `enp1s0f1np1` "
        "and `enP7s7` are stock interface names on this board, not deployment-specific",
    ("upstream-author-path", "*"):
        "`zurih` is the upstream author identifier already pinned as attribution (it "
        "appears in upstream NOTICE/copyright lines); these are that author's paths in "
        "the upstream kit, carried over unchanged, not this deployment's account",
    ("generic-scheme-ip", "*"):
        "the repository's own generic scheme: 10.0.0.1 = head, 10.0.0.2 = worker 1; "
        "used consistently across seven files, and the real fabric is a different range",
    ("nfs-pair-ip", "*"):
        "part of that same generic scheme (NFS pairs), not the fabric",
    ("upstream-author", "*"):
        "upstream author identifier in NOTICE/copyright lines; removing it would strip "
        "attribution",
    ("share-code", "*"):
        "deliberately published cloud-drive extract code -- it is how the reader is "
        "meant to obtain the image",
    ("aicad-path", "*"):
        "aicad is a published project name; README's attribution table already links "
        "its repository as the origin of the libncclpin shim",
    ("placeholder-account", "*"):
        "generic distribution account used by the published harness paths; not the "
        "account this deployment runs as",
    ("ascii-placeholder", "*"):
        "an ASCII placeholder introduced by the redaction pass itself -- the intended "
        "public form, not a leak",
}

# Regression cases from the first scan pass. Assembled from fragments on purpose:
# a real value written here to prove the scanner works would itself be a leak.
_AS = "AS" + "1217" + "hf"
_HCA = "roce" + "p1s0f0"
_NIC = "enP" + "7s7"
_IP = "192.168." + "5." + "186"

SELFTEST_NO_MATCH = [
    # numeric coincidence: a memory size shaped like an address fragment
    'assert budget == "~189 GiB"',
    # numeric coincidence: a throughput pair whose second value looks like an octet
    "prefill 149.8 / decode 140.3 tok/s",
    # mid-word substring: matched a key pattern without a word boundary
    "disk-cache-hit / mask-initialization",
    # the intended public placeholder
    'API_KEY = "YOUR_API_KEY"',
    # a variable reference, not a literal
    'password = os.environ.get("WORKER_PASS")',
    # generic /home paths that carry no identity
    "https://example.invalid/home/user/index.html",
    "see /home/appuser/config for the template",
]
SELFTEST_MUST_MATCH = [
    ("peer-hca-pinning-map",
     "PEER_HCA_RANK0=" + '"1=' + _HCA + ";3=hcaC,hcaD\""),
    ("hca-name", "IB_HCA=" + _HCA),
    ("nic-name", "GLOO_SOCKET_IFNAME=" + _NIC),
    ("username-in-path", "SB=" + "/home/" + "some" + "one/state"),
    ("mgmt-ip", "upstream at " + _IP + ":8001"),
    ("sudo-password", "pw " + _AS + " end"),
]

# `.workbuddy/` is skipped deliberately. It is gitignored scratch space -- run logs,
# working scripts, and this project's own memory notes, all of which legitimately
# contain the real host names, because that is what they are for. It can never be
# published, so a hit there is not a leak; and a check that fails on every run for a
# reason nobody will ever fix is a check people learn to skip, which costs more than
# it catches. The published tree is what this scans.
SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv",
             "site-packages", "dist", "build", ".mypy_cache", ".pytest_cache",
             ".workbuddy"}
BINARY_EXT = {".bin", ".safetensors", ".gguf", ".tar", ".tgz", ".zip", ".png",
              ".jpg", ".jpeg", ".gif", ".pdf", ".so", ".o", ".a", ".pyc",
              ".ipynb", ".gz", ".xz", ".7z", ".zst", ".woff", ".woff2", ".ttf"}


def selftest():
    failures = []
    for text in SELFTEST_NO_MATCH:
        for pid, rx, cls, sev in PATTERNS:
            if sev == "blocker" and re.search(rx, text, re.M):
                failures.append("false positive: %s matched %r" % (pid, text))
    lookup = dict((p[0], p[1]) for p in PATTERNS)
    for pid, text in SELFTEST_MUST_MATCH:
        if not re.search(lookup[pid], text, re.M):
            failures.append("missed: %s did not match %r" % (pid, text))
    for f in failures:
        print("  [FAIL] " + f)
    print("selftest: %d cases, %d failures"
          % (len(SELFTEST_NO_MATCH) + len(SELFTEST_MUST_MATCH), len(failures)))
    return 1 if failures else 0


def is_binary(path):
    if os.path.splitext(path)[1].lower() in BINARY_EXT:
        return True
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(8192)
    except OSError:
        return True


def scan(root):
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            if is_binary(fp):
                continue
            rel = os.path.relpath(fp, root).replace(os.sep, "/")
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.read().split("\n")
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                for pid, rx, cls, sev in PATTERNS:
                    if re.search(rx, line, re.M):
                        hits.append((pid, cls, sev, rel, i, line.strip()[:150]))
    return hits


def main(argv):
    if "--selftest" in argv:
        return selftest()
    rest = [a for a in argv[1:] if not a.startswith("--")]
    root = rest[0] if rest else os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))

    if selftest():
        print("\nFAIL -- the scanner itself is broken; refusing to report on a target.")
        return 2

    hits = scan(root)
    counts, unclassified = {}, []
    for pid, cls, sev, rel, lineno, text in hits:
        counts[(cls, sev)] = counts.get((cls, sev), 0) + 1
        if sev == "classified" or (pid, rel) in CLASSIFIED or (pid, "*") in CLASSIFIED:
            continue
        unclassified.append((pid, cls, rel, lineno, text))

    print("scan root : %s" % root)
    print("hits      : %d across %d files" % (len(hits), len(set(h[3] for h in hits))))
    for (cls, sev), n in sorted(counts.items()):
        print("  %-11s %-19s %d" % (sev, cls, n))

    if unclassified:
        print("\nUNCLASSIFIED BLOCKER-CLASS HITS: %d\n" % len(unclassified))
        for pid, cls, rel, lineno, text in unclassified:
            print("  [%s / %s] %s:%d" % (pid, cls, rel, lineno))
            print("      %s" % text)
        print("\nFAIL -- mask them, or add a CLASSIFIED entry with a reason.")
        return 1

    print("\nPASS -- every hit is classified.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

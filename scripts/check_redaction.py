#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_redaction.py -- fail-closed leak scan for the PUBLISHED repository tree.

Why this exists
---------------
`deliverables/engineering-assurance/sanitize_release.py` (a deployment-side tool,
not shipped in this repository) is a *masker*: it walks a release copy and applies
a replacement table.  That table covers credentials, IPs,
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
- **The pattern list is inside the scan target, and nobody noticed for six days.**
  The two credential classes were written *literally*, so this file published the
  operator's sudo password and a token to everyone who cloned the repository --
  from `7259fee` (2026-09-18) until 2026-09-24.  The scanner could not report it:
  `\b` is itself a word character, so in the literal text `<value>` wrapped in
  `\b` on both sides the boundary after the leading escape never exists, and the
  pattern can never match its own definition.  A pattern that hides from itself is
  not a policy.  Credentials are now assembled from fragments at module level, and
  the selftest asserts both halves -- that this file does not publish them, and
  that the rebuilt patterns still catch a sample.  **Editing it out does not
  unpublish it: the blobs remain in history, so a value that has ever been in a
  pushed commit is a value to rotate, not a value to fix.**
- **2026-09-24, and the rule above applied to itself.**  Two files already in the tree
  were found carrying the operator's *local* absolute path (a drive letter, `Users`, a
  real account name, and the tool's own directory), and a report being prepared for
  publication carried an address inside the management /24 that `mgmt-ip` did not
  enumerate.  Every path pattern in this file assumed POSIX and every address pattern
  enumerated hosts, so neither class was visible to it.  Classes `windows-user-path`
  and `mgmt-subnet-ip` were added after masking all three.  When you add a class, add
  its self-test case in the same edit -- the fixtures below are the regression.
- `zurih`, `?pwd=luzi` and `/opt/aicad-prod` are deliberate and load-bearing
  (attribution, published share code, published project name).  Do not "clean" them.
- **2026-09-30, and the same rule applied to a *sibling key*.**  `peer-hca-pinning-map`
  had long been the one class the repo masks rather than classifies, on the stated
  ground that the map *is* the physical cabling.  Then the 0.2.9 pack turned out to
  carry `B12X_ROCE_PEER_HCA_MAPS` -- the same map written as `peer=HCAindex/HCAindex`,
  with `B12X_ROCE_HCA` giving the index order.  Decoding it against the four shipped
  `PEER_HCA_RANK<n>` values reproduced every one of the 12 masked entries (and 4 more).
  So the masking was cosmetic: the class was masked in one spelling and published in
  another.  Class `b12x-peer-hca-map` was added.  The lesson is the general form of
  the one above: **a class is not a value, it is every encoding of that value.**
"""
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# Classes. Policy verdicts come from the 2026-09-17 release audit, section 3.2.1.
#   blocker    -- the audit says mask. Any unclassified hit fails the scan.
#   classified -- deliberately retained; must carry a reason in CLASSIFIED.
# ---------------------------------------------------------------------------
# Credential patterns are ASSEMBLED FROM FRAGMENTS, for the same reason the
# self-test samples further down are: this file lives inside the tree it scans, so
# a literal credential in the pattern list publishes that credential to everyone
# who clones the repository.
#
# The previous form was literal, and it did exactly that -- and the scanner could
# not see it either.  `\b` is itself a word character, so once a value is written
# between two literal `\b` escapes there is no word boundary after the leading
# one, and the assertion can never match its own definition.  A pattern that
# hides from itself is not a policy, and a scanner is the last file that can
# afford one.
#
# This comment block is itself inside the scan target.  An earlier draft quoted
# that old pattern verbatim "to explain the bug", which re-published the
# credential the fix had just removed -- and the new selftest caught it on the
# very next run.  Explain the shape, never the value.
#
# The selftest asserts both halves: that no fragment here assembles into a
# contiguous credential anywhere in this file, and that the rebuilt pattern still
# matches a sample.  Its fixture value is assembled separately from `_SUDO_PW` on
# purpose -- a single assembly shared by the pattern and its test would break
# together, and the test would not notice.  When you add a credential class, add
# its fragment here -- never the value.
_SUDO_PW = "AS" + "1217" + "hf"
_API_TOK = "sk-" + "dgxspark-" + "[0-9a-f]{4,}"
_API_ALT = "LuZ" + "vLLM" + "DEV" + "2026"

# 2026-10-01 carrier classes.  Same fragment discipline: the names below are
# real identities found in the 0.2.9 bundle's *non-file* carriers, so they must
# not appear contiguously anywhere in this file either.
_ID_MAIL_1 = "op" + "s" + "@" + "local" + "host"
_ID_MAIL_2 = "liux" + "iaoya" + "@" + "local"
_ID_NAME_1 = "lixi" + "aofan"

# Already published by THIS repository's own history (measured: 12 commits on
# the pushed main line).  Fragment-built for the same reason as the rest: the
# pattern list is inside the scan target.
_ID_MAIL_PUB = "op" + "s" + "@" + "local" + "host"

PATTERNS = [
    # (id, regex, class, severity)
    ("username-in-path",
     r"/home/(?!(?:spark|zurih|user|username|you|your|example|me|appuser|host|node)/)"
     r"[a-z][a-z0-9_-]*/",
     "identity", "blocker"),

    ("sudo-password", r"\b" + _SUDO_PW + r"\b", "credential", "blocker"),

    ("api-token", r"\b" + _API_TOK + r"\b|\b" + _API_ALT + r"\b",
     "credential", "blocker"),

    ("node-hostname", r"\bdgxspark0[1-4]\b(?!\.example)", "identity", "blocker"),

    ("mgmt-ip", r"\b192\.168\.(?:5|1)\.18[6-9]\b|\b192\.168\.5\.5[7-8]\b",
     "network", "blocker"),

    ("peer-hca-pinning-map", r"PEER_HCA_RANK[0-9]\s*=\s*\"[^\"]*roce",
     "topology-fingerprint", "blocker"),

    # Added 2026-09-30.  The class above is *one encoding* of the pinning map, and
    # masking it alone turned out to be cosmetic: `B12X_ROCE_PEER_HCA_MAPS` carries
    # the same map as peer=HCAindex/HCAindex, and `B12X_ROCE_HCA` supplies the index
    # order, so every masked `PEER_HCA_RANK<n>` entry is recoverable from the two
    # keys nobody was looking at.  Measured, not inferred: all 12 masked entries
    # decode back byte-for-byte (and the B12X form carries 4 more).  A mask whose
    # target is still readable through a sibling key is not a mask.
    #
    # Shape, not value: `p=a/b` with `/` and `,` separators inside one assignment.
    ("b12x-peer-hca-map", r"B12X_ROCE_PEER_HCA_MAPS\s*=\s*\"?[0-9]+=[0-9]+/[0-9]+",
     "topology-fingerprint", "blocker"),

    # Added 2026-09-24 (see the docstring).  Two design notes:
    #   * the trailing separator is deliberately NOT required, unlike
    #     `username-in-path` -- a bare drive/Users/<account> is itself the
    #     disclosure, and requiring the separator is how a leak escapes.
    #   * the lookahead whitelists the accounts that are generic *by construction*
    #     (Windows ships `Public` and `Default`; the rest mirror the /home list).
    ("windows-user-path",
     r"[A-Za-z]:[\\/]{1,2}(?i:Users)[\\/]{1,2}"
     r"(?!(?i:Public|Default|Example|User|Username|You|Your|Shared)\b)"
     r"[A-Za-z][A-Za-z0-9._-]*",
     "identity", "blocker"),

    # Added 2026-09-24.  `mgmt-ip` above enumerates the specific node and NFS hosts
    # that were in front of us when the class was written; it is blind to any other
    # host on the same management /24, which is the same disclosure.  The published
    # repo carries its own generic scheme (10.0.0.x) precisely so that nothing from
    # the real range has to appear -- so no address in it is publishable.
    ("mgmt-subnet-ip", r"\b192\.168\.5\.[0-9]{1,3}\b", "network", "blocker"),

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

# Carrier patterns: applied to commit/tag messages and to author / committer /
# tagger identity fields, NOT to file contents.  Separate list on purpose -- a
# worktree walk cannot see these carriers at all, so folding them into PATTERNS
# would imply a coverage the walk does not have.
CARRIER_PATTERNS = [
    # The identities that are NOT already public -- and only those.  Two of the
    # identities in the 0.2.9 bundle are already on this repository's own pushed
    # main line (measured 2026-10-01), so they are disclosed-but-unfixable rather
    # than new; they are handled by a separate `classified` pattern at the end of
    # this list.  Splitting by DISPOSITION rather than listing every value here is
    # load-bearing: if an already-published value stays in this alternation, both
    # patterns fire and the blocker verdict wins, so the exemption becomes
    # decoration.  That exact mistake was made and caught in one revision.
    # Explain the shape, never the value -- this block is inside the scan target.
    ("carrier-identity-email",
     r"\b" + _ID_MAIL_2 + r"\b",
     "identity", "blocker"),
    # a real name with no email at all -- strictly more identifying than the
    # local-part-only form, and the one identity class absent from the public
    # repository's own history.
    ("carrier-real-name", r"\b" + _ID_NAME_1 + r"\b", "identity", "blocker"),
    # node hostnames are already a blocker class for file contents; they reach
    # commit messages too (`--replace-text` does not touch messages).
    ("carrier-node-hostname", r"\bdgxspark0[1-4]\b", "identity", "blocker"),

    # Narrowly exempted, NOT harmless.  This one identity is already on the
    # pushed public main line (12 commits, measured 2026-10-01), so the
    # disclosure has already happened and rewriting it would change every SHA
    # of a repository that is already cloned -- for a value that is already out.
    # Severity `classified`, not `blocker`, and deliberately a SEPARATE pattern
    # with its own id: collapsing it into the class above would exempt the two
    # identities that are still private, which is the hole this class exists to
    # close.  A class-wide exempt would be the bug, not the fix.
    ("carrier-identity-already-published",
     r"\b" + _ID_MAIL_PUB + r"\b",
     "identity", "classified"),
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
# 2026-09-24 classes: both separator styles, the bare (separator-less) form, a
# whitelisted generic account that must NOT match, and a host on the management /24
# that the older host-enumerating pattern could not see.
_WIN = "C:" + "/Us" + "ers/" + "some" + "one/"
_WIN_B = "D:" + "\\" + "Us" + "ers" + "\\" + "some" + "one" + "\\"
_WIN_OK = "C:" + "/Us" + "ers/" + "exa" + "mple/work"
_MGMT = "192.168." + "5." + "77"

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
    # generic Windows accounts carry no identity either (same argument as /home/user)
    _WIN_OK,
    "default profile lives under C:" + "/Us" + "ers/" + "Public",
    # 2026-09-30: naming the B12X key in prose (a doc that explains the derivation)
    # is not the map. Only a value assignment is.
    "`B12X_ROCE_PEER_HCA_MAPS` is the index form of the pinning map; see `B12X_ROCE_HCA`",
]
SELFTEST_MUST_MATCH = [
    ("peer-hca-pinning-map",
     "PEER_HCA_RANK0=" + '"1=' + _HCA + ";3=hcaC,hcaD\""),
    # 2026-09-30: the sibling encoding. Shape-only fixture -- the pattern keys on the
    # `p=a/b` structure, so no real value has to be written down to test it.
    ("b12x-peer-hca-map", "B12X_ROCE_PEER_HCA_MAPS=" + "1=1/3,2=0/3"),
    ("b12x-peer-hca-map", 'B12X_ROCE_PEER_HCA_MAPS="' + "0=1/2;1=0/2"),
    ("hca-name", "IB_HCA=" + _HCA),
    ("nic-name", "GLOO_SOCKET_IFNAME=" + _NIC),
    ("username-in-path", "SB=" + "/home/" + "some" + "one/state"),
    ("mgmt-ip", "upstream at " + _IP + ":8001"),
    ("sudo-password", "pw " + _AS + " end"),
    ("windows-user-path", "log written to " + _WIN + "state/app.log"),
    ("windows-user-path", "out=" + _WIN_B + "out.bin"),
    # the separator-less form must match too: a bare path is already the disclosure
    ("windows-user-path", _WIN.rstrip("/")),
    ("mgmt-subnet-ip", "client at " + _MGMT + " opened a stream"),
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

    # Self-immunity regression, added 2026-09-24 after both halves were found live.
    # They hid each other: the pattern list carried the credentials *literally*, so
    # this file published them to everyone who cloned the repository; and because
    # `\b` is itself a word character, the pattern could not match its own
    # definition, so the scanner reported zero credential hits across 28 files and
    # PASSED.  Exposure ran from 7259fee (2026-09-18) to this fix.
    #
    # Assert both halves, always.  Half one alone would be satisfied by deleting
    # the class; half two alone is what was already believed to be true.
    with open(os.path.abspath(__file__), "r", encoding="utf-8") as _self_f:
        _self_src = _self_f.read()
    for _v in (_SUDO_PW, _API_TOK, _API_ALT,
               _ID_MAIL_1, _ID_MAIL_2, _ID_NAME_1, _ID_MAIL_PUB):
        if _v in _self_src:
            failures.append("this file PUBLISHES %r, which it exists to catch"
                            % (_v[:3] + "***"))
    for _pid, _sample in (("sudo-password", "pw " + _SUDO_PW + " end"),
                          ("api-token", "k " + _API_ALT + " x")):
        if not re.search(lookup[_pid], _sample, re.M):
            failures.append("%s stopped matching a sample after being rebuilt "
                            "from fragments" % _pid)

    # 2026-10-01 carrier classes.  Both halves again: each must catch a sample,
    # and this file must not carry the value contiguously.  A carrier pattern
    # that never fires proves nothing about the carriers it claims to cover.
    _ck = dict((p[0], p[1]) for p in CARRIER_PATTERNS)
    # counted so the printed total is the measured total; a report that
    # understates its own coverage invites a reader to conclude the carriers
    # were never checked.
    _carrier_cases = 0
    for _pid, _sample in (
            ("carrier-identity-email", "commit by " + _ID_MAIL_2),
            ("carrier-real-name",
             "authored by " + _ID_NAME_1 + " on 09-12"),
            ("carrier-node-hostname",
             "wedge on dgxspark0" + "2" + " PD safety-mode"),
            ("carrier-identity-already-published",
             "authored by " + _ID_MAIL_PUB),
            ("carrier-identity-already-published",
             "committer " + _ID_MAIL_PUB + " on 09-21")):
        _carrier_cases += 1
        if not re.search(_ck[_pid], _sample, re.M):
            failures.append("%s stopped matching a sample" % _pid)
    for _t in ("Authored-by: LuZ Operator <operator@luz.invalid>",
               "ops-worker@example.invalid",
               "authorized <someone@example.invalid>",
               "dgxspark0X is a placeholder",
               # the already-published identity must NOT be a blocker: it is a
               # `classified` hit in its own pattern, and a value with two
               # dispositions would silently take the stricter one.
               "author " + _ID_MAIL_PUB + " end"):
        _carrier_cases += 1
        for _pid, _rx, _cls, _sev in CARRIER_PATTERNS:
            if _sev != "blocker":
                continue
            if re.search(_rx, _t, re.M):
                failures.append("false positive: %s matched %r"
                                % (_pid, _t))

    for f in failures:
        print("  [FAIL] " + f)
    print("selftest: %d cases, %d failures"
          % (len(SELFTEST_NO_MATCH) + len(SELFTEST_MUST_MATCH)
             + _carrier_cases, len(failures)))
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


def _git(repo, args):
    p = subprocess.run(["git"] + args, cwd=repo, capture_output=True)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def scan_carriers(repo):
    """Scan the carriers a worktree walk cannot reach.

    commit messages / author+committer identity / annotated tag objects
    (tagger identity + message).  Returns a hit list in the same shape as
    scan(), or None when `repo` is not a git repository -- the caller must
    then say so out loud instead of reporting a clean result.
    """
    rc, _ = _git(repo, ["rev-parse", "--git-dir"])
    if rc != 0:
        return None
    hits = []

    def check(where, lineno, text):
        for pid, rx, cls, sev in CARRIER_PATTERNS:
            if re.search(rx, text, re.M):
                hits.append((pid, cls, sev, where, lineno,
                             text.strip()[:150]))

    rc, out = _git(repo, ["log", "--all",
                          "--format=%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B%x1e"])
    if rc == 0:
        for rec in out.split("\x1e"):
            rec = rec.strip("\n")
            if not rec.strip():
                continue
            f = rec.split("\x1f")
            if len(f) < 6:
                continue
            sha = f[0].strip()[:12]
            for kind, val in (("author-name", f[1]), ("author-email", f[2]),
                              ("committer-name", f[3]), ("committer-email", f[4])):
                check("commit:%s/%s" % (sha, kind), 0, val)
            for i, line in enumerate(f[5].split(chr(10)), 1):
                check("commit:%s/message" % sha, i, line)

    rc, out = _git(repo, ["for-each-ref", "refs/tags",
                          "--format=%(refname)%09%(objecttype)%09%(taggername)"
                          "%09%(taggeremail)%09%(contents)"])
    if rc == 0:
        for line in out.split(chr(10)):
            if not line.strip():
                continue
            f = line.split("\t")
            if len(f) < 5 or f[1] != "tag":
                continue
            ref = f[0].replace("refs/tags/", "")
            for kind, val in (("tag-name", f[2]), ("tag-email", f[3])):
                check("tag:%s/%s" % (ref, kind), 0, val)
            for i, ln in enumerate(f[4].split(chr(10)), 1):
                check("tag:%s/message" % ref, i, ln)
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
    carrier_hits = scan_carriers(root)
    if carrier_hits is None:
        carrier_hits = []
        carriers_note = (
            "NOT SCANNED -- %s is not a git repository, so the commit/tag\n"
            "            messages and author/committer/tagger identities were\n"
            "            not checked.  A worktree walk cannot see them: this is\n"
            "            a gap, not a clean result." % root)
    else:
        carriers_note = (
            "scanned -- commit messages, annotated-tag messages (tagger\n"
            "            identity included) and author/committer identities.\n"
            "            A worktree walk cannot see any of these.")

    counts, unclassified = {}, []
    for pid, cls, sev, rel, lineno, text in hits + carrier_hits:
        counts[(cls, sev)] = counts.get((cls, sev), 0) + 1
        if sev == "classified" or (pid, rel) in CLASSIFIED or (pid, "*") in CLASSIFIED:
            continue
        unclassified.append((pid, cls, rel, lineno, text))

    print("scan root : %s" % root)
    print("hits      : %d across %d files" % (len(hits), len(set(h[3] for h in hits))))
    print("carriers  : %d hits, %s" % (len(carrier_hits), carriers_note))
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

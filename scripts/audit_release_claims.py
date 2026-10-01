#!/usr/bin/env python3
"""Audit every numeric / total-count claim in the 0.2.9 release package.

Why this exists
---------------
On 2026-09-30 a scripted pass over this package found seven defects that an
ordinary read-through had missed: a checksum manifest that could not verify, per-era
commit counts that summed to 56 against a stated 58, two commits credited to the
release that are not in its lineage, and four stale counts. Every one of them was a
hand-typed integer. This script turns those checks into a guard so the class cannot
silently come back.

Guarding principle: any "N" claim must be produced by a script. A claim a human
typed is a claim nobody verified.

Two counting scopes, deliberately distinguished
-----------------------------------------------
Earlier revisions of this package called the released history "the full history, 58
commits". That number came from a **shallow clone**: `.git/shallow` truncated the
graph at `3959f739`, so git could not see that commit's parents. After
`git fetch --unshallow`, the real `HEAD` ancestry is 84. Every count below is
qualified by its scope, because the same repository legitimately yields three
different numbers:

  our line     58 = `3959f739^..HEAD`  -- this project's own engineering line,
                                         and what the CHANGELOG appendix enumerates
  inherited    26 = the ancestors below `3959f739`, inherited from the upstream
                                         project's public history
  HEAD lineage 84 = 58 + 26            -- every ancestor of HEAD
  bundle        86 = --branches --tags -- lineage plus the 2 commits unique to the
                                         side branch `v40exp-20260928`

A shallow clone also breaks the **bundle**: `git bundle create` run from a shallow
repository emits an archive that cannot be cloned (`Could not read <parent>`;
`git bundle verify` still says "complete history"). The guard for that is in C1
below -- it refuses to run when `3959f739^` does not resolve, so a shallow source
fails loudly instead of producing a plausible wrong count.

Usage
-----
    # from the package root, pointing at a checkout of the deployment repo
    ./scripts/audit_release_claims.py --repo ~/dsv41-flash-dgxsparks

    # or without a checkout, straight from the bundled history
    ./scripts/audit_release_claims.py --bundle deploy/git-history-v0.2.9-fin2.bundle

It is fail-closed, and it takes its facts from git -- never from the documents it
is checking. Exit code is 0 only if every check passes.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

BRANCH_IN_BUNDLE = "4dgx-ring"  # bundle's head branch == the released tag's commit
# This project's own line starts at this commit. It is a fact about the repository,
# not a claim read out of a document; C1 verifies it resolves and that its parent is
# reachable, which is exactly what a shallow clone would break.
OUR_LINE_BASE = "3959f73939c451f6099338e2a891a702d7ff78b0"
FAILS = []


def git(args, cwd):
    p = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True,
                       errors="replace")
    if p.returncode != 0:
        sys.exit(f"FAIL: git {' '.join(args)} -> rc={p.returncode}\n{p.stderr.strip()}")
    return p.stdout


def check(tag, ok, detail):
    print(f"[{'PASS' if ok else 'FAIL'}] {tag}: {detail}")
    if not ok:
        FAILS.append(tag)
    return ok


# An 8-hex token in prose is not necessarily a commit id. Classify with a reason;
# a "the keyword appears somewhere in the file" test is too weak (that was a false
# positive on 2026-09-30).
TOKEN_CLASS = {
    "e3b0c442": ("sha_const", "sha256('') quoted as a check constant"),
    "01ba4719": ("sha_const", "sha256('\\n') quoted as a check constant"),
    "c4f13f93": ("md5_anchor", "production .env.tp4 md5 (cross-ref anchor)"),
    "05b74b2a": ("md5_anchor", "rollback env md5"),
    "9798b5e9": ("md5_anchor", "rollback-512k-ar env md5"),
    "79cafec0": ("upstream", "upstream main, cited as the LuZ-0.3.0 base"),
    # Tree objects are not commits. The README uses them to show that the rewrite
    # changed the tag object while leaving the file list identical (1220/0/0).
    # Classified by NAME rather than quietly allowed, so the distinction between
    # "a commit we ship" and "a tree we describe" stays explicit.
    "e578fe39": ("tree_object", "tag v0.2.9-fin2 tree (post-rewrite)"),
    "314982d0": ("tree_object", "tag v0.2.9-fin2 tree (pre-rewrite)"),
}
EXPLICITLY_SCOPED = {"d78b9d5", "22fd5ca"}  # side branch v40exp-20260928
SCOPE_MARKERS = ("v40exp-20260928", "不在这条血缘", "未烘入")


def clone_from_bundle(bundle):
    tmp = tempfile.mkdtemp(prefix="audit_bundle_")
    repo = os.path.join(tmp, "repo")
    subprocess.run(["git", "init", "-q", repo], check=True)
    # Fetch into the REAL namespaces, not a private refs/audit/* one. This matters:
    # `git rev-list --branches --tags` only sees refs/heads/* and refs/tags/*, so
    # parking the bundle's refs under a private prefix silently under-counts the
    # reachable set (it read 84 instead of 86 on 2026-09-30 and C8 failed for the
    # wrong reason). Keep the mapping 1:1 so the counts a reader would reproduce
    # are the counts this auditor computes.
    p = subprocess.run(["git", "fetch", os.path.abspath(bundle),
                        "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"],
                       cwd=repo, capture_output=True, text=True, errors="replace")
    if p.returncode != 0:
        # A bundle produced from a shallow clone dies HERE, before any count is
        # computed -- "Could not read <parent>" / "did not send all necessary
        # objects". That is the strongest form of the D14 defect: not merely
        # un-clonable, but un-fetchable. Surface git's own words and stop; never
        # continue with a partial object store.
        sys.exit("FAIL/GUARD: the bundle cannot be fetched into an empty repository "
                 f"(rc={p.returncode}).\n{(p.stderr or '').strip()}\n"
                 "  A bundle built from a SHALLOW clone fails exactly here, with "
                 "'Could not read <parent>' and 'did not send all necessary "
                 "objects'.\n  Note that `git bundle verify` will still report "
                 "'records a complete history' for such a file --\n  the acceptance "
                 "test is a CLONE into an empty directory, not verify's output.")
    git(["checkout", "-q", "--detach", f"refs/heads/{BRANCH_IN_BUNDLE}"], repo)
    return repo, tmp


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--repo", help="deployment repo checkout (reads working-tree git)")
    src.add_argument("--bundle", help="git bundle to read facts from")
    ap.add_argument("--pkg", default=".", help="release package root (default: cwd)")
    args = ap.parse_args()

    pkg = os.path.abspath(args.pkg)
    tmp = None
    repo = os.path.abspath(args.repo) if args.repo else None
    if args.bundle:
        repo, tmp = clone_from_bundle(args.bundle)

    try:
        # ---- one-time scope guard: a shallow source invalidates every count ----
        # Order matters: this runs before any number is computed.
        #
        # "The parent does not resolve" has three different causes and only one of
        # them is a shallow clone. Diagnosing all three as "shallow" sends the reader
        # to `git fetch --unshallow`, which cannot fix the other two. The clearest
        # non-shallow case is pointing this script at a checkout of a DIFFERENT
        # repository -- e.g. the public snapshot that redistributes the 0.2.9
        # content. That checkout is not truncated; it simply does not contain the
        # 0.2.9 deployment line at all, so every check below is inapplicable rather
        # than merely short.
        base_t = subprocess.run(["git", "cat-file", "-t", OUR_LINE_BASE],
                                cwd=repo, capture_output=True, text=True)
        base_present = base_t.returncode == 0 and base_t.stdout.strip() == "commit"
        par_t = subprocess.run(["git", "cat-file", "-t", OUR_LINE_BASE + "^"],
                               cwd=repo, capture_output=True, text=True)
        parent_ok = par_t.returncode == 0 and par_t.stdout.strip() == "commit"

        if not parent_ok:
            if not base_present:
                sys.exit(
                    "FAIL/WRONG-TARGET: the baseline commit does not exist in this "
                    f"repository at all ({OUR_LINE_BASE} -> rc={base_t.returncode}).\n"
                    "  This script audits the **0.2.9 deployment package**: it asserts "
                    "that package's own counts, and it hard-codes that package's\n"
                    f"  baseline commit and its head branch ({BRANCH_IN_BUNDLE!r}). A "
                    "checkout that does not contain that commit is a DIFFERENT\n"
                    "  repository -- not a shallow one -- and every check below would "
                    "be inapplicable rather than merely truncated.\n"
                    "  This is NOT a shallow clone; `git fetch --unshallow` cannot "
                    "help.\n"
                    "  Point it at the 0.2.9 material instead:\n"
                    "    --bundle <0.2.9 history bundle>   # shipped in the 0.2.9 "
                    "package, e.g. deploy/git-history-v0.2.9-fin2.bundle\n"
                    "    --repo   <0.2.9 deployment-repo checkout>\n"
                    "  and set --pkg to the 0.2.9 package root (its default is the "
                    "current directory).")
            if os.path.exists(os.path.join(repo, ".git", "shallow")):
                sys.exit(
                    "FAIL/GUARD: the baseline commit's PARENT does not resolve "
                    f"({OUR_LINE_BASE}^ -> rc={par_t.returncode}, "
                    f"type={par_t.stdout.strip() or 'n/a'}) and .git/shallow is "
                    "present.\n"
                    "  This is the signature of a SHALLOW clone (or a bundle built "
                    "from one): '.git/shallow' truncates the graph, so every count\n"
                    "  computed below would be a lower bound presented as a total, and "
                    "the bundle would not be clonable.\n"
                    "  Fix:  git fetch --unshallow <remote> <branch>   then rebuild the "
                    "bundle with:  git bundle create <f> --branches --tags")
            sys.exit(
                "FAIL/GUARD: the baseline commit's PARENT does not resolve "
                f"({OUR_LINE_BASE}^ -> rc={par_t.returncode}, "
                f"type={par_t.stdout.strip() or 'n/a'}), yet .git/shallow is ABSENT.\n"
                "  So this is not a shallow clone: the baseline commit is present and "
                "its parent is genuinely absent from the object store.\n"
                "  The history was truncated some other way (a graft, a "
                "partial/promisor clone, or a hand-filtered history), so counts below\n"
                "  would still be a lower bound presented as a total. Investigate the "
                "object store before trusting any number.")

        rows = [tuple(l.split("|", 2)) for l in
                git(["log", "--format=%h|%ad|%s", "--date=short", "HEAD"],
                    repo).strip().split("\n") if l]
        # --date=short prints YYYY-MM-DD; keep MM-DD. Do NOT use
        # `--date=format:%m-%d` here: older git builds demand a colon separator in
        # that form and abort with "date format missing colon separator". This is
        # not hypothetical -- on the packaging machine `shutil.which("git")`
        # resolves to a DIFFERENT binary than the shell's `git` (a bundled
        # PortableGit), so the same command succeeds in one and fails in the other.
        # Keep every git invocation version-agnostic.
        rows = [(h, d[5:], s) for h, d, s in rows]
        lineage_full = [l.strip() for l in
                        git(["log", "--format=%H", "HEAD"], repo).splitlines() if l]
        our_line_full = [l.strip() for l in
                         git(["rev-list", f"{OUR_LINE_BASE}^..HEAD"], repo)
                         .splitlines() if l]
        all_full = [l.strip() for l in
                    git(["rev-list", "--all"], repo).splitlines() if l]
        reach_full = [l.strip() for l in
                      git(["rev-list", "--branches", "--tags"], repo).splitlines() if l]
        tags = [t for t in git(["tag"], repo).splitlines() if t]
        tree_files = [f for f in
                      git(["ls-tree", "-r", "--name-only", "HEAD"], repo).splitlines() if f]
        lineage_short = {r[0] for r in rows}

        n_our, n_lin, n_reach = len(our_line_full), len(lineage_full), len(reach_full)
        n_inherit = n_lin - n_our

        def read(rel):
            p = os.path.join(pkg, rel)
            if not os.path.exists(p):
                sys.exit(
                    f"FAIL: package is missing a required file: {rel}\n"
                    f"  --pkg points at: {pkg}\n"
                    "  --pkg must be the ROOT OF THE 0.2.9 PACKAGE (the directory "
                    "holding docs/, scripts/, deploy/), not a checkout of some other\n"
                    "  repository. A snapshot of the same *content* is not enough: "
                    "this script asserts the package's own inventory, and the package\n"
                    "  carries files a redistribution may legitimately omit (it does "
                    "not follow that --pkg should point at that redistribution).\n"
                    "  Its default is the current directory.")
            return open(p, encoding="utf-8").read()

        changelog = read("docs/CHANGELOG-0.2.9.md")
        readme = read("docs/README-RELEASE.md")
        rindex = read("docs/RESEARCH-INDEX.md")
        sums = read("SHA256SUMS-payload")

        print(f"facts from git: our_line={n_our} inherited={n_inherit} "
              f"HEAD_lineage={n_lin} bundle_reachable={n_reach} --all={len(all_full)} "
              f"tags={len(tags)} tree_files={len(tree_files)}")
        print()

        # C1  appendix enumerates exactly THIS PROJECT's line (not the full lineage)
        #     -- and the shallow-clone guard above has already proven we can see it.
        blocks = changelog.split("```")
        if len(blocks) < 3:
            sys.exit("FAIL: no fenced appendix block in CHANGELOG")
        app = [l.split("|")[0] for l in blocks[1].strip().split("\n")
               if re.match(r"^[0-9a-f]{7,40}\|", l)]
        miss = [x for x in app if not any(h.startswith(x) for h in our_line_full)]
        extra = [h for h in our_line_full if not any(h.startswith(x) for x in app)]
        check("C1/appendix-vs-our-line",
              not miss and not extra and len(app) == n_our,
              f"appendix={len(app)} our_line={n_our} "
              f"not_in_our_line={miss} not_in_appendix={[h[:8] for h in extra]}")

        # C2  per-era counts sum to our-line total, and the header agrees ----------
        sec = changelog.split("## 二、")[1].split("## 三、")[0]
        declared = [int(m) for m in re.findall(r"，(\d+) 提交）", sec)]
        m = re.search(r"## 二、[^\n（]*（([^\n）]*?)(\d+) 提交", changelog)
        if not m:
            sys.exit("FAIL: cannot parse the era-section header in CHANGELOG "
                     "(refusing to proceed with an unknown declared total)")
        hdr = int(m.group(2))
        check("C2/era-sum", hdr == sum(declared) == n_our,
              f"declared={declared} sum={sum(declared)} header={hdr} our_line={n_our}")

        # C3  the era partition is total and non-overlapping --------------------
        # Era 5 (0.2.8pre) and era 6 (#40352) both live on 09-23, so a date
        # histogram alone cannot separate them: classify on (date, topic).
        era6_0923 = {"b5ddb40", "63c631b", "2786431", "517aca8"}
        missing_topic = [s for s in era6_0923
                         if not any(h.startswith(s) for h in our_line_full)]
        if missing_topic:
            check("C3/era-partition", False,
                  f"topic-classifier names commits not on our line: {missing_topic}")
        else:
            def era(sha, date):
                if date in ("09-13", "09-17"):
                    return 1
                if date == "09-19":
                    return 2
                if date in ("09-20", "09-21"):
                    return 3
                if date == "09-22":
                    return 4
                if date == "09-23":
                    return 6 if sha in era6_0923 else 5
                if date in ("09-28", "09-30"):
                    return 6
                return 0

            buckets = {i: 0 for i in range(1, 7)}
            unclass = []
            our_set = set(our_line_full)
            for sha, date, _ in rows:
                if not any(h.startswith(sha) for h in our_set):
                    continue  # inherited upstream history is outside this partition
                e = era(sha, date)
                if e == 0:
                    unclass.append((sha, date))
                else:
                    buckets[e] += 1
            got = [buckets[i] for i in range(1, 7)]
            check("C3/era-partition",
                  not unclass and sum(got) == n_our and got == declared,
                  f"buckets={got} unclassified={unclass} matches_prose={got == declared}")

        # C4  named SHAs are in our line, or explicitly scoped out ----------------
        # README §0.2 is the ONE place where a pre-rewrite id is the correct value:
        # its table shows `old -> new`, so the old ids must appear there. Exempting
        # the whole file would hide a genuinely stale citation elsewhere in it, so
        # the exemption is scoped to the SECTION: strip §0.2 before scanning, and
        # assert that §0.2 is where those ids actually live.
        readme_scan, readme_scope_note = readme, ""
        if "### 0.2 " in readme:
            head, tail = readme.split("### 0.2 ", 1)
            nxt = tail.find("\n## ")
            if nxt != -1:
                scope_blk, tail = tail[:nxt], tail[nxt:]
            else:
                scope_blk, tail = tail, ""
            readme_scan = head + tail
            pre = sorted(set(re.findall(r"(?<![0-9a-f])([0-9a-f]{7,8})(?![0-9a-f])",
                                        scope_blk)))
            pre = [t for t in pre if not re.search(r"[0-9]{7,}", t)]
            readme_scope_note = f" section0.2_exempted={pre}"
        for name, text in (("CHANGELOG", changelog), ("README-RELEASE", readme_scan),
                           ("RESEARCH-INDEX", rindex)):
            toks = sorted(set(re.findall(r"(?<![0-9a-f])([0-9a-f]{7,8})(?![0-9a-f])", text)))
            # pure-digit tokens are dates (20260928); commit ids here carry a letter
            dates = [t for t in toks if not re.search(r"[a-f]", t)]
            toks = [t for t in toks if re.search(r"[a-f]", t)]
            bad = []
            for t in toks:
                kind = TOKEN_CLASS.get(t, ("commit", ""))[0]
                if kind in ("sha_const", "md5_anchor", "upstream", "tree_object"):
                    continue
                # git floors `%h` at 7 hex and widens to 8 only when 7 is
                # ambiguous, so prose legitimately contains BOTH widths for the
                # same commit (the baseline is written `3959f739` but its `%h` is
                # `3959f73`). Accept a unique prefix of the full lineage.
                if len([h for h in lineage_full if h.startswith(t)]) == 1:
                    continue
                if t in EXPLICITLY_SCOPED and any(k in text for k in SCOPE_MARKERS):
                    continue
                bad.append(t)
            check(f"C4/{name}", not bad,
                  f"off-lineage_commit_tokens={bad} date_tokens_skipped={len(dates)}"
                  + (readme_scope_note if name == "README-RELEASE" else ""))

        # C5  manifest size matches the README claim -------------------------
        n_entries = len([l for l in sums.splitlines() if l.strip()])
        mm = re.search(r"sha256sum -c SHA256SUMS-payload\s*#\s*(\d+)/(\d+)", readme)
        cnum = int(mm.group(1)) if mm else -1
        check("C5/manifest-count", cnum == n_entries,
              f"manifest_entries={n_entries} readme_claim={cnum}")

        # C6  manifest does not hash itself ----------------------------------
        # Normalise the `*` of sha256sum's binary mode: the first version of this
        # check compared the raw last field against `SHA256SUMS-payload`, so a line
        # reading `… *SHA256SUMS-payload` could never match and the check could not
        # fail on the very defect it documents. The negative-test suite caught it
        # (C6 fired no FAIL while C5 did). Strip the marker, then compare basenames.
        def entry_name(line):
            return os.path.basename(line.split()[-1].lstrip("*" + " "))

        selfref = any(entry_name(l) == "SHA256SUMS-payload"
                      for l in sums.splitlines() if l.split())
        check("C6/no-self-reference", not selfref,
              "a self-hash cannot converge (real defect: line 1 held sha256(''))")

        # C7  image tar stays out of the payload manifest ---------------------
        intar = [l.split()[-1] for l in sums.splitlines() if l.strip().endswith(".tar")]
        check("C7/no-image-in-payload-manifest", not intar,
              f"the image is verified by its own sidecar; offenders={intar}")

        # C8  bundle scope statement only cites numbers this run can produce ------
        # Any 2+ digit figure in the statement must be one of the four legitimate
        # scopes. This is what catches a stale count that was merely re-worded.
        bm = re.search(r"git-history-v0\.2\.9-fin2\.bundle` \| git 全史 bundle（([^）]*)）",
                       readme)
        stmt = bm.group(1) if bm else ""
        facts = {str(n_our), str(n_inherit), str(n_lin), str(n_reach), str(len(tags))}
        # A date-shaped identifier (`v40exp-20260928`) is not a count. Drop the
        # WHOLE token, not just the digit run: stripping only `\d{6,}` leaves
        # `v40exp-` behind, whose `40` then reads as an unexplained count.
        prose = re.sub(r"\S*\d{6,}\S*", " ", stmt)
        cited = set(re.findall(r"\d{2,}", prose))
        unknown = sorted(cited - facts)
        check("C8/bundle-scope",
              bool(bm) and not unknown
              and str(n_reach) in cited and str(n_lin) in cited and str(n_our) in cited,
              f"readme='{stmt[:70]}…' ; cited={sorted(cited)} unknown={unknown} "
              f"git: our={n_our} inherit={n_inherit} lineage={n_lin} reach={n_reach}")

        # C9  the bundle carries every historical tag -------------------------
        check("C9/tag-coverage", len(tags) >= 6, f"tags={len(tags)} {sorted(tags)}")

        # C10 image size is stated in bytes, not docker-images SIZE -----------
        check("C10/image-size-bytes",
              "14,055,778,304" in readme and "13.09 GiB" in readme,
              "docker images SIZE is shared-layer accounting, not disk usage")

        # C11 no stale commit count survives the re-tag -----------------------
        check("C11/no-stale-commit-count",
              "57 提交" not in rindex and "60 提交" not in readme,
              "pre-re-tag / pre-unshallow counts must not survive")

        # C12 this auditor is itself covered by the manifest and the index -----
        # Real defect: v1 of this script shipped inside the package but was listed
        # in neither place, so the guard had no integrity protection and readers
        # had no way to find it.
        own_rel = "scripts/" + os.path.basename(os.path.abspath(__file__))
        in_sums = any(l.split()[-1].lstrip("*") == own_rel for l in sums.splitlines()
                      if l.split())
        in_readme = own_rel in readme
        exists = os.path.exists(os.path.join(pkg, own_rel))
        check("C12/auditor-is-covered", exists and in_sums and in_readme,
              f"{own_rel}: on_disk={exists} in_manifest={in_sums} in_readme={in_readme}")

        # C13 the published history was rewritten, so every SHA citation must
        #     belong to THAT history -- not to the pre-rewrite one -------------
        # Real defect (D17): the redaction rewrite re-hashed 78 of 84 commits, but
        # the package kept citing the old ids. Every command a reader copied would
        # have failed with "unknown revision" against a perfectly valid history.
        # C4 cannot catch this: it checks tokens against the SHIPPED lineage, so a
        # stale token is simply "unknown" to it and would need a hand-kept
        # allow-list -- which is how such a defect hides. Here the test is
        # structural: the tag's short hash must equal the tag's commit, and the
        # README's snapshot FILENAME must name that same commit.
        tag_commit = git(["rev-parse", "v0.2.9-fin2^{commit}"], repo).strip()
        documented = sorted(set(re.findall(
            r"v0\.2\.9-fin2-([0-9a-f]{7,40})\.tar\.gz", readme)))
        filenames = sorted(os.path.basename(p) for p in
                           __import__("glob").glob(
                               os.path.join(pkg, "deploy", "repo-snapshot-*.tar.gz")))
        on_disk = sorted(set(re.findall(r"repo-snapshot-v0\.2\.9-fin2-([0-9a-f]+)\.tar\.gz",
                                        " ".join(filenames))))
        consistent = (documented == [tag_commit[:8]] == on_disk
                      and tag_commit[:8] in changelog)
        check("C13/sha-repin-consistency", consistent,
              f"tag_commit={tag_commit[:8]} readme_names={documented} "
              f"on_disk={on_disk} changelog_cites={'yes' if tag_commit[:8] in changelog else 'NO'}"
              + ("" if consistent else
                 "  <- a citation names a commit this history does not contain; "
                 "re-pin it to the shipped id (see README §0.2)"))

        print()
        print(f"=== RESULT: {'ALL PASS' if not FAILS else 'FAILED: ' + ', '.join(FAILS)} ===")
        return 0 if not FAILS else 1
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

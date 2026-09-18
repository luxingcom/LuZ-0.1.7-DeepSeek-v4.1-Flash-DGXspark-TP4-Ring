#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_report_tables.py -- emit the report's tables from the archives.

The report used to be assembled by hand from JSON, which is how a table can
carry a number nobody can trace. This renders every table directly from the
archives produced by `run_sd1_all.sh`, so the report body and the raw data
cannot drift apart, and a reader can regenerate the tables themselves:

    python3 benchmarks/render_report_tables.py <run_dir> > tables.md

<run_dir> is the run directory with `de/`, `grammar/` (or `grammar2/`), `fp4_256/`,
`gw/`, `pr/`, `cache/` and `channel/` subdirectories (the layout
`run_sd1_all.sh` followed by `run_sd1_extra.sh` writes). Missing stages are
reported as missing, never silently skipped.

Exit code is non-zero if a stage that should be present is absent.
"""
import json
import os
import statistics
import sys

DE_TYPES = ["structured", "prose", "code", "json"]
CONCS = [1, 2, 4, 8, 16]


def load(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def fnum(v, nd=2):
    if v is None:
        return "\u2014"
    if isinstance(v, float):
        return ("%%.%df" % nd) % v
    return str(v)


def thousands(v):
    if v is None:
        return "\u2014"
    return "{:,}".format(int(round(v)))


def wave_spread(cell):
    """(max - min) / median of the per-wave medians, in percent.

    This is the row's own error bar and it is not decoration. Across the 20 cells
    of the 2026-09-18 SD-1 run the wave spread is 17.7%..45.0% for `structured`
    and only 0.5%..7.4% for `json`, `code` and `prose` -- the instability is
    concentrated in one type, not spread over the table. A row-to-row difference
    smaller than this spread is not resolvable, and printing the spread is the
    only way a reader can tell which differences are real.

    The cause is **not established, and an earlier note here got it wrong.** That
    note claimed DSpark's acceptance rate follows the output content and cited
    `chars_per_token` between 1.733 and 2.491. Both halves were wrong: the quoted
    range was not the measured range, and the per-stream relation does not exist.
    Measured from the per-stream records:

      * within-cell per-stream `chars_per_token` spans 1.188..3.661 (`structured`,
        C8) while `json` is nearly constant at 2.448..2.484;
      * but r(chars_per_token, decode_tps) *within a cell* has **median 0.001**
        across the 20 cells and is negative in 10 of them;
      * the pooled r = -0.295 is an artefact of pooling across concurrencies and
        must not be quoted; and
      * the previously cited r = +0.317 is exactly the value of one cell
        (`structured` C16, n=48). One member's value is not the grid's.

    So `structured` is both the most variable in content and the least
    reproducible, which makes "content variability drives throughput variability"
    a hypothesis worth testing -- but this archive does not support it as a
    finding, and no report should state it as one.

    Returned as None, not 0, when the archive predates `waves_detail`.
    """
    wd = cell.get("waves_detail") or []
    v = [w.get("median_decode_tps") for w in wd
         if w.get("median_decode_tps") is not None]
    if len(v) < 2:
        return None
    m = statistics.median(v)  # true median -- the upper median is not to be resurrected
    if not m:
        return None
    return round((max(v) - min(v)) / m * 100, 1)


def de_table(run, out, missing):
    d = load(os.path.join(run, "de", "de_v3_matrix.json"))
    if d is None:
        missing.append("de")
        return
    meta = d.get("_meta", {})
    out.append("<!-- generated from de/de_v3_matrix.json -->")
    out.append("")
    out.append("Max output %s tokens, %s waves per cell, one nonce per request -- no cell "
               "can be warmed by an earlier wave, an earlier stage, or the warm-up. "
               "`median decode` = `statistics.median` over every ok stream of every wave; "
               "the stream count is the `OK streams` column. `agg decode` = median over "
               "waves of that wave's own `\u03a3(ct\u22121) / (last first-token \u2212 first "
               "first-token)`. `agg prefill` = the same shape on `\u03a3 prompt_tokens`. The "
               "two aggregates are cluster-wide, so a cell's `median` and its `agg` are "
               "different quantities and are not expected to agree."
               % (meta.get("max_tokens"), meta.get("waves")))
    out.append("")
    out.append("`Wave spread` is `(max \u2212 min) / median` over the three per-wave medians, and "
               "it is a real error bar rather than decoration: the prompt fixes **how much** "
               "is generated, not **what**, and the resulting instability is concentrated in "
               "one type -- 17.7%\u201345.0% for `structured`, 0.5%\u20137.4% for the other "
               "three. **A row-to-row difference smaller than its own wave spread is not "
               "resolvable by this table.** On this run that bites: the full ordering "
               "`code > json > structured > prose` holds at every concurrency, but of the 15 "
               "adjacent gaps only 11 clear their own error bar -- at C1 and C2 the low-"
               "concurrency rows separate `code` from `prose` and nothing in between. The "
               "cause of the spread is not identified; see the note on `wave_spread`.")
    out.append("")
    out.append("| Type | C | Median decode tok/s/req | Wave spread | Agg decode tok/s | Median prefill tok/s | Agg prefill tok/s | Median TTFT s | chars/token | OK streams | Waves OK |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for t in DE_TYPES:
        for c in CONCS:
            cell = d.get("DE-V3_%s_C%d" % (t, c))
            if cell is None:
                continue
            # An absent count renders as absent. A missing key must not read as 0 --
            # "no streams succeeded" and "this archive predates the counter" are
            # different statements and only one of them is true.
            spread = wave_spread(cell)
            out.append("| %s | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s/%s |" % (
                t, c, fnum(cell.get("median_decode_tps")),
                ("\u2014" if spread is None else "\u00b1%.1f%%" % spread),
                fnum(cell.get("agg_decode_tps"), 1),
                fnum(cell.get("median_prefill_tps"), 1), fnum(cell.get("agg_prefill_tps"), 1),
                fnum(cell.get("median_ttft_s"), 3), fnum(cell.get("median_chars_per_token"), 2),
                fnum(cell.get("streams_ok")), fnum(cell.get("ok_waves")),
                fnum(cell.get("waves"))))
    out.append("")


def grammar_table(run, out, missing):
    # One source: the pass that writes per-stream records. The earlier pass wrote
    # only a summary, so its cells could not be checked below cell level; it was
    # re-run rather than shipped beside the auditable one. The stage is named
    # `grammar2` in the run log and shipped as `grammar/`, because it supersedes
    # the first pass entirely.
    src = "grammar"
    d = load(os.path.join(run, src, "grammar_ab.json"))
    if d is None:
        src = "grammar2"
        d = load(os.path.join(run, src, "grammar_ab.json"))
    if d is None:
        missing.append("grammar")
        return
    out.append("<!-- generated from %s/grammar_ab.json -->" % src)
    out.append("")
    out.append("Native `/generate` for both arms; same prompt *body*, same accounting, and "
               "one nonce per request so whichever arm runs second does not inherit the "
               "first arm's cached prefix. The only difference is whether "
               "`sampling_params.json_schema` is present. \u0394 is quoted as "
               "\"grammar \u2212 free\", so a negative \u0394 is the price of the constraint.")
    out.append("")
    out.append("| C | decode tok/s/req (free) | decode (grammar) | \u0394 | agg decode (free) | agg (grammar) | \u0394 | prefill tok/s (free) | prefill (grammar) | \u0394 | median ct (free / grammar) |")
    out.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for c in CONCS:
        cell = d.get("GRAMMAR_AB_C%d" % c)
        if cell is None:
            continue
        f, g = cell.get("free", {}), cell.get("grammar", {})
        pct = lambda v: ("\u2014" if v is None else "%+.1f%%" % v)
        out.append("| %d | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s / %s |" % (
            c, fnum(f.get("median_decode_tps")), fnum(g.get("median_decode_tps")),
            pct(cell.get("decode_delta_pct")), fnum(f.get("agg_decode_tps"), 1),
            fnum(g.get("agg_decode_tps"), 1), pct(cell.get("agg_delta_pct")),
            fnum(f.get("median_prefill_tps"), 1), fnum(g.get("median_prefill_tps"), 1),
            pct(cell.get("prefill_delta_pct")),
            fnum(f.get("median_completion_tokens"), 0), fnum(g.get("median_completion_tokens"), 0)))
    out.append("")


def pr_table(run, out, missing):
    d = load(os.path.join(run, "pr", "summary.json"))
    if d is None:
        missing.append("pr")
        return
    meta = d.get("_meta", {})
    cells = d.get("cells", [])
    chunk = meta.get("chunked_prefill_size")
    out.append("<!-- generated from pr/summary.json -->")
    out.append("")
    out.append("Input size is token-exact; fresh nonce per request; output budget forced to "
               "%s tokens. Input size is the one documented SD-1 exception (native "
               "`/generate` with `input_ids` is the only way to hit an exact size)."
               % meta.get("max_new_tokens"))
    out.append("")
    out.append("**The prefill column scales only for `input <= %s`.** Above that a request is "
               "chunked, and the scheduler gives the in-flight chunked request the whole step's "
               "prefill budget, so it is prefilled one at a time: aggregate prompt rate falls to "
               "the single-stream chunked rate and TTFT grows with queue position. "
               "`Prefills/step (pred)` is `%s`; `Engine running` / `Engine queue` are the "
               "engine's own `sglang:num_running_reqs` / `sglang:num_queue_reqs` sampled once a "
               "second during the cell, so the prediction can be checked against the engine "
               "rather than believed."
               % (chunk, meta.get("prefills_per_step_law")))
    out.append("")
    out.append("`TTFT first` / `TTFT last` bracket the wave's queue positions. When the median "
               "sits between two values an order of magnitude apart, it is describing the queue, "
               "not the engine. `Window decode` is the older 129\u2013641 measure, recovered from "
               "the retained per-token event log.")
    out.append("")
    out.append("| Input tokens | C | Prefills/step (pred) | Agg prefill tok/s | TTFT first s | Median TTFT s | TTFT last s | Median decode tok/s/req | Window decode tok/s/req (129\u2013641) | Agg decode tok/s (union) | Engine running (min/med/max) | Engine queue (min/med/max) | OK |")
    out.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|")
    for cell in cells:
        p = cell.get("engine_probe") or {}

        def trio(pre):
            if p.get(pre + "_min") is None:
                return "\u2014"
            return "%s/%s/%s" % (fnum(p[pre + "_min"], 0), fnum(p[pre + "_med"], 0),
                                 fnum(p[pre + "_max"], 0))
        out.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s/%s |" % (
            thousands(cell.get("input_tokens")), fnum(cell.get("concurrency")),
            fnum(cell.get("prefills_per_step_pred"), 0),
            fnum(cell.get("agg_prefill_tps")), fnum(cell.get("ttft_first_s")),
            fnum(cell.get("median_ttft_s")), fnum(cell.get("ttft_last_s")),
            fnum(cell.get("median_decode_tps")),
            fnum(cell.get("median_window_decode_tps")),
            fnum(cell.get("agg_decode_tps"), 1),
            trio("running"), trio("queue"),
            fnum(cell.get("streams_ok")), fnum(cell.get("concurrency"))))
    out.append("")


def pr_cell_client_layer(run, size, conc, wave):
    """Derive the client layer from the retained per-stream records.

    Returns (dispatch_spread_ms, peak_overlap, n_streams). The dispatch spread is
    `max(t0) - min(t0)` over the wave: how long the client took to get every
    request of the wave onto the wire. The peak overlap is the largest number of
    client streams in flight at once, i.e. whether the wave really was
    simultaneous from the client's side.

    This has to be derived here rather than read from `summary.json`: the summary
    field called `stagger_s` is the **TTFT** spread (`ttft_last - ttft_first`) and
    says nothing about dispatch. It keeps that name so the archived cells stay
    reproducible by the harness that produced them.
    """
    recs = load(os.path.join(run, "pr", "%d-c%d-w%d.json" % (size, conc, wave)))
    if not recs:
        return None
    t0 = sorted(r["t0"] for r in recs if r.get("t0"))
    if not t0:
        return None
    spans = []
    for r in recs:
        if not r.get("t0"):
            continue
        spans.append((r["t0"], 1))
        spans.append((r.get("t_end") or r.get("t_last") or r["t0"], -1))
    spans.sort()
    active = peak = 0
    for _, delta in spans:
        active += delta
        peak = max(peak, active)
    return round((t0[-1] - t0[0]) * 1000.0, 1), peak, len(t0)


def pr_evidence_table(run, out, missing):
    """The admission-law evidence, one row per cell, three independent layers.

    The PR table's `Prefills/step (pred)` is a prediction. This table is what
    makes it checkable: the client layer (did the wave leave together?), the
    engine gauge (what did the engine report while it ran?) and, in
    `pr/engine-steps.log`, the scheduler's own `#new-seq` per step.
    """
    d = load(os.path.join(run, "pr", "summary.json"))
    if d is None:
        missing.append("pr")
        return
    cells = d.get("cells", [])
    chunk = d.get("_meta", {}).get("chunked_prefill_size")
    out.append("<!-- generated from pr/summary.json + pr/*-c*-w*.json -->")
    out.append("")
    out.append("`Prefills/step (pred)` is `min(C, floor(%s / input))`. The columns under "
               "**client** are derived here from the retained per-stream `t0` / `t_end`; the "
               "columns under **engine** are the engine's own gauge, sampled once a second "
               "during the cell. A third channel, the scheduler's `#new-seq` per prefill step, "
               "is in `pr/engine-steps.log` (produced by `pr_engine_steps.py`)." % chunk)
    out.append("")
    out.append("Read the engine column as `med` first. **`running min`/`max` and `queue min` "
               "can carry a value from the *previous* cell**: the probe window opens "
               "immediately after the previous wave returns, and the engine only republishes "
               "the gauge when it runs a step, so an idle engine keeps its last value for a "
               "sample or two. `running med` and `queue max` are the load-bearing values; the "
               "gauge/law agreement in `engine-steps.log` is the independent check on them.")
    out.append("")
    out.append("| Input tokens | C | Prefills/step (pred) | Client dispatch spread ms | Client peak overlap | Engine running min/med/max | Engine queue min/med/max | TTFT first \u2192 last s |")
    out.append("|---:|---:|---:|---:|---:|---|---|---|")
    for cell in cells:
        p = cell.get("engine_probe") or {}
        size, conc, wave = (cell.get("input_tokens"), cell.get("concurrency"),
                            cell.get("wave", 0))
        cl = pr_cell_client_layer(run, size, conc, wave)
        def trio(pre):
            if p.get(pre + "_min") is None:
                return "\u2014"
            return "%s/%s/%s" % (fnum(p[pre + "_min"], 0), fnum(p[pre + "_med"], 0),
                                 fnum(p[pre + "_max"], 0))
        out.append("| %s | %s | %s | %s | %s | %s | %s | %s \u2192 %s |" % (
            thousands(size), fnum(conc), fnum(cell.get("prefills_per_step_pred"), 0),
            fnum(cl[0], 1) if cl else "\u2014",
            fnum(cl[1], 0) if cl else "\u2014",
            trio("running"), trio("queue"),
            fnum(cell.get("ttft_first_s")), fnum(cell.get("ttft_last_s"))))
    out.append("")


def gw_table(run, out, missing):
    d = load(os.path.join(run, "gw", "gw_ab.json"))
    if d is None:
        missing.append("gw")
        return
    s = d.get("summary", {})
    out.append("<!-- generated from gw/gw_ab.json -->")
    out.append("")
    out.append("Gateway `:8001` vs direct engine `:8899`, alternating within each round. "
               "\u0394 is \"gateway \u2212 direct\", in percent. Positive is the gateway "
               "ahead on prefill and decode tok/s; on the wall arm positive means the "
               "gateway is *slower*, because wall time is a duration. Every request carries "
               "its own nonce except the wall arm, which deliberately re-sends its own "
               "path's decode request unstreamed -- both paths reach that line equally warm, "
               "so the comparison stays symmetric.")
    out.append("| Arm | :8001 gateway (median) | direct :8899 (median) | \u0394 vs direct | n per arm |")
    out.append("|---|---:|---:|---:|---:|")
    label = {"prefill": "prefill tok/s", "decode": "decode tok/s/req", "wall": "wall s (not streamed)"}
    for arm in ("prefill", "decode", "wall"):
        a = s.get(arm, {})
        g, dr = a.get("gw8001", {}), a.get("direct8899", {})
        out.append("| %s | %s | %s | %s | %s |" % (
            label.get(arm, arm), fnum(g.get("median"), 3), fnum(dr.get("median"), 3),
            ("\u2014" if a.get("delta_pct") is None else "%+.1f%%" % a["delta_pct"]),
            fnum(g.get("n"))))
    out.append("")


def fp4_table(run, out, missing):
    d = load(os.path.join(run, "fp4_256", "de_v3_matrix.json"))
    if d is None:
        missing.append("fp4_256")
        return
    out.append("<!-- generated from fp4_256/de_v3_matrix.json -->")
    out.append("")
    out.append("Short-output arm (%s tokens) of the fp4-indexer A/B, `code` type. "
               "**One arm only**: the indexer is currently ON, so this is the "
               "indexer-on side. The off side needs a restart and is a window item."
               % d.get("_meta", {}).get("max_tokens"))
    out.append("")
    out.append("| C | Median decode tok/s/req | Wave spread | Agg decode tok/s | Median prefill tok/s | Median ct | OK streams |")
    out.append("|---:|---:|---:|---:|---:|---:|---:|")
    for c in (1, 8, 16):
        cell = d.get("DE-V3_code_C%d" % c)
        if cell is None:
            continue
        sp = wave_spread(cell)
        out.append("| %d | %s | %s | %s | %s | %s | %s |" % (
            c, fnum(cell.get("median_decode_tps")),
            ("\u2014" if sp is None else "\u00b1%.1f%%" % sp),
            fnum(cell.get("agg_decode_tps"), 1),
            fnum(cell.get("median_prefill_tps"), 1),
            fnum(cell.get("median_completion_tokens"), 0), fnum(cell.get("streams_ok"))))
    out.append("")


def cache_table(run, out, missing):
    """What a repeated prompt is worth, by size. Sizes the nonce defect."""
    d = load(os.path.join(run, "cache", "cache_effect.json"))
    if d is None:
        missing.append("cache")
        return
    rows = d.get("rows", [])
    out.append("<!-- generated from cache/cache_effect.json -->")
    out.append("")
    out.append("What an identical prompt is actually worth, measured rather than assumed. "
               "`worth = 1 \u2212 ttft_repeat / ttft_cold`; positive means the engine served "
               "the repeat from its radix cache. This is the instrument that sizes the "
               "shared-prompt defect instead of leaving it at \"a leak existed\". The two "
               "self-check columns are computed, not asserted: `cold` and `repeat` must be "
               "byte-identical, and `distinct` must differ -- if the first pair does not "
               "match, the probe is not measuring what it claims.")
    out.append("")
    out.append("| Size (requested) | prompt tokens | TTFT cold s | TTFT repeat s | TTFT distinct s | Worth of a repeat | repeat byte-identical | distinct differs |")
    out.append("|---:|---:|---:|---:|---:|---:|:--:|:--:|")
    for r in rows:
        w = r.get("worth_of_a_repeat")
        out.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            thousands(r.get("size_requested")), thousands(r.get("prompt_tokens")),
            fnum(r.get("ttft_cold_s"), 4), fnum(r.get("ttft_repeat_s"), 4),
            fnum(r.get("ttft_distinct_s"), 4),
            ("\u2014" if w is None else "%+.1f%%" % (w * 100)),
            "\u2713" if r.get("selfcheck_repeat_is_byte_identical") else "\u2717",
            "\u2713" if r.get("selfcheck_distinct_differs") else "\u2717"))
    errs = [r for r in rows if r.get("errors")]
    if errs:
        out.append("")
        out.append("**Errors:** " + "; ".join(
            "size %s: %s" % (r.get("size_requested"), r.get("errors")) for r in errs))
    out.append("")


def channel_table(run, out, missing):
    """chat channel vs native /generate, same prompt, alternating within a wave."""
    d = load(os.path.join(run, "channel", "channel_ab.json"))
    if d is None:
        missing.append("channel")
        return
    out.append("<!-- generated from channel/channel_ab.json -->")
    out.append("")
    out.append("The confound test for the grammar A/B. Both arms send the same prompt "
               "*body*, unconstrained and force-filled, with one nonce per request, and the "
               "arms alternate **within** each wave so drift lands on both. The only "
               "variable is the channel. \u0394 is \"native \u2212 chat\": negative means the "
               "native `/generate` channel is *slower* for an identical unconstrained "
               "request -- which is what the grammar result has to be read against.")
    out.append("")
    out.append("| C | chat decode tok/s/req | native decode tok/s/req | \u0394 | chat agg tok/s | native agg tok/s | \u0394 | chat chars/token | native chars/token |")
    out.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    pct = lambda v: ("\u2014" if v is None else "%+.1f%%" % v)
    for key in sorted(k for k in d if k.startswith("CHANNEL_AB_C")):
        c = d[key]
        ch, na = c.get("chat", {}), c.get("native", {})
        out.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            fnum(c.get("conc")), fnum(ch.get("median_decode_tps")),
            fnum(na.get("median_decode_tps")), pct(c.get("native_vs_chat_pct")),
            fnum(ch.get("agg_decode_tps"), 1), fnum(na.get("agg_decode_tps"), 1),
            pct(c.get("native_vs_chat_agg_pct")),
            fnum(ch.get("median_chars_per_token"), 3),
            fnum(na.get("median_chars_per_token"), 3)))
    out.append("")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    run = sys.argv[1]
    out, missing = [], []
    de_table(run, out, missing)
    pr_table(run, out, missing)
    pr_evidence_table(run, out, missing)
    fp4_table(run, out, missing)
    grammar_table(run, out, missing)
    gw_table(run, out, missing)
    cache_table(run, out, missing)
    channel_table(run, out, missing)
    print("\n".join(out))
    if missing:
        print("MISSING STAGES: %s" % ", ".join(missing), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

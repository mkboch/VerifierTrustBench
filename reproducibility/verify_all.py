#!/usr/bin/env python3
"""Reproduce the study's published numerical results from the public release alone.

    python -m reproducibility.verify_all [--out DIR] [--draws N] [--no-figures]

Runs eight stages and prints a PASS/FAIL line for every assertion it checks:

  1  checksums          every published data file matches docs/data/SHA256SUMS.txt
  2  schema             the per-cell table is structurally sound and self-consistent
  3  counts             rung-level numerators and denominators
  4  estimators         balanced accuracy and log-linear d' per rung
  5  contrasts          the six paired contrasts under BOTH weightings
  6  intervals          manuscript-cluster bootstrap, frozen generator and seed
  7  other experiments  broader benchmark, three-state task, agentic, transfer, frontier,
                        scorer audits
  8  outputs            result tables, and figures when matplotlib is installed

Every assertion is compared against reproducibility/manuscript_targets.json, which is read
ONLY for comparison. No analysis function reads it. A disagreement is reported as a
disagreement; nothing is nudged to make a line pass.

Requires no private path, no environment variable, no GPU and no paid model API.
"""
from __future__ import annotations
import argparse, csv, json, math, sys
from pathlib import Path

from . import contrasts as C
from . import data as D
from .estimators import aggregate, rates, wilson

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TARGETS = json.loads((HERE / "manuscript_targets.json").read_text())

ROWS = []       # (stage, item, expected, got, tol, status, note)
_fail = 0


def rnd(x, nd):
    """Round half away from zero, the manuscript's convention."""
    if x is None:
        return None
    f = 10 ** nd
    return math.floor(abs(x) * f + 0.5) / f * (1 if x >= 0 else -1)


OVERRIDE = TARGETS.get("canonical_overrides", {})


def check(stage, item, expected, got, tol=0.0, note="", nd=None):
    """Compare one computed value against its target.

    Where the manuscript's printed value is known to disagree with the frozen record, the
    CANONICAL value is asserted instead and the manuscript's value is reported as a
    discrepancy. A known display error must not be able to look like a reproduction
    failure, and must not be able to hide either.
    """
    global _fail
    ov = OVERRIDE.get(item)
    if ov and isinstance(ov, dict):
        ms = expected
        expected, nd, tol = ov["canonical"], ov.get("nd", nd), ov.get("tol", tol)
        note = (note + " " if note else "") + \
            f"canonical asserted; manuscript prints {ms} (see {ov['discrepancy']})"
    if expected is None or got is None:
        ok = expected is None and got is None
        diff = ""
    elif isinstance(expected, bool) or isinstance(got, bool):
        ok, diff = bool(expected) == bool(got), ""
    elif isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        g = rnd(got, nd) if nd is not None else got
        ok = abs(g - expected) <= tol + 1e-12
        diff = f"{g - expected:+.6g}"
    else:
        ok, diff = str(expected) == str(got), ""
    if not ok:
        _fail += 1
    ROWS.append({"stage": stage, "item": item, "expected": expected,
                 "got": rnd(got, nd) if (nd is not None and isinstance(got, float)) else got,
                 "tolerance": tol, "difference": diff,
                 "status": "PASS" if ok else "FAIL", "note": note})
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "reproduction_output"))
    ap.add_argument("--draws", type=int, default=10000,
                    help="bootstrap draws; the frozen analysis used 10000. Lowering this "
                         "changes interval endpoints and is for smoke-testing only.")
    ap.add_argument("--no-figures", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    exact = a.draws == 10000

    print(__doc__.strip().splitlines()[0])
    print(f"\nbootstrap draws: {a.draws}" + ("" if exact else
          "   *** NOT the frozen 10000: intervals will not match the manuscript ***"))

    # ---------------------------------------------------------------- 1 checksums
    print("\n[1] checksums")
    sums, ok = D.verify_checksums()
    for name, st, detail in sums:
        check("checksums", name, "PASS", st, note=detail)
        print(f"    {st}  {name}  {detail}")

    # ---------------------------------------------------------------- 2 schema
    print("\n[2] schema")
    doc, cells = D.load_cells()
    errs = D.validate_cells(doc, cells)
    check("schema", "per-cell table structurally valid", 0, len(errs), note="; ".join(errs))
    print(f"    {'PASS' if not errs else 'FAIL'}  {len(cells)} cells, "
          f"{doc['n_clusters']} clusters, {doc['n_relations']} relations")
    OW = [s["id"] for s in doc["systems"] if s["id"] != "gpt-5.2"]
    ds = TARGETS["dataset"]
    check("schema", "held-out manuscripts", ds["held_out_selected"], doc["n_clusters"])
    check("schema", "relations per system", ds["relations_per_system_extension"],
          doc["n_relations"])
    check("schema", "open-weight systems in the extension",
          ds["open_weight_systems_extension"], len(OW))
    check("schema", "defect families", ds["defect_families"], len(doc["families"]))
    check("schema", "domains", ds["domains"], len(doc["domains"]))

    # ------------------------------------------------- 3,4 counts and estimators
    print("\n[3] rung counts        [4] estimators")
    lad = {r["rung"]: r for r in C.ladder(cells, OW)}
    for t in TARGETS["canonical_ladder"]["rows"]:
        r = lad[t["rung"]]
        check("counts", f"{t['rung']} complete-case n", t["n"], r["n_e0"])
        check("counts", f"{t['rung']} E0 hits", t["hits"], r["hits"])
        check("counts", f"{t['rung']} E1 false alarms", t["false_alarms"],
              r["false_alarms"])
        check("counts", f"{t['rung']} E0 sensitivity %", t["sensitivity_pct"],
              100 * r["sensitivity"], tol=0.05, nd=1)
        check("counts", f"{t['rung']} E1 false-alarm rate %", t["false_alarm_rate_pct"],
              100 * r["false_alarm_rate"], tol=0.05, nd=1)
        check("estimators", f"{t['rung']} balanced accuracy %",
              t["balanced_accuracy_pct"], 100 * r["balanced_accuracy"], tol=0.05, nd=1)
        check("estimators", f"{t['rung']} d'", t["dprime"], r["dprime"],
              tol=0.0005, nd=3)
    for k in ("counts", "estimators"):
        n = sum(1 for r in ROWS if r["stage"] == k)
        f = sum(1 for r in ROWS if r["stage"] == k and r["status"] == "FAIL")
        print(f"    {'PASS' if not f else 'FAIL'}  {k}: {n - f}/{n}")

    # ------------------------------------------------- 5,6 contrasts, intervals
    print("\n[5] six paired contrasts   [6] cluster-bootstrap intervals")
    table = []
    for row in TARGETS["contrasts_table1"]["rows"]:
        a_, b_ = row["from"], row["to"]
        ba = C.contrast(cells, a_, b_, OW, "balanced_accuracy", "pooled", draws=a.draws)
        dp = C.contrast(cells, a_, b_, OW, "dprime", "pooled", draws=a.draws)
        bb = C.contrast(cells, a_, b_, OW, "balanced_accuracy", "system_balanced",
                        draws=a.draws)
        db = C.contrast(cells, a_, b_, OW, "dprime", "system_balanced", draws=a.draws)
        name = f"{a_}->{b_}"
        check("contrasts", f"{name} paired n", row["n"], ba["n_pairs"])
        check("contrasts", f"{name} balanced accuracy pp", row["balanced_accuracy_pp"],
              ba["point"], tol=0.005, nd=2)
        check("contrasts", f"{name} d'", row["dprime"], dp["point"], tol=0.005, nd=2)
        if exact:
            check("intervals", f"{name} BA CI lo", row["ba_ci"][0], ba["ci95_lo"],
                  tol=0.005, nd=2)
            check("intervals", f"{name} BA CI hi", row["ba_ci"][1], ba["ci95_hi"],
                  tol=0.005, nd=2)
            check("intervals", f"{name} d' CI lo", row["dp_ci"][0], dp["ci95_lo"],
                  tol=0.005, nd=2)
            check("intervals", f"{name} d' CI hi", row["dp_ci"][1], dp["ci95_hi"],
                  tol=0.005, nd=2)
        table.append({"contrast": name, "n_pairs": ba["n_pairs"],
                      "ba_pooled": ba["point"], "ba_pooled_lo": ba["ci95_lo"],
                      "ba_pooled_hi": ba["ci95_hi"],
                      "ba_balanced": bb["point"], "ba_balanced_lo": bb["ci95_lo"],
                      "ba_balanced_hi": bb["ci95_hi"],
                      "dp_pooled": dp["point"], "dp_pooled_lo": dp["ci95_lo"],
                      "dp_pooled_hi": dp["ci95_hi"],
                      "dp_balanced": db["point"], "dp_balanced_lo": db["ci95_lo"],
                      "dp_balanced_hi": db["ci95_hi"],
                      "pooled_excludes_zero_ba": ba["excludes_zero"],
                      "pooled_excludes_zero_dp": dp["excludes_zero"],
                      "balanced_excludes_zero_dp": db["excludes_zero"]})
    u = TARGETS["unrounded_central_result"]
    ba = C.contrast(cells, "relation", "binary", OW, "balanced_accuracy", "pooled",
                    draws=a.draws)
    dp = C.contrast(cells, "relation", "binary", OW, "dprime", "pooled", draws=a.draws)
    cr = C.contrast(cells, "category", "relation", OW, "dprime", "pooled", draws=a.draws)
    check("contrasts", "unrounded central balanced accuracy pp",
          u["balanced_accuracy_pp"], ba["point"], tol=0.0005, nd=3)
    check("contrasts", "unrounded central d'", u["dprime"], dp["point"],
          tol=0.0005, nd=3)
    check("contrasts", "unrounded category->relation d'",
          u["category_to_relation_dprime"], cr["point"], tol=0.0005, nd=3)
    if exact:
        for lbl, want, got in [("BA CI lo", u["ba_ci"][0], ba["ci95_lo"]),
                               ("BA CI hi", u["ba_ci"][1], ba["ci95_hi"]),
                               ("d' CI lo", u["dp_ci"][0], dp["ci95_lo"]),
                               ("d' CI hi", u["dp_ci"][1], dp["ci95_hi"]),
                               ("cat->rel d' CI lo", u["category_to_relation_dp_ci"][0],
                                cr["ci95_lo"]),
                               ("cat->rel d' CI hi", u["category_to_relation_dp_ci"][1],
                                cr["ci95_hi"])]:
            check("intervals", f"unrounded {lbl}", want, got, tol=0.0005, nd=3)
    for t in TARGETS["weighting_sensitive_dprime"]:
        r = C.contrast(cells, t["from"], t["to"], OW, "dprime", t["weighting"],
                       draws=a.draws)
        nm = f"{t['from']}->{t['to']} {t['weighting']}"
        check("weighting", f"{nm} d'", t["dprime"], r["point"], tol=0.005, nd=2)
        if exact:
            check("weighting", f"{nm} CI lo", t["ci"][0], r["ci95_lo"], tol=0.005, nd=2)
            check("weighting", f"{nm} CI hi", t["ci"][1], r["ci95_hi"], tol=0.005, nd=2)
            check("weighting", f"{nm} excludes zero", t["excludes_zero"],
                  r["excludes_zero"])
    for k in ("contrasts", "intervals", "weighting"):
        n = sum(1 for r in ROWS if r["stage"] == k)
        f = sum(1 for r in ROWS if r["stage"] == k and r["status"] == "FAIL")
        if n:
            print(f"    {'PASS' if not f else 'FAIL'}  {k}: {n - f}/{n}")

    # ---------------------------------------------------------- 7 other experiments
    print("\n[7] other experiments")
    stats = D.load("public_sufficient_statistics.json")
    rr = D.load("research_results.json")
    sa = D.load("scorer_audit_items.json")

    bb_ = TARGETS["broader_benchmark"]
    dv = stats["experiments"]["discovery_vs_localized"]["pooled"]
    check("experiments", "broader blind x", bb_["blind"]["x"], dv["blind"]["x"])
    check("experiments", "broader blind n", bb_["blind"]["n"], dv["blind"]["n"])
    check("experiments", "broader localized x", bb_["relation_localized"]["x"],
          dv["targeted"]["x"])
    check("experiments", "broader localized n", bb_["relation_localized"]["n"],
          dv["targeted"]["n"])
    diff = 100 * (dv["targeted"]["x"] - dv["blind"]["x"]) / dv["blind"]["n"]
    check("experiments", "broader difference pp", bb_["difference_pp"], diff,
          tol=0.05, nd=1)

    ts = TARGETS["three_state_localized"]
    tr = rr["three_state_localized"]
    for k, key in [("E0", "E0_defective"), ("E1", "E1_as_published"),
                   ("E2", "E2_alternate"), ("all_three", "correct_in_all_three")]:
        check("experiments", f"three-state {k} x", ts[k]["x"], tr[key]["x"])
        check("experiments", f"three-state {k} n", ts[k]["n"], tr[key]["n"])
        check("experiments", f"three-state {k} %", ts[k]["pct"],
              100 * tr[key]["x"] / tr[key]["n"], tol=0.05, nd=1)
    check("experiments", "cited relation but wrong verdict",
          ts["cited_relation_but_wrong_verdict"], tr["cited_relation_but_wrong_verdict"])

    ag, at = TARGETS["agentic"], stats["experiments"]["agentic"]
    check("experiments", "agentic direct x", ag["direct"]["x"], at["direct_blind"]["x"])
    check("experiments", "agentic agentic x", ag["agentic"]["x"], at["agentic_blind"]["x"])
    check("experiments", "agentic difference pp", ag["difference_pp"],
          100 * (at["agentic_blind"]["x"] - at["direct_blind"]["x"]) / at["n_paired_cases"],
          tol=0.05, nd=1)

    fz = stats["experiments"]["information_transfer"]["frozen_contrasts"]
    ti = TARGETS["information_transfer"]
    for key in ("relevant_vs_irrelevant_rationale", "relevant_vs_filler"):
        spec = ti[key]
        fc = fz[spec["contrast"]]
        # paired discordant cells: (b - c) / n, never a difference of two arm rates
        pp = 100 * (fc["b"] - fc["c"]) / fc["n"]
        check("experiments", f"transfer {key} pp", spec["manuscript_pp"], pp,
              tol=0.05, nd=1, note="paired (b-c)/n on the frozen contrast")

    an = rr["frontier"]["anthropic"]
    fc = TARGETS["frontier_claude_sonnet_5_5"]
    acc = an["accuracy"]["primary_strict_parser"]
    check("experiments", "Claude strict verdicts", fc["strict_parsed_verdicts"],
          acc["n_scored"])
    check("experiments", "Claude strict correct", fc["strict_correct"], acc["n_correct"])
    check("experiments", "Claude strict accuracy %", fc["strict_accuracy_pct"],
          acc["accuracy_pct"], tol=0.05, nd=1)
    check("experiments", "Claude refusals are not scored as errors", True,
          acc["n_scored"] < 60, note="strict denominator excludes refused/unparseable")

    t = sa["audits"]["targeted"]; b = sa["audits"]["blind"]
    LV = ["Yes", "Partially", "No", "Ambiguous / Cannot determine"]
    tot = {k: sum(i["counts"][k] for i in t["items"]) for k in LV}
    nj = sum(tot.values())
    check("experiments", "targeted audit judgments",
          TARGETS["scorer_audit"]["targeted_audit"]["judgments"], nj)
    check("experiments", "targeted endorsement %",
          TARGETS["scorer_audit"]["targeted_endorsement_pct"], 100 * tot["No"] / nj,
          tol=0.05, nd=1)

    def maj(c):
        m = max(c.values())
        for k in LV:
            if c[k] == m:
                return k
    check("experiments", "unanimous targeted items",
          TARGETS["scorer_audit"]["unanimous_targeted_items"],
          sum(1 for i in t["items"] if max(i["counts"].values()) == i["n_reviewers"]))
    num = den = 0.0
    strata = {}
    for i in t["items"]:
        strata.setdefault(i["stratum"], {"yes": 0, "n": 0, "pop": i["stratum_population"]})
        strata[i["stratum"]]["n"] += 1
        strata[i["stratum"]]["yes"] += 1 if maj(i["counts"]) == "Yes" else 0
    for s, v in strata.items():
        num += v["pop"] * v["yes"] / v["n"]; den += v["pop"]
    check("experiments", "targeted reweighted false-negative %",
          TARGETS["scorer_audit"]["targeted_reweighted_false_negative_pct"],
          100 * num / den, tol=0.05, nd=1,
          note="recomputed from published per-item counts")
    check("experiments", "blind audit judgments",
          TARGETS["scorer_audit"]["blind_audit"]["judgments"],
          sum(sum(i["counts"].values()) for i in b["items"]))
    gl = rr["gold_label_validation"]["agreement_overall"]
    check("experiments", "gold-label agreement x",
          TARGETS["scorer_audit"]["gold_label_validation"]["x"], gl["x"])
    check("experiments", "gold-label agreement n",
          TARGETS["scorer_audit"]["gold_label_validation"]["n"], gl["n"])
    check("experiments", "gold-label agreement %",
          TARGETS["scorer_audit"]["gold_label_validation"]["pct"],
          100 * gl["x"] / gl["n"], tol=0.05, nd=1)

    sc = rr["scorer_correction_scenarios"]["scenarios"]
    sct = TARGETS["scorer_audit"]
    check("experiments", "conservative one-sided BA pp (one_sided_with_partial)",
          sct["conservative_one_sided_balanced_accuracy_pp"],
          sc["one_sided_with_partial"]["balanced_accuracy_difference_pp"],
          tol=0.05, nd=1)
    check("experiments", "earlier public aggregate (one_sided_strict) BA pp",
          sct["earlier_public_aggregate_one_sided_strict_pp"],
          sc["one_sided_strict"]["balanced_accuracy_difference_pp"], tol=0.005, nd=2)
    check("experiments", "one-sided d' interval includes zero", False,
          sc["one_sided_with_partial"]["dprime_difference_excludes_zero"])
    n = sum(1 for r in ROWS if r["stage"] == "experiments")
    f = sum(1 for r in ROWS if r["stage"] == "experiments" and r["status"] == "FAIL")
    print(f"    {'PASS' if not f else 'FAIL'}  experiments: {n - f}/{n}")

    # ---------------------------------------------------------------- 8 outputs
    print("\n[8] outputs")
    with open(out / "table1_contrasts.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(table[0]))
        w.writeheader(); w.writerows(table)
    with open(out / "ladder_table.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["rung", "n_e0", "hits", "sensitivity_pct", "n_e1", "false_alarms",
                    "false_alarm_pct", "balanced_accuracy_pct", "dprime"])
        for r in C.ladder(cells, OW):
            w.writerow([r["rung"], r["n_e0"], r["hits"], f"{100*r['sensitivity']:.1f}",
                        r["n_e1"], r["false_alarms"], f"{100*r['false_alarm_rate']:.1f}",
                        f"{100*r['balanced_accuracy']:.1f}", f"{r['dprime']:.3f}"])
    print(f"    PASS  wrote table1_contrasts.csv, ladder_table.csv")
    figs = 0
    if not a.no_figures:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            lad2 = C.ladder(cells, OW)
            fig, ax = plt.subplots(figsize=(7, 3.6), constrained_layout=True)
            x = range(len(lad2))
            ax.bar([i - 0.2 for i in x], [100 * r["sensitivity"] for r in lad2], 0.4,
                   label="E0 sensitivity")
            ax.bar([i + 0.2 for i in x], [100 * r["false_alarm_rate"] for r in lad2], 0.4,
                   label="E1 false-alarm rate")
            ax.set_xticks(list(x))
            ax.set_xticklabels([r["rung"] for r in lad2])
            ax.set_ylabel("per cent")
            ax.set_title("Four-rung ladder: detection and false alarms (descriptive)")
            ax.legend(frameon=False)
            fig.savefig(out / "fig_ladder.png", dpi=150); plt.close(fig)
            fig, ax = plt.subplots(figsize=(7, 4), constrained_layout=True)
            ys = list(range(len(table)))[::-1]
            ax.errorbar([r["ba_pooled"] for r in table], ys, fmt="o",
                        xerr=[[r["ba_pooled"] - r["ba_pooled_lo"] for r in table],
                              [r["ba_pooled_hi"] - r["ba_pooled"] for r in table]],
                        capsize=3)
            ax.axvline(0, color="k", lw=0.8)
            ax.set_yticks(ys)
            ax.set_yticklabels([r["contrast"] for r in table])
            ax.set_xlabel("balanced-accuracy difference (pp), pooled")
            ax.set_title("Six paired contrasts, manuscript-cluster bootstrap")
            fig.savefig(out / "fig_contrasts.png", dpi=150); plt.close(fig)
            figs = 2
            print(f"    PASS  wrote fig_ladder.png, fig_contrasts.png")
        except ImportError:
            print("    SKIP  matplotlib not installed; figures not regenerated")

    # ------------------------------------------------- manuscript discrepancies
    print("\n[*] manuscript vs canonical record")
    disc = TARGETS["manuscript_vs_canonical_discrepancies"]["items"]
    for d_ in disc:
        ROWS.append({"stage": "discrepancy", "item": f"{d_['id']} {d_['where']}",
                     "expected": d_["manuscript"], "got": d_["canonical"],
                     "tolerance": "", "difference": "",
                     "status": "DISCREPANCY", "note": d_["why"]})
        print(f"    {d_['id']}  {d_['where']}: manuscript {d_['manuscript']}, "
              f"canonical {d_['canonical']}")
    print(f"    {len(disc)} recorded discrepancies -- reported, not reconciled")

    # ---------------------------------------------------------------- report
    with open(out / "RECONCILIATION.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["stage", "item", "expected", "got",
                                           "tolerance", "difference", "status", "note"])
        w.writeheader(); w.writerows(ROWS)
    npass = sum(1 for r in ROWS if r["status"] == "PASS")
    ndisc = sum(1 for r in ROWS if r["status"] == "DISCREPANCY")
    nassert = len(ROWS) - ndisc
    summary = {
        "assertions_checked": nassert, "passed": npass, "failed": nassert - npass,
        "manuscript_discrepancies_reported": ndisc,
        "bootstrap_draws": a.draws, "exact_frozen_bootstrap": exact,
        "figures_written": figs,
        "scope": ("Every assertion compares a value computed from the public research "
                  "data against the manuscript value recorded in manuscript_targets.json. "
                  "This is 100% parity across THIS set of assertions, which is not the "
                  "same as the whole manuscript being verified."),
        "failures": [r for r in ROWS if r["status"] == "FAIL"],
    }
    (out / "RECONCILIATION.json").write_text(json.dumps(summary, indent=1))
    print(f"\n{'='*64}\n{npass}/{nassert} assertions PASS"
          f"{'' if npass == nassert else f'   {nassert-npass} FAIL'}"
          f"   plus {ndisc} manuscript discrepancies reported")
    if npass != nassert:
        for r in ROWS:
            if r["status"] == "FAIL":
                print(f"  FAIL [{r['stage']}] {r['item']}: expected {r['expected']}, "
                      f"got {r['got']} ({r['note']})")
    print(f"wrote {out}/RECONCILIATION.csv and RECONCILIATION.json")
    return 0 if npass == nassert else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Sections 1, 3 and 4: the fair-scoring ladder metrics and the four-view re-estimate.

Per rung and per system:
  E0 sensitivity, E1 false-alarm rate, specificity, balanced accuracy, d', and the
  paired E0-detect-and-E1-clear trajectory.

Then four views of the relation-targeted versus binary difference, each with a
manuscript-cluster bootstrap interval, and the decision label those four views support.

Pooled d' is computed from pooled hit and false-alarm rates and is labelled as such. It is
never presented as the mean of the per-system d'.
"""
from __future__ import annotations
import collections, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fairlib as F  # noqa: E402

OUT = Path(__file__).resolve().parents[1]
SYSTEMS = F.OPENWEIGHT + [F.FRONTIER]
GATED = "RELATION_LOCALIZED_BINARY_VERDICT"


def cells_ok(f, system, rung):
    """Cells usable for the E0/E1 comparison: both states produced a scoreable response."""
    out = []
    for c in f.rows(system, rung):
        if c.get("e0_status") == "OK" and c.get("e1_status") == "OK":
            out.append(c)
    return out


def rates(cells, e0_key="e0_correct"):
    hits = sum(c.get(e0_key, 0) for c in cells)
    fas = sum(c.get("e1_false_alarm", 0) for c in cells)
    n = len(cells)
    if n == 0:
        return None
    sens = hits / n
    far = fas / n
    spec = 1 - far
    bal = (sens + spec) / 2
    d, hh, ff = F.loglinear_dprime(hits, n, fas, n)
    paired = sum(1 for c in cells if c.get(e0_key, 0) and not c.get("e1_false_alarm", 0))
    return {"n": n, "hits": hits, "false_alarms": fas,
            "sensitivity_pct": round(100 * sens, 1),
            "false_alarm_rate_pct": round(100 * far, 1),
            "specificity_pct": round(100 * spec, 1),
            "balanced_accuracy_pct": round(100 * bal, 1),
            "dprime": round(d, 3),
            "dprime_corrected_hit_rate": round(hh, 4),
            "dprime_corrected_fa_rate": round(ff, 4),
            "paired_detect_and_clear": paired,
            "paired_detect_and_clear_pct": round(100 * paired / n, 1)}


def boot(cells, stat):
    units = collections.defaultdict(list)
    for c in cells:
        units[c["paper"]].append(c)
    return F.cluster_bootstrap(units, stat)


def main() -> int:
    f = F.Fair()
    res = {"label": "FAIR_SCORING_LADDER_METRICS",
           "dprime_correction": "log-linear (Hautus 1995), applied unconditionally",
           "bootstrap": {"draws": F.BOOT_DRAWS, "seed": F.BOOT_SEED, "unit": "manuscript"},
           "per_system_per_rung": {}, "pooled_per_rung": {}, "coverage": {}}

    # ---------------- per system, per rung
    for s in SYSTEMS:
        res["per_system_per_rung"][s] = {}
        for g in F.RUNGS:
            cs = cells_ok(f, s, g)
            r = rates(cs)
            if r is None:
                res["per_system_per_rung"][s][F.RUNG_SHORT[g]] = {"status": "NO_DATA"}
                continue
            if g == GATED:
                pg = rates(cs, e0_key="e0_prov_gated")
                r["provenance_gated"] = {
                    "sensitivity_pct": pg["sensitivity_pct"],
                    "balanced_accuracy_pct": pg["balanced_accuracy_pct"],
                    "dprime": pg["dprime"],
                    "paired_detect_and_clear_pct": pg["paired_detect_and_clear_pct"],
                    "hits": pg["hits"]}
            res["per_system_per_rung"][s][F.RUNG_SHORT[g]] = r

    # ---------------- pooled per rung
    for g in F.RUNGS:
        cs = [c for s in F.OPENWEIGHT for c in cells_ok(f, s, g)]
        r = rates(cs)
        r["note_on_pooled_dprime"] = ("d' calculated from pooled hit/false-alarm rates; "
                                      "this is NOT the mean of the per-system d'")
        per = [res["per_system_per_rung"][s][F.RUNG_SHORT[g]]["dprime"]
               for s in F.OPENWEIGHT
               if res["per_system_per_rung"][s][F.RUNG_SHORT[g]].get("dprime") is not None]
        r["mean_of_per_system_dprime"] = round(sum(per) / len(per), 3) if per else None
        if g == GATED:
            pg = rates(cs, e0_key="e0_prov_gated")
            r["provenance_gated"] = {k: pg[k] for k in
                                     ("sensitivity_pct", "balanced_accuracy_pct", "dprime",
                                      "paired_detect_and_clear_pct", "hits")}
        res["pooled_per_rung"][F.RUNG_SHORT[g]] = r

    # ---------------- coverage
    for s in SYSTEMS:
        res["coverage"][s] = {F.RUNG_SHORT[g]: {
            "cells": 60,
            "e0_ok": sum(1 for c in f.rows(s, g) if c.get("e0_status") == "OK"),
            "e1_ok": sum(1 for c in f.rows(s, g) if c.get("e1_status") == "OK"),
            "both_ok": len(cells_ok(f, s, g))} for g in F.RUNGS}

    # ---------------- section 4: four views of relation-targeted vs binary
    REL, BIN = "RELATION_TARGETED_FINDING_LIST", GATED
    views = {}

    def paired_cells(s=None):
        """Cells where BOTH rungs are scoreable in both states, for the same relation."""
        out = []
        syss = [s] if s else F.OPENWEIGHT
        for sy in syss:
            rel = {c["case_id"]: c for c in cells_ok(f, sy, REL)}
            bi = {c["case_id"]: c for c in cells_ok(f, sy, BIN)}
            for cid in sorted(set(rel) & set(bi)):
                out.append({"paper": rel[cid]["paper"], "rel": rel[cid], "bin": bi[cid]})
        return out

    pc = paired_cells()

    def mk(name, fn, desc):
        units = collections.defaultdict(list)
        for x in pc:
            units[x["paper"]].append(x)
        pt, lo, hi, nb = F.cluster_bootstrap(units, fn)
        views[name] = {"description": desc, "difference": round(pt, 2) if pt is not None else None,
                       "ci95": [round(lo, 2), round(hi, 2)] if lo is not None else None,
                       "n_paired_cells": len(pc),
                       "n_manuscripts": len({x["paper"] for x in pc}),
                       "bootstrap_draws_used": nb}

    def _rate(xs, side, key):
        return sum(x[side].get(key, 0) for x in xs) / len(xs) if xs else None

    mk("A_raw_E0_difference",
       lambda xs: 100 * (_rate(xs, "bin", "e0_correct") - _rate(xs, "rel", "e0_correct")),
       "Raw E0 performance difference: correct binary verdict minus strict relation-targeted "
       "discovery. This is the original headline quantity, unadjusted.")

    mk("B_provenance_gated_E0_difference",
       lambda xs: 100 * (_rate(xs, "bin", "e0_prov_gated") - _rate(xs, "rel", "e0_correct")),
       "Provenance-gated binary E0 minus strict relation-targeted discovery. The binary rung "
       "must now both answer correctly AND cite a line that carries the tested relation, which "
       "is closer to what the finding-list rung is required to do.")

    def balacc(xs, side, key="e0_correct"):
        sens = _rate(xs, side, key)
        far = _rate(xs, side, "e1_false_alarm")
        return 100 * ((sens + (1 - far)) / 2)

    mk("C_balanced_accuracy_difference",
       lambda xs: balacc(xs, "bin") - balacc(xs, "rel"),
       "Balanced-accuracy difference using E0 and E1. Both rungs are now charged for false "
       "alarms on the unmodified manuscript, so neither is rewarded for a low chance floor "
       "alone.")

    def dp(xs, side, key="e0_correct"):
        n = len(xs)
        h = sum(x[side].get(key, 0) for x in xs)
        fa = sum(x[side].get("e1_false_alarm", 0) for x in xs)
        return F.loglinear_dprime(h, n, fa, n)[0]

    mk("D_dprime_difference",
       lambda xs: dp(xs, "bin") - dp(xs, "rel"),
       "d' difference, pooled hit and false-alarm rates, log-linear correction. Separates "
       "discriminability from response bias.")

    mk("C2_balanced_accuracy_difference_provenance_gated",
       lambda xs: balacc(xs, "bin", "e0_prov_gated") - balacc(xs, "rel"),
       "Balanced accuracy with the binary rung ALSO provenance-gated: the strictest fair "
       "comparison available from these data.")

    mk("D2_dprime_difference_provenance_gated",
       lambda xs: dp(xs, "bin", "e0_prov_gated") - dp(xs, "rel"),
       "d' difference with the binary rung provenance-gated.")

    res["section4_four_views"] = views

    # per-system version of the four views
    res["section4_per_system"] = {}
    for s in SYSTEMS:
        xs = paired_cells(s)
        if not xs:
            continue
        res["section4_per_system"][s] = {
            "n": len(xs),
            "A_raw_pp": round(100 * (_rate(xs, "bin", "e0_correct")
                                     - _rate(xs, "rel", "e0_correct")), 1),
            "B_prov_gated_pp": round(100 * (_rate(xs, "bin", "e0_prov_gated")
                                            - _rate(xs, "rel", "e0_correct")), 1),
            "C_balacc_pp": round(balacc(xs, "bin") - balacc(xs, "rel"), 1),
            "C2_balacc_gated_pp": round(balacc(xs, "bin", "e0_prov_gated")
                                        - balacc(xs, "rel"), 1),
            "D_dprime": round(dp(xs, "bin") - dp(xs, "rel"), 3),
            "D2_dprime_gated": round(dp(xs, "bin", "e0_prov_gated") - dp(xs, "rel"), 3),
        }

    # ---------------- decision
    def sig(v):
        c = views[v]["ci95"]
        return c is not None and (c[0] > 0 or c[1] < 0)

    allpos = all(views[v]["difference"] > 0 for v in
                 ("A_raw_E0_difference", "C_balanced_accuracy_difference", "D_dprime_difference"))
    fair_sig = sig("C_balanced_accuracy_difference") and sig("D_dprime_difference")
    shrink = (views["C_balanced_accuracy_difference"]["difference"]
              / views["A_raw_E0_difference"]["difference"]
              if views["A_raw_E0_difference"]["difference"] else None)
    if allpos and fair_sig and shrink is not None and shrink >= 0.75:
        label = "FORMAT_EFFECT_SURVIVES_FAIR_SCORING"
    elif allpos and fair_sig:
        label = "FORMAT_AND_SCORING_BOTH_CONTRIBUTE"
    elif not fair_sig:
        label = ("RAW_FORMAT_EFFECT_LARGELY_EXPLAINED_BY_SCORING_BIAS"
                 if shrink is not None and shrink < 0.5 else "INCONCLUSIVE")
    else:
        label = "INCONCLUSIVE"
    res["section4_decision"] = {
        "label": label,
        "decision_rule": "FORMAT_EFFECT_SURVIVES_FAIR_SCORING requires all of the raw, "
                         "balanced-accuracy and d' differences to point the same way, the two "
                         "fair-scoring intervals to exclude zero, and the balanced-accuracy "
                         "difference to retain at least 75% of the raw difference. "
                         "FORMAT_AND_SCORING_BOTH_CONTRIBUTE is the same but with material "
                         "shrinkage. RAW_FORMAT_EFFECT_LARGELY_EXPLAINED_BY_SCORING_BIAS "
                         "requires the fair-scoring intervals to include zero and the "
                         "balanced-accuracy difference to retain under half the raw difference.",
        "fraction_of_raw_difference_retained_under_balanced_accuracy":
            round(shrink, 3) if shrink is not None else None,
        "balanced_accuracy_interval_excludes_zero": sig("C_balanced_accuracy_difference"),
        "dprime_interval_excludes_zero": sig("D_dprime_difference"),
    }

    (OUT / "data/FAIR_LADDER_METRICS.json").write_text(json.dumps(res, indent=1) + "\n")

    # ---------------- console
    print(f"{'system':13s}{'rung':10s}{'n':>4}{'sens%':>7}{'FA%':>6}{'spec%':>7}"
          f"{'bal%':>7}{'dprime':>8}{'D&C%':>7}")
    for s in SYSTEMS:
        for g in F.RUNGS:
            r = res["per_system_per_rung"][s][F.RUNG_SHORT[g]]
            if r.get("status") == "NO_DATA":
                print(f"{s:13s}{F.RUNG_SHORT[g]:10s}  NO DATA")
                continue
            print(f"{s:13s}{F.RUNG_SHORT[g]:10s}{r['n']:>4}{r['sensitivity_pct']:>7.1f}"
                  f"{r['false_alarm_rate_pct']:>6.1f}{r['specificity_pct']:>7.1f}"
                  f"{r['balanced_accuracy_pct']:>7.1f}{r['dprime']:>8.2f}"
                  f"{r['paired_detect_and_clear_pct']:>7.1f}")
    print("\nSection 4 views (binary minus relation-targeted):")
    for k, v in views.items():
        ci = f"[{v['ci95'][0]:+.2f}, {v['ci95'][1]:+.2f}]" if v["ci95"] else "n/a"
        print(f"  {k:48s} {v['difference']:+8.2f}  95% CI {ci}")
    print(f"\nDECISION: {label}")
    print(f"  balanced accuracy retains "
          f"{res['section4_decision']['fraction_of_raw_difference_retained_under_balanced_accuracy']}"
          f" of the raw difference")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Experiment 2B frozen decision rules (applied mechanically by evaluate.py). Written before any 2B inference.

Thresholds (all pre-specified):
  T1 integrity       every evidence, blind and matrix cell (model x experiment) >= 95% valid; 0 fingerprint mismatches;
                     0 unplanned records. Pair cells are exploratory and do not enter T1.
  T2 usable papers   a paper is usable when (a) every primary model has >= 95% valid evidence trials on its 36 case-states,
                     (b) >= 95% valid blind audits on its 12 E0 manuscripts, and (c) no primary model has more than 2 of its
                     12 case relations flagged FALSE_POSITIVE in the blind audit of the unmodified paper.
                     Requires >= 4 of 5 papers usable.
  T3 no leakage      pooled share of valid E0 blind audits with a generic foreign-text objection on a target line <= 10%,
                     and pooled share of valid E0 targeted outputs using those terms exceeds the E1 share by <= 5 points.
  H1 replicates      pooled over models and the five papers: targeted-only > blind-only with exact McNemar p < 0.05;
                     targeted-only > blind-only in >= 4 of 5 papers (pooled over models); every leave-one-paper-out
                     pooled test p < 0.05; every leave-one-family-out pooled test keeps targeted-only > blind-only.
  H2 meaningful      at least one primary model has pooled full-trajectory rate >= 50% with Wilson lower bound >= 35%,
                     and that model's trajectory rate is >= 40% in every leave-one-paper-out subset.
  H3 interpretable   POSITIVE: pooled correct_rationale vs correct_verdict helpful > harmful with McNemar p < 0.05 and
                     helpful >= harmful in every leave-one-paper-out subset. CONSTRAINING_NULL: not positive, >= 20 paired
                     blocks, and the pooled 95% CI of the accuracy difference lies within [-0.05, +0.05].
                     Otherwise UNINTERPRETABLE.
  S1 (secondary)     DEMONSTRATED if pooled false_verdict vs neutral or false_rationale vs neutral has harmful > helpful,
                     p < 0.05, and harmful > helpful in every leave-one-paper-out subset.

Decision:
  READY_FOR_MANUSCRIPT  T1, T2, T3, H1, H2 hold and H3 is POSITIVE or CONSTRAINING_NULL.
  STOP                  T1, T2, T3 hold; H1 pooled not significant (or reversed); H2 fails; H3 not POSITIVE; S1 not demonstrated.
  PIVOT                 T1, T2, T3 hold; H1 pooled not significant (or reversed) and H2 fails; but H3 POSITIVE or S1 DEMONSTRATED.
  REVISE_2B             every other case (a technical/benchmark criterion fails, or H1/H2 hold only partly, or H3 uninterpretable).
2B does not lead to another experiment automatically.
"""
from __future__ import annotations


def decide(out: dict, E) -> dict:
    integ = out["integrity"]
    prim_cells = [c for c in integ["cells"] if c["experiment"] in ("evidence", "blind", "matrix")]
    t1_fail = [(c["experiment"], c["model"], c["valid_rate"]) for c in prim_cells if c["valid_rate"] < 0.95]
    t1 = not t1_fail and not integ["fingerprint_mismatches"] and not integ["unplanned_records"]

    usable, paper_detail = [], {}
    for p in E.papers:
        pcases = [c for c in E.cases if c["paper"] == p]
        ev_ok = all(sum(1 for c in pcases for s in ("E0", "E1", "E2")
                        if E.ev.get(f"evidence::{m}::{c['case_id']}::{s}") and E.ev[f"evidence::{m}::{c['case_id']}::{s}"]["result"]["status"] == "OK")
                    >= 0.95 * 3 * len(pcases) for m in E.models)
        bl_ok = all(sum(1 for c in pcases if E.bl.get(f"blind::{m}::{c['case_id']}::E0") and E.bl[f"blind::{m}::{c['case_id']}::E0"]["result"]["status"] == "OK")
                    >= 0.95 * len(pcases) for m in E.models)
        fp_ok = all(out["blind"][m]["clean_false_positives"].get(p, 0) <= 2 for m in E.models)
        paper_detail[p] = {"evidence_valid": ev_ok, "blind_valid": bl_ok, "clean_fp_ok": fp_ok}
        if ev_ok and bl_ok and fp_ok:
            usable.append(p)
    t2 = len(usable) >= 4

    bl = out["blind"]
    gx = sum(bl[m]["generic_on_target"]["x"] for m in E.models)
    gn = sum(bl[m]["generic_on_target"]["n"] for m in E.models)
    lk = out["leakage_targeted_text"]

    def pooled(state):
        x = sum(lk.get(f"{m}|{state}", {"x": 0})["x"] for m in E.models)
        n = sum(lk.get(f"{m}|{state}", {"n": 0})["n"] for m in E.models)
        return x / n if n else 0.0
    t3 = (gn > 0 and gx / gn <= 0.10) and (pooled("E0") - pooled("E1") <= 0.05)

    h1 = out["h1"]
    pool = h1["by_model"]["POOLED"]
    h1_pooled = pool["first_only"] > pool["second_only"] and pool["mcnemar_p"] < 0.05
    papers_dir = [p for p in E.papers if h1["by_model_paper"][f"POOLED|{p}"]["first_only"] > h1["by_model_paper"][f"POOLED|{p}"]["second_only"]]
    lopo_ok = all(h1["lopo"][f"POOLED|without {p}"]["mcnemar_p"] < 0.05 and
                  h1["lopo"][f"POOLED|without {p}"]["first_only"] > h1["lopo"][f"POOLED|without {p}"]["second_only"] for p in E.papers)
    lofo_ok = all(h1["lofo"][f"POOLED|without {f}"]["first_only"] > h1["lofo"][f"POOLED|without {f}"]["second_only"] for f in E.families)
    h1_holds = h1_pooled and len(papers_dir) >= 4 and lopo_ok and lofo_ok

    h2 = out["h2"]
    h2_models = []
    for m in E.models:
        t = h2["by_model"][m]["trajectory"]
        if t["n"] and t["rate"] >= 0.5 and t["ci95"][0] >= 0.35 and all(
                (h2["lopo"][f"{m}|without {p}"]["trajectory"]["rate"] or 0) >= 0.40 for p in E.papers):
            h2_models.append(m)
    h2_holds = bool(h2_models)

    h3b = out["matrix"]["h3_correct_rationale_vs_correct_verdict"]
    hp = h3b["pooled"]
    if hp["helpful"] > hp["harmful"] and hp["mcnemar_p"] < 0.05 and all(v["helpful"] >= v["harmful"] for v in h3b["lopo"].values()):
        h3 = "POSITIVE"
    elif hp["n"] >= 20 and hp["ci95"][0] is not None and hp["ci95"][0] >= -0.05 and hp["ci95"][1] <= 0.05:
        h3 = "CONSTRAINING_NULL"
    else:
        h3 = "UNINTERPRETABLE"

    def s1_demo(name):
        b = out["matrix"][name]
        p = b["pooled"]
        return p["harmful"] > p["helpful"] and p["mcnemar_p"] < 0.05 and all(v["harmful"] > v["helpful"] for v in b["lopo"].values())
    s1 = s1_demo("s1_false_verdict_vs_neutral") or s1_demo("s1_false_rationale_vs_neutral")

    if t1 and t2 and t3 and h1_holds and h2_holds and h3 in ("POSITIVE", "CONSTRAINING_NULL"):
        status = "READY_FOR_MANUSCRIPT"
    elif t1 and t2 and t3 and not h1_pooled and not h2_holds and (h3 == "POSITIVE" or s1):
        status = "PIVOT"
    elif t1 and t2 and t3 and not h1_pooled and not h2_holds and h3 != "POSITIVE" and not s1:
        status = "STOP"
    else:
        status = "REVISE_2B"
    return {"status": status,
            "T1_integrity": {"holds": t1, "failing_cells": t1_fail, "fingerprint_mismatches": len(integ["fingerprint_mismatches"]),
                             "unplanned": len(integ["unplanned_records"])},
            "T2_usable_papers": {"holds": t2, "usable": usable, "detail": paper_detail},
            "T3_no_leakage": {"holds": t3, "blind_generic_on_target_rate": round(gx / gn, 4) if gn else None,
                              "targeted_E0_minus_E1_term_rate": round(pooled("E0") - pooled("E1"), 4)},
            "H1": {"holds": h1_holds, "pooled_significant": h1_pooled, "papers_with_direction": papers_dir,
                   "lopo_all_significant": lopo_ok, "lofo_all_direction": lofo_ok},
            "H2": {"holds": h2_holds, "models_meeting": h2_models},
            "H3": h3, "S1_secondary_demonstrated": s1}

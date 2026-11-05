#!/usr/bin/env python3
"""D1 + D2: reconcile every denominator that appears in the manuscript and Extended Data."""
from __future__ import annotations
import json, sys, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
for p in ("exp3heldout", "exp2b", "exp2br", "exp2bbroad"):
    sys.path.insert(0, str(ROOT / p))
import design_heldout as D, evaluate as EV, scoring as S  # noqa: E402

RUN = ROOT / "runs/exp3heldout_20260918_014959"
O = json.loads((RUN / "analysis.json").read_text())
PROF = json.loads((ROOT / "nature_extension/phase0_methods/profile_exp3/profile.json").read_text())
plan = D.Plan(); cases = {c["case_id"]: c for c in plan.cases}
ev, _ = EV.load(RUN / "evidence_trials.jsonl")
bl, _ = EV.load(RUN / "blind_trials.jsonl")
res = {}

print("=" * 78)
print("D1 — why the Blind column and Recall@5 differ")
print("=" * 78)
d1 = {}
for m in D.PRIMARY:
    blind_ok = [c for c in cases if EV.ok(bl.get(f"blind::{m}::{c}::E0"))]
    tgt_ok = [c for c in cases if EV.ok(ev.get(f"evidence::{m}::{c}::E0"))]
    paired = sorted(set(blind_ok) & set(tgt_ok))
    def det(c):
        r = bl[f"blind::{m}::{c}::E0"]
        _, valid = plan.paper_text(cases[c], "E0")
        lab, _f = S.label_defective(r["result"]["parsed"]["findings"], cases[c], plan.ledger, valid)
        return lab == "TRUE_DETECTION"
    all_blind_x = sum(det(c) for c in blind_ok)
    paired_x = sum(det(c) for c in paired)
    r5 = PROF["by_model"][m]["discovery"]["recall_at"]["5"]
    r1 = PROF["by_model"][m]["discovery"]["recall_at"]["1"]
    h1 = O["h1"]["by_model"][m]
    d1[m] = {
        "manuscript_blind_column": {"x": h1["blind_rate"]["x"], "n": h1["blind_rate"]["n"],
                                    "pct": round(100 * h1["blind_rate"]["x"] / h1["blind_rate"]["n"], 2),
                                    "denominator_is": "cases where BOTH the blind and the localized "
                                                      "generation were technically valid (the paired set)"},
        "recall_at_1": {"x": r1["x"], "n": r1["n"], "pct": round(100 * r1["x"] / r1["n"], 2)},
        "recall_at_5": {"x": r5["x"], "n": r5["n"], "pct": round(100 * r5["x"] / r5["n"], 2),
                        "denominator_is": "every technically valid blind generation, regardless of "
                                          "whether that case's localized generation succeeded"},
        "localized_column": {"x": h1["targeted_rate"]["x"], "n": h1["targeted_rate"]["n"],
                             "pct": round(100 * h1["targeted_rate"]["x"] / h1["targeted_rate"]["n"], 2)},
        "recomputed_all_valid_blind": {"x": all_blind_x, "n": len(blind_ok)},
        "recomputed_paired_blind": {"x": paired_x, "n": len(paired)},
        "n_blind_valid": len(blind_ok), "n_localized_valid": len(tgt_ok), "n_paired": len(paired),
    }
    print(f"\n{m}")
    print(f"  Blind column (paired denominator)  {h1['blind_rate']['x']}/{h1['blind_rate']['n']}"
          f" = {100*h1['blind_rate']['x']/h1['blind_rate']['n']:.1f}%")
    print(f"  Recall@1  (all valid blind)        {r1['x']}/{r1['n']} = {100*r1['x']/r1['n']:.1f}%")
    print(f"  Recall@5  (all valid blind)        {r5['x']}/{r5['n']} = {100*r5['x']/r5['n']:.1f}%")
    print(f"  Localized column                   {h1['targeted_rate']['x']}/{h1['targeted_rate']['n']}"
          f" = {100*h1['targeted_rate']['x']/h1['targeted_rate']['n']:.1f}%")
    print(f"  recomputed: all-valid blind {all_blind_x}/{len(blind_ok)}, paired blind {paired_x}/{len(paired)}")
    agree = (all_blind_x == r5["x"] and len(blind_ok) == r5["n"])
    print(f"  -> Recall@5 == strict blind over all valid generations? {'YES' if agree else 'NO'}")
res["D1_blind_vs_recall"] = d1

print("\n" + "=" * 78)
print("D2 — denominator flow")
print("=" * 78)
flow = []
n_cases = len(cases)
flow.append(("relations in the frozen corpus", n_cases, "every admitted relation"))
for state, label in (("E0", "E0 defective"), ("E1", "E1 valid"), ("E2", "E2 alternate")):
    ok_n = sum(1 for m in D.PRIMARY for c in cases if EV.ok(ev.get(f"evidence::{m}::{c}::{state}")))
    flow.append((f"targeted {label}: technically valid generations", ok_n,
                 f"5 systems x {n_cases} relations = {5*n_cases} attempted"))
blind_ok = sum(1 for m in D.PRIMARY for c in cases if EV.ok(bl.get(f"blind::{m}::{c}::E0")))
flow.append(("blind E0: technically valid generations", blind_ok, f"5 x {n_cases} attempted"))
paired = sum(1 for m in D.PRIMARY for c in cases
             if EV.ok(bl.get(f"blind::{m}::{c}::E0")) and EV.ok(ev.get(f"evidence::{m}::{c}::E0")))
flow.append(("paired blind AND localized both valid (H1 denominator)", paired, "the 909"))
traj = sum(1 for m in D.PRIMARY for c in cases
           if all(EV.ok(ev.get(f"evidence::{m}::{c}::{s}")) for s in ("E0", "E1", "E2")))
flow.append(("all three localized states valid (trajectory denominator)", traj, "the 909 trajectories"))
print(f"\n{'stage':62}{'n':>7}")
for a, b, c in flow:
    print(f"  {a:60}{b:>7}   {c}")
res["D2_flow"] = [{"stage": a, "n": b, "note": c} for a, b, c in flow]

# agentic + model-specific localized denominators
P3 = json.loads((ROOT / "runs/natureext_phase3_latest/phase3_analysis.json").read_text())
am = P3["by_model"]["qwen38_27"]
res["D2_agentic"] = {"n_paired_cases": am["n_paired_cases"],
                     "note": "cases where BOTH the agentic and the frozen direct blind generation "
                             "were technically valid, for qwen38_27 only"}
print(f"\n  agentic paired cases (qwen38_27 only): {am['n_paired_cases']}")
res["D2_model_specific_localized"] = {
    m: {"localized_valid": d1[m]["n_localized_valid"], "blind_valid": d1[m]["n_blind_valid"],
        "paired": d1[m]["n_paired"]} for m in D.PRIMARY}
print("\n  per-system valid counts (why 181/179/183 appear):")
for m in D.PRIMARY:
    v = res["D2_model_specific_localized"][m]
    print(f"    {m:14} localized {v['localized_valid']:4}  blind {v['blind_valid']:4}  paired {v['paired']:4}")

json.dump(res, (OUT / "data/DENOMINATOR_AUDIT.json").open("w"), indent=1)
print("\nwrote data/DENOMINATOR_AUDIT.json")

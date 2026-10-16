#!/usr/bin/env python3
"""Phase 4 analysis: does the H3 rationale benefit survive length matching?

    python analyze_phase4.py --run-dir runs/natureext_phase4_<ts> --exp3-dir runs/exp3heldout_20260918_014959

Combines the NEW control arms with the FROZEN Experiment 3 arms (which are read-only and never re-run) and runs
the five pre-registered contrasts plus the 2x2 factorial.
"""
from __future__ import annotations
import argparse, json, sys
from collections import defaultdict
from decimal import Decimal, getcontext
from math import comb
from pathlib import Path

getcontext().prec = 60
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "exp3heldout")); sys.path.insert(0, str(ROOT / "exp2b"))
import design_heldout as D, evaluate as EV  # noqa: E402

NEW = ("cv_irrelevant", "fv_irrelevant", "filler")
OLD = ("neutral", "correct_verdict", "correct_rationale", "false_verdict", "false_rationale")


def ep(b, c):
    n = b + c
    if n == 0:
        return Decimal(1)
    k = min(b, c)
    return min(2 * sum(Decimal(comb(n, i)) for i in range(k + 1)) / (Decimal(2) ** n), Decimal(1))


def load(p):
    out = {}
    if p.exists():
        for l in p.read_text().splitlines():
            if l.strip():
                r = json.loads(l); out[r["key"]] = r
    return out


def ok(r):
    return r is not None and r["result"]["status"] == "OK"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True); ap.add_argument("--exp3-dir", required=True)
    a = ap.parse_args()
    rd = ROOT / a.run_dir if not Path(a.run_dir).is_absolute() else Path(a.run_dir)
    e3 = ROOT / a.exp3_dir if not Path(a.exp3_dir).is_absolute() else Path(a.exp3_dir)
    new, old = load(rd / "h3control_trials.jsonl"), load(e3 / "matrix_trials.jsonl")
    plan = D.Plan(); subset = plan.matrix_subset()
    models = sorted({r["model"] for r in new.values()})

    # correctness[model][arm][(case,state)] = bool
    corr = defaultdict(lambda: defaultdict(dict))
    for r in new.values():
        if ok(r):
            corr[r["model"]][r["arm"]][(r["case_id"], r["state"])] = \
                r["result"]["parsed"]["verdict"] == r["truth"]
    for r in old.values():
        if ok(r) and r.get("arm") in OLD:
            corr[r["model"]][r["arm"]][(r["case_id"], r["state"])] = \
                r["result"]["parsed"]["verdict"] == r["truth"]

    CONTRASTS = [
        ("1_relevant_vs_irrelevant_rationale", "correct_rationale", "cv_irrelevant",
         "Does relation-specific evidence content matter beyond a length-matched irrelevant rationale?"),
        ("2_label_only_vs_irrelevant_rationale", "correct_verdict", "cv_irrelevant",
         "Does adding length-matched irrelevant text to a verdict change anything?"),
        ("3_relevant_rationale_vs_filler", "correct_rationale", "filler",
         "Relevant rationale against pure length-matched context, with no verdict."),
        ("4_correct_vs_false_under_irrelevant", "cv_irrelevant", "fv_irrelevant",
         "Verdict-label effect with rationale relevance held constant (both irrelevant)."),
        ("5_original_h3_replication", "correct_rationale", "correct_verdict",
         "The original H3 contrast, recomputed on the same subset."),
        ("6_filler_vs_neutral", "filler", "neutral",
         "Pure token/context effect with no verdict and no relation content."),
    ]
    out = {"run_dir": str(rd), "models": models, "new_arms": list(NEW), "results": {}}
    for name, A, B, q in CONTRASTS:
        per_model, pooled = {}, []
        for m in models:
            keys = set(corr[m].get(A, {})) & set(corr[m].get(B, {}))
            pairs = [(corr[m][A][k], corr[m][B][k]) for k in sorted(keys)]
            if not pairs:
                continue
            t = EV.paired_table(pairs)
            t["exact_p"] = f"{ep(t['first_only'], t['second_only']):.4E}"
            t["a_arm"], t["b_arm"] = A, B
            per_model[m] = t
            pooled += pairs
        if pooled:
            tp = EV.paired_table(pooled)
            tp["exact_p"] = f"{ep(tp['first_only'], tp['second_only']):.4E}"
            out["results"][name] = {"question": q, "a_arm": A, "b_arm": B,
                                    "pooled": tp, "by_model": per_model}
    # accuracy per arm
    acc = {}
    for m in models:
        acc[m] = {arm: {"x": sum(corr[m].get(arm, {}).values()), "n": len(corr[m].get(arm, {}))}
                  for arm in OLD + NEW}
    out["arm_accuracy"] = acc
    pooled_acc = {}
    for arm in OLD + NEW:
        x = sum(acc[m][arm]["x"] for m in models); n = sum(acc[m][arm]["n"] for m in models)
        pooled_acc[arm] = {"x": x, "n": n, "rate": round(x / n, 4) if n else None}
    out["arm_accuracy_pooled"] = pooled_acc
    (rd / "phase4_analysis.json").write_text(json.dumps(out, indent=1, default=str) + "\n")

    print("=== pooled arm accuracy ===")
    for arm, v in pooled_acc.items():
        if v["n"]:
            print(f"  {arm:20s} {v['x']:4d}/{v['n']:4d} = {100*v['rate']:5.1f}%")
    print("\n=== pre-registered contrasts (pooled) ===")
    for name, r in out["results"].items():
        t = r["pooled"]
        print(f"  {name:38s} n={t['n']:4d} helped={t['first_only']:3d} harmed={t['second_only']:3d} "
              f"diff={100*t['diff']:+6.1f}pp ci=[{100*t['ci95'][0]:+.1f},{100*t['ci95'][1]:+.1f}] "
              f"p={t['exact_p']}")


if __name__ == "__main__":
    main()

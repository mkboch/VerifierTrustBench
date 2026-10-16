#!/usr/bin/env python3
"""Phase 3 analysis: AGENTIC_BLIND vs the frozen DIRECT_BLIND, paired per case.

    python analyze_phase3.py --run-dir runs/natureext_phase3_<ts> --exp3-dir runs/exp3heldout_20260918_014959
"""
from __future__ import annotations
import argparse, json, sys
from collections import Counter
from decimal import Decimal, getcontext
from math import comb
from pathlib import Path

getcontext().prec = 60
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "nature_extension/verifier_profile"))
sys.path.insert(0, str(ROOT / "exp3heldout")); sys.path.insert(0, str(ROOT / "exp2b"))
import profile_core as P, design_heldout as D, evaluate as EV, scoring as S  # noqa: E402

KS = (1, 2, 3, 5)


def ep(b, c):
    n = b + c
    if n == 0: return Decimal(1)
    k = min(b, c)
    return min(2 * sum(Decimal(comb(n, i)) for i in range(k + 1)) / (Decimal(2) ** n), Decimal(1))


def load(p):
    out = {}
    if p.exists():
        for l in p.read_text().splitlines():
            if l.strip():
                r = json.loads(l); out[r["key"]] = r
    return out


def ok(r): return r is not None and r["result"]["status"] == "OK"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True); ap.add_argument("--exp3-dir", required=True)
    a = ap.parse_args()
    rd = ROOT / a.run_dir if not Path(a.run_dir).is_absolute() else Path(a.run_dir)
    e3 = ROOT / a.exp3_dir if not Path(a.exp3_dir).is_absolute() else Path(a.exp3_dir)
    ag, bl = load(rd / "agentic_trials.jsonl"), load(e3 / "blind_trials.jsonl")
    plan = D.Plan(); ledger = plan.ledger
    cases = {c["case_id"]: c for c in plan.cases}
    models = sorted({r["model"] for r in ag.values()})
    out = {"models": models, "ks": list(KS), "by_model": {}}

    for m in models:
        pairs, acur, dcur = [], [], []
        tool_calls, lat, fp_a, fp_d = [], [], [], []
        for cid, c in cases.items():
            A = ag.get(f"agentic::{m}::{cid}::E0"); Dr = bl.get(f"blind::{m}::{cid}::E0")
            if not (ok(A) and ok(Dr)):
                continue
            _, valid = plan.paper_text(c, "E0")
            la, _ = S.label_defective(A["result"]["parsed"]["findings"], c, ledger, valid)
            ld, _ = S.label_defective(Dr["result"]["parsed"]["findings"], c, ledger, valid)
            pairs.append((la == "TRUE_DETECTION", ld == "TRUE_DETECTION"))
            ca = P.discovery_curve(A["result"]["parsed"]["findings"], c, ledger, valid, KS)
            cd = P.discovery_curve(Dr["result"]["parsed"]["findings"], c, ledger, valid, KS)
            acur.append(ca); dcur.append(cd)
            fp_a.append(ca["n_findings"] - ca["n_correct_findings"])
            fp_d.append(cd["n_findings"] - cd["n_correct_findings"])
            tool_calls.append(A.get("tool_calls_used", 0)); lat.append(A.get("latency_s", 0))
        if not pairs:
            continue
        t = EV.paired_table(pairs)
        t["exact_p"] = f"{ep(t['first_only'], t['second_only']):.4E}"
        n = len(acur)
        def curve(cur):
            return {"recall_at": {k: EV.rate(sum(x[f"recall_at_{k}"] for x in cur), n) for k in KS},
                    "precision_at": {k: round(sum(x[f"precision_at_{k}"] for x in cur) / n, 4) for k in KS},
                    "mean_findings": round(sum(x["n_findings"] for x in cur) / n, 2),
                    "rank_distribution": dict(Counter(x["rank_first_correct"] for x in cur
                                                      if x["rank_first_correct"]))}
        out["by_model"][m] = {
            "n_paired_cases": len(pairs),
            "agentic_discovery": EV.rate(sum(p[0] for p in pairs), len(pairs)),
            "direct_discovery": EV.rate(sum(p[1] for p in pairs), len(pairs)),
            "paired_agentic_vs_direct": t,
            "agentic_curve": curve(acur), "direct_curve": curve(dcur),
            "false_positive_findings_per_case": {"agentic": round(sum(fp_a) / n, 2),
                                                 "direct": round(sum(fp_d) / n, 2)},
            "tool_calls": {"mean": round(sum(tool_calls) / n, 2),
                           "distribution": dict(Counter(tool_calls))},
            "latency_s": {"mean": round(sum(lat) / n, 1)},
        }
    (rd / "phase3_analysis.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
    for m, r in out["by_model"].items():
        t = r["paired_agentic_vs_direct"]
        print(f"{m}: n={r['n_paired_cases']} agentic={100*r['agentic_discovery']['rate']:.1f}% "
              f"direct={100*r['direct_discovery']['rate']:.1f}% "
              f"diff={100*t['diff']:+.1f}pp ci=[{100*t['ci95'][0]:+.1f},{100*t['ci95'][1]:+.1f}] "
              f"p={t['exact_p']} tools={r['tool_calls']['mean']}")
        print(f"   recall@1 agentic={100*r['agentic_curve']['recall_at'][1]['rate']:.1f}% "
              f"direct={100*r['direct_curve']['recall_at'][1]['rate']:.1f}%   "
              f"recall@5 agentic={100*r['agentic_curve']['recall_at'][5]['rate']:.1f}% "
              f"direct={100*r['direct_curve']['recall_at'][5]['rate']:.1f}%")


if __name__ == "__main__":
    main()

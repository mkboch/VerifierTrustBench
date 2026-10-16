#!/usr/bin/env python3
"""Phase 1 analysis: statistical-family effect at enriched precision.

    python analyze_phase1.py --run-dir runs/natureext_phase1_<ts> --exp3-dir runs/exp3heldout_20260918_014959

Reports the enriched statistical H1 estimate SEPARATELY (Phase 1 cases only) and POOLED with the frozen
Experiment 3 statistical cases. Significance is not the success criterion; the deliverable is a tighter interval.
"""
from __future__ import annotations
import argparse, json, sys
from decimal import Decimal, getcontext
from math import comb
from pathlib import Path

getcontext().prec = 60
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "exp3heldout")); sys.path.insert(0, str(ROOT / "exp2b"))
import design_heldout as D, evaluate as EV, scoring as S, normalize as N  # noqa: E402

LED1 = json.loads((HERE / "ledger.json").read_text())


def ep(b, c):
    n = b + c
    if n == 0: return Decimal(1)
    k = min(b, c)
    return min(2 * sum(Decimal(comb(n, i)) for i in range(k + 1)) / (Decimal(2) ** n), Decimal(1))


def load(p):
    out = {}
    if Path(p).exists():
        for l in Path(p).read_text().splitlines():
            if l.strip():
                r = json.loads(l); out[r["key"]] = r
    return out


def ok(r): return r is not None and r["result"]["status"] == "OK"


def tbl(pairs):
    t = EV.paired_table(pairs)
    t["exact_p"] = f"{ep(t['first_only'], t['second_only']):.4E}"
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True); ap.add_argument("--exp3-dir", required=True)
    a = ap.parse_args()
    rd = ROOT / a.run_dir if not Path(a.run_dir).is_absolute() else Path(a.run_dir)
    e3 = ROOT / a.exp3_dir if not Path(a.exp3_dir).is_absolute() else Path(a.exp3_dir)
    ev1, bl1 = load(rd / "evidence_trials.jsonl"), load(rd / "blind_trials.jsonl")
    ev3, bl3 = load(e3 / "evidence_trials.jsonl"), load(e3 / "blind_trials.jsonl")
    plan = D.Plan()
    e3_stat = [c for c in plan.cases if c["family"] == "statistical"]
    models = sorted({r["model"] for r in ev1.values()})

    out = {"models": models, "phase1_cases": len(LED1["cases"]), "exp3_statistical_cases": len(e3_stat)}

    def collect(cases, ev, bl, ledger, textfn):
        pairs, h2 = [], {"E0": [0, 0], "E1": [0, 0], "E2": [0, 0], "traj": [0, 0]}
        for c in cases:
            for m in models:
                v = {}
                for st in ("E0", "E1", "E2"):
                    r = ev.get(f"evidence::{m}::{c['case_id']}::{st}")
                    if ok(r):
                        v[st] = r["result"]["parsed"]["verdict"]
                        h2[st][1] += 1
                        h2[st][0] += int(v[st] == c["truth"][st])
                if len(v) == 3:
                    h2["traj"][1] += 1
                    h2["traj"][0] += int(all(v[s] == c["truth"][s] for s in ("E0", "E1", "E2")))
                tr = ev.get(f"evidence::{m}::{c['case_id']}::E0")
                br = bl.get(f"blind::{m}::{c['case_id']}::E0")
                if ok(tr) and ok(br):
                    _, valid = textfn(c, "E0")
                    lab, _ = S.label_defective(br["result"]["parsed"]["findings"], c, ledger, valid)
                    pairs.append((tr["result"]["parsed"]["verdict"] == c["truth"]["E0"],
                                  lab == "TRUE_DETECTION"))
        return pairs, h2

    def p1_text(c, st):
        return N.number((ROOT / c["paths"][st]).read_text())

    p1_pairs, p1_h2 = collect(LED1["cases"], ev1, bl1, LED1, p1_text)
    e3_pairs, e3_h2 = collect(e3_stat, ev3, bl3, plan.ledger, plan.paper_text)

    out["phase1_only"] = {"h1": tbl(p1_pairs) if p1_pairs else None,
                          "h2": {k: {"x": v[0], "n": v[1]} for k, v in p1_h2.items()}}
    out["exp3_only"] = {"h1": tbl(e3_pairs) if e3_pairs else None,
                        "h2": {k: {"x": v[0], "n": v[1]} for k, v in e3_h2.items()}}
    out["pooled"] = {"h1": tbl(p1_pairs + e3_pairs) if (p1_pairs + e3_pairs) else None}
    (rd / "phase1_analysis.json").write_text(json.dumps(out, indent=1, default=str) + "\n")

    def show(tag, t):
        if not t:
            print(f"  {tag:14s} (no data)"); return
        print(f"  {tag:14s} n={t['n']:4d}  targeted-only={t['first_only']:3d} blind-only={t['second_only']:3d}  "
              f"diff={100*t['diff']:+6.1f}pp  ci=[{100*t['ci95'][0]:+.1f},{100*t['ci95'][1]:+.1f}]  "
              f"p={t['exact_p']}  half-width={100*(t['ci95'][1]-t['ci95'][0])/2:.1f}pp")
    print("=== statistical-family H1 ===")
    show("Exp3 only", out["exp3_only"]["h1"])
    show("Phase 1 only", out["phase1_only"]["h1"])
    show("POOLED", out["pooled"]["h1"])


if __name__ == "__main__":
    main()

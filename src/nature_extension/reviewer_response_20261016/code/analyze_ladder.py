#!/usr/bin/env python3
"""B4 analysis: the same-format localization ladder.

All three arms are scored by the SAME frozen scorer on the SAME outcome: strict discovery
(TRUE_DETECTION) of the tested relation within the returned finding list. The blind arm is the
frozen Experiment 3 blind record, unchanged.

Monotonicity is NOT assumed. If category targeting does not help, that is what gets reported.
"""
from __future__ import annotations
import csv, json, sys, collections
from pathlib import Path
from decimal import Decimal, getcontext
from math import comb
import numpy as np

getcontext().prec = 60
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
for p in ("exp3heldout", "exp2b", "exp2br"):
    sys.path.insert(0, str(ROOT / p))
import design_heldout as D, evaluate as EV, scoring as S  # noqa: E402

SEED, NBOOT = 20261016, 10000
MAN = json.loads((OUT / "ladder/LADDER_DESIGN_MANIFEST.json").read_text())
plan = D.Plan(); cases = {c["case_id"]: c for c in plan.cases}
subset = MAN["case_ids"]; MODELS = MAN["models"]

bl, _ = EV.load(ROOT / "runs/exp3heldout_20260918_014959/blind_trials.jsonl")
lad = {}
f = OUT / "ladder/ladder_trials.jsonl"
if f.exists():
    for line in f.open():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r["result"]["status"] == "OK":
            lad[r["key"]] = r

ARMS = ["BLIND_DISCOVERY", "CATEGORY_TARGETED_DISCOVERY", "RELATION_TARGETED_DISCOVERY"]
rows, tech = [], collections.Counter()
for m in MODELS:
    for cid in subset:
        c = cases[cid]
        _, valid = plan.paper_text(c, "E0")
        for arm in ARMS:
            if arm == "BLIND_DISCOVERY":
                r = bl.get(f"blind::{m}::{cid}::E0")
                okr = EV.ok(r)
            else:
                r = lad.get(f"ladder::{m}::{cid}::{arm}")
                okr = r is not None
            if not okr:
                tech[(m, arm)] += 1
                continue
            fnd = r["result"]["parsed"]["findings"]
            lab, feats = S.label_defective(fnd, c, plan.ledger, valid)
            hit_rank = None
            for i, ft in enumerate(feats):
                if ft["L"] and ft["V"] and ft["R"]:
                    hit_rank = i + 1
                    break
            fp = sum(1 for ft in feats if not ft["L"] and not ft["V"])
            rows.append({"system": m, "case_id": cid, "paper": c["paper"], "family": c["family"],
                         "domain": c["domain"], "arm": arm,
                         "detected": int(lab == "TRUE_DETECTION"), "label": lab,
                         "n_findings": len(fnd), "hit_rank": hit_rank or "",
                         "false_positive_findings": fp})

with (OUT / "data/LADDER_ITEMLEVEL.csv").open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(f"scored observations: {len(rows)}   technically invalid/absent: {sum(tech.values())}")

def recall_at(sub, k):
    hit = sum(1 for r in sub if r["hit_rank"] != "" and int(r["hit_rank"]) <= k)
    return hit, len(sub)

print(f"\n{'arm':32}{'Recall@1':>14}{'Recall@5':>14}{'FP findings/case':>19}{'findings/case':>15}")
summary = {}
for arm in ARMS:
    sub = [r for r in rows if r["arm"] == arm]
    if not sub:
        print(f"{arm:32}  no data yet"); continue
    h1, n = recall_at(sub, 1); h5, _ = recall_at(sub, 5)
    fp = sum(r["false_positive_findings"] for r in sub) / n
    nf = sum(r["n_findings"] for r in sub) / n
    prec = sum(r["detected"] for r in sub) / max(1, sum(r["n_findings"] for r in sub))
    summary[arm] = {"n": n, "recall_at_1": {"x": h1, "n": n, "pct": round(100*h1/n, 1)},
                    "recall_at_5": {"x": h5, "n": n, "pct": round(100*h5/n, 1)},
                    "false_positive_findings_per_case": round(fp, 2),
                    "findings_per_case": round(nf, 2),
                    "finding_precision": round(prec, 4)}
    print(f"{arm:32}{h1:>6}/{n:<4}{100*h1/n:5.1f}%{h5:>6}/{n:<4}{100*h5/n:5.1f}%{fp:>19.2f}{nf:>15.2f}")


def exact_p(b, c):
    n = b + c
    if n == 0:
        return Decimal(1)
    k = min(b, c)
    return min(2 * sum(Decimal(comb(n, i)) for i in range(k + 1)) / (Decimal(2) ** n), Decimal(1))


idx = {(r["system"], r["case_id"], r["arm"]): r for r in rows}
def paired(a, b):
    units = [(s, c) for (s, c, ar) in idx if ar == a and (s, c, b) in idx]
    if not units:
        return None
    recs = [{"a": idx[(s, c, a)]["detected"], "b": idx[(s, c, b)]["detected"],
             "paper": idx[(s, c, a)]["paper"]} for s, c in units]
    both = sum(1 for r in recs if r["a"] and r["b"])
    ao = sum(1 for r in recs if r["a"] and not r["b"])
    bo = sum(1 for r in recs if r["b"] and not r["a"])
    n = len(recs)
    bypaper = collections.defaultdict(list)
    for r in recs:
        bypaper[r["paper"]].append(r)
    papers = sorted(bypaper)
    rng = np.random.default_rng(SEED); vals = []
    for _ in range(NBOOT):
        pick = rng.integers(0, len(papers), len(papers))
        pool = [x for i in pick for x in bypaper[papers[i]]]
        x = sum(1 for r in pool if r["a"] and not r["b"])
        y = sum(1 for r in pool if r["b"] and not r["a"])
        vals.append(100 * (x - y) / len(pool))
    v = np.asarray(vals)
    return {"arm_a": a, "arm_b": b, "n": n, "both": both, "a_only": ao, "b_only": bo,
            "neither": n - both - ao - bo,
            "rate_a": round(100 * (both + ao) / n, 1), "rate_b": round(100 * (both + bo) / n, 1),
            "diff_pp": round(100 * (ao - bo) / n, 2), "exact_p": f"{exact_p(ao, bo):.4E}",
            "cluster_lo": round(float(np.percentile(v, 2.5)), 2),
            "cluster_hi": round(float(np.percentile(v, 97.5)), 2),
            "n_manuscripts": len(papers)}


print(f"\n{'contrast':58}{'n':>5}{'diff':>9}{'exact p':>12}{'cluster 95% CI':>20}")
contrasts = {}
for a, b, lab in (("CATEGORY_TARGETED_DISCOVERY", "BLIND_DISCOVERY", "category minus blind"),
                  ("RELATION_TARGETED_DISCOVERY", "CATEGORY_TARGETED_DISCOVERY", "relation minus category"),
                  ("RELATION_TARGETED_DISCOVERY", "BLIND_DISCOVERY", "relation minus blind")):
    r = paired(a, b)
    if r is None:
        print(f"{lab:58}  no data"); continue
    contrasts[lab] = r
    print(f"{lab:58}{r['n']:>5}{r['diff_pp']:>+9.2f}{r['exact_p']:>12}"
          f"   [{r['cluster_lo']:+.2f}, {r['cluster_hi']:+.2f}]")

# per system
per_sys = {}
for m in MODELS:
    per_sys[m] = {}
    for arm in ARMS:
        sub = [r for r in rows if r["arm"] == arm and r["system"] == m]
        if sub:
            x = sum(r["detected"] for r in sub)
            per_sys[m][arm] = {"x": x, "n": len(sub), "pct": round(100 * x / len(sub), 1)}
print(f"\n{'system':16}" + "".join(f"{a.split('_')[0][:9]:>14}" for a in ARMS))
for m in MODELS:
    line = f"{m:16}"
    for arm in ARMS:
        d = per_sys[m].get(arm)
        line += f"{(str(d['x'])+'/'+str(d['n'])) if d else '-':>14}"
    print(line)

json.dump({"seed": SEED, "n_bootstrap": NBOOT, "label": MAN["label"], "status": MAN["status"],
           "arm_summary": summary, "contrasts": contrasts, "by_system": per_sys,
           "technically_invalid_or_absent": {f"{k[0]}|{k[1]}": v for k, v in tech.items()},
           "n_scored": len(rows)},
          (OUT / "data/LADDER_RESULTS.json").open("w"), indent=1)
print("\nwrote data/LADDER_RESULTS.json and data/LADDER_ITEMLEVEL.csv")

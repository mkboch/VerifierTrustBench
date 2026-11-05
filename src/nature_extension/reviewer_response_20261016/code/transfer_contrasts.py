#!/usr/bin/env python3
"""D3, D4, H: exact identification of the information-transfer contrasts, and the paired
bare-correct-verdict versus bare-false-verdict test the manuscript never ran.

The five original arms live in the frozen Experiment 3 matrix store; the three length-matched
control arms live in the Phase 4 store. Both are keyed by model x case x state x arm, so the
paired cells can be rebuilt exactly.
"""
from __future__ import annotations
import csv, json, sys, collections
from pathlib import Path
from decimal import Decimal, getcontext
from math import comb
import numpy as np

getcontext().prec = 80
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
for p in ("exp3heldout", "exp2b", "exp2br"):
    sys.path.insert(0, str(ROOT / p))
import evaluate as EV  # noqa: E402

SEED, NBOOT = 20261016, 10000
mx, _ = EV.load(ROOT / "runs/exp3heldout_20260918_014959/matrix_trials.jsonl")
p4, _ = EV.load(ROOT / "runs/natureext_phase4_latest/h3control_trials.jsonl")

# index: (model, case, state, arm) -> correct?
obs = {}
meta = {}
for store in (mx, p4):
    for k, r in store.items():
        if r["result"]["status"] != "OK":
            continue
        arm = r.get("arm")
        if arm is None:
            continue
        key = (r["model"], r["case_id"], r["state"], arm)
        obs[key] = int(r["result"]["parsed"]["verdict"] == r["truth"])
        meta[(r["model"], r["case_id"], r["state"])] = r["paper"]

arms = sorted({k[3] for k in obs})
print("arms available:", arms)
counts = collections.Counter(k[3] for k in obs)
print("valid observations per arm:", dict(counts))


def exact_p(b, c):
    n = b + c
    if n == 0:
        return Decimal(1)
    k = min(b, c)
    return min(2 * sum(Decimal(comb(n, i)) for i in range(k + 1)) / (Decimal(2) ** n), Decimal(1))


def paired(a_arm, b_arm):
    units = [u for u in {(m, c, s) for (m, c, s, _a) in obs}
             if (u[0], u[1], u[2], a_arm) in obs and (u[0], u[1], u[2], b_arm) in obs]
    both = aonly = bonly = neither = 0
    rows = []
    for u in units:
        a, b = obs[(u[0], u[1], u[2], a_arm)], obs[(u[0], u[1], u[2], b_arm)]
        both += a and b; aonly += a and not b; bonly += b and not a; neither += (not a) and (not b)
        rows.append({"unit": u, "paper": meta[u], "a": a, "b": b})
    n = len(units)
    if n == 0:
        return None
    d = 100 * (aonly - bonly) / n
    # manuscript-cluster bootstrap
    bypaper = collections.defaultdict(list)
    for r in rows:
        bypaper[r["paper"]].append(r)
    papers = sorted(bypaper)
    rng = np.random.default_rng(SEED)
    vals = []
    for _ in range(NBOOT):
        pick = rng.integers(0, len(papers), len(papers))
        pool = [x for i in pick for x in bypaper[papers[i]]]
        ao = sum(1 for x in pool if x["a"] and not x["b"])
        bo = sum(1 for x in pool if x["b"] and not x["a"])
        vals.append(100 * (ao - bo) / len(pool))
    v = np.asarray(vals)
    return {"a_arm": a_arm, "b_arm": b_arm, "n": n, "both": both, "a_only": aonly,
            "b_only": bonly, "neither": neither,
            "rate_a": round(100 * (both + aonly) / n, 2), "rate_b": round(100 * (both + bonly) / n, 2),
            "paired_diff_pp": round(d, 2), "exact_p": f"{exact_p(aonly, bonly):.4E}",
            "cluster_boot_lo": round(float(np.percentile(v, 2.5)), 2),
            "cluster_boot_hi": round(float(np.percentile(v, 97.5)), 2),
            "n_manuscripts": len(papers)}


CONTRASTS = [
    ("D4_bare_correct_vs_false_verdict", "correct_verdict", "false_verdict",
     "Bare correct verdict versus bare false verdict, no rationale on either side. "
     "This is the contrast the manuscript's abstract language about verdict correctness implies "
     "but never tested."),
    ("D3_relevance_held_irrelevant", "cv_irrelevant", "fv_irrelevant",
     "Correct verdict WITH a length-matched IRRELEVANT rationale versus false verdict WITH a "
     "length-matched IRRELEVANT rationale. Both sides carry irrelevant text; only the verdict "
     "label differs. This is the -1.6 pp contrast."),
    ("relevant_vs_irrelevant_rationale", "correct_rationale", "cv_irrelevant", "The H3 relevance contrast."),
    ("correct_vs_false_rationale", "correct_rationale", "false_rationale",
     "Both rationales are relation-specific; only the advocated conclusion differs."),
    ("false_rationale_vs_false_verdict", "false_rationale", "false_verdict",
     "Adding relation-specific content to a false verdict."),
    ("false_rationale_vs_neutral", "false_rationale", "neutral",
     "A rationale advocating the WRONG conclusion, against no upstream information at all."),
    ("filler_vs_neutral", "filler", "neutral", "Pure token volume."),
]

out = {}
print(f"\n{'contrast':40}{'n':>6}{'rateA':>8}{'rateB':>8}{'diff':>8}{'exact p':>12}{'cluster CI':>20}")
print("-" * 102)
for name, a, b, desc in CONTRASTS:
    r = paired(a, b)
    if r is None:
        print(f"{name:40}  NOT AVAILABLE")
        continue
    r["description"] = desc
    out[name] = r
    print(f"{name:40}{r['n']:>6}{r['rate_a']:>8.1f}{r['rate_b']:>8.1f}{r['paired_diff_pp']:>+8.2f}"
          f"{r['exact_p']:>12}   [{r['cluster_boot_lo']:+.2f}, {r['cluster_boot_hi']:+.2f}]")

json.dump(out, (OUT / "data/TRANSFER_CONTRASTS.json").open("w"), indent=1)
with (OUT / "data/TRANSFER_CONTRASTS.csv").open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["contrast"] + [k for k in next(iter(out.values())) if k != "description"])
    w.writeheader()
    for k, v in out.items():
        w.writerow({"contrast": k, **{x: y for x, y in v.items() if x != "description"}})
print("\nwrote data/TRANSFER_CONTRASTS.json and .csv")

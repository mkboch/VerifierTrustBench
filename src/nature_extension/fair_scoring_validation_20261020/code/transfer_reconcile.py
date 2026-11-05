#!/usr/bin/env python3
"""Section 7: transfer-table reconciliation from frozen trial keys.

Recomputes every H3 arm and every reported paired contrast from the frozen matrix store and
the Phase 4 length-matched control store, and shows, for each contrast, BOTH

  the marginal accuracy of each arm over all its valid observations, and
  the paired accuracy of each arm over the subset where both arms are valid,

so that an apparent discrepancy between a paired difference and the subtraction of two
marginal rates can be attributed to its real cause: the two arms have different valid
subsets, and the paired contrast is computed only where both are valid.

A paired contrast that is correct is NOT adjusted to match the marginal subtraction.
"""
from __future__ import annotations
import collections, json, sys
from decimal import Decimal, getcontext
from math import comb
from pathlib import Path
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

obs, meta, attempted = {}, {}, collections.Counter()
for store in (mx, p4):
    for k, r in store.items():
        arm = r.get("arm")
        if arm is None:
            continue
        attempted[arm] += 1
        if r["result"]["status"] != "OK":
            continue
        key = (r["model"], r["case_id"], r["state"], arm)
        obs[key] = int(r["result"]["parsed"]["verdict"] == r["truth"])
        meta[(r["model"], r["case_id"], r["state"])] = r["paper"]

ARMS = sorted({k[3] for k in obs})


def exact_p(b, c):
    n = b + c
    if n == 0:
        return Decimal(1)
    k = min(b, c)
    return min(2 * sum(Decimal(comb(n, i)) for i in range(k + 1)) / (Decimal(2) ** n), Decimal(1))


def marginal(arm):
    cells = [(u, v) for (m, c, s, a), v in obs.items() if a == arm for u in [(m, c, s)]]
    n = len(cells)
    k = sum(v for _u, v in cells)
    return {"arm": arm, "n_attempted": attempted[arm], "n_valid": n,
            "n_correct": k, "accuracy_pct": round(100 * k / n, 2) if n else None}


MARG = {a: marginal(a) for a in ARMS}


def paired(a_arm, b_arm):
    units = [u for u in {(m, c, s) for (m, c, s, _a) in obs}
             if (u + (a_arm,)) in obs and (u + (b_arm,)) in obs]
    rows = [{"unit": u, "paper": meta[u], "a": obs[u + (a_arm,)], "b": obs[u + (b_arm,)]}
            for u in units]
    n = len(rows)
    if n == 0:
        return None
    both = sum(1 for x in rows if x["a"] and x["b"])
    aonly = sum(1 for x in rows if x["a"] and not x["b"])
    bonly = sum(1 for x in rows if x["b"] and not x["a"])
    neither = n - both - aonly - bonly
    bypaper = collections.defaultdict(list)
    for r in rows:
        bypaper[r["paper"]].append(r)
    papers = sorted(bypaper)
    rng = np.random.default_rng(SEED)
    vals = []
    for _ in range(NBOOT):
        pool = [x for i in rng.integers(0, len(papers), len(papers)) for x in bypaper[papers[i]]]
        ao = sum(1 for x in pool if x["a"] and not x["b"])
        bo = sum(1 for x in pool if x["b"] and not x["a"])
        vals.append(100 * (ao - bo) / len(pool))
    v = np.asarray(vals)
    pa, pb = 100 * (both + aonly) / n, 100 * (both + bonly) / n
    ma, mb = MARG[a_arm]["accuracy_pct"], MARG[b_arm]["accuracy_pct"]
    return {
        "arm_a": a_arm, "arm_b": b_arm,
        "marginal_a_pct": ma, "marginal_a_n": MARG[a_arm]["n_valid"],
        "marginal_b_pct": mb, "marginal_b_n": MARG[b_arm]["n_valid"],
        "marginal_difference_pp": round(ma - mb, 2),
        "paired_n": n, "paired_n_manuscripts": len(papers),
        "paired_accuracy_a_pct": round(pa, 2), "paired_accuracy_b_pct": round(pb, 2),
        "paired_difference_pp": round(pa - pb, 2),
        "discordant_a_only": aonly, "discordant_b_only": bonly,
        "concordant_both": both, "concordant_neither": neither,
        "exact_mcnemar_p": f"{exact_p(aonly, bonly):.4E}",
        "cluster_boot_ci_pp": [round(float(np.percentile(v, 2.5)), 2),
                               round(float(np.percentile(v, 97.5)), 2)],
        "paired_minus_marginal_pp": round((pa - pb) - (ma - mb), 2),
        "dropped_from_a": MARG[a_arm]["n_valid"] - n,
        "dropped_from_b": MARG[b_arm]["n_valid"] - n,
    }


CONTRASTS = [
    ("relevant_rationale_vs_filler", "correct_rationale", "filler",
     "Relevant rationale versus length-matched filler. Isolates relation-specific content "
     "from token volume."),
    ("false_rationale_vs_bare_false_verdict", "false_rationale", "false_verdict",
     "Adding relation-specific reasoning to a false verdict, against the bare false verdict."),
    ("correct_verdict_only_vs_false_verdict_only", "correct_verdict", "false_verdict",
     "Bare correct verdict versus bare false verdict, no rationale on either side."),
    ("relevance_held_correct_vs_false_verdict", "cv_irrelevant", "fv_irrelevant",
     "Correct versus false verdict with a length-matched IRRELEVANT rationale on both sides, "
     "so relevance is held constant and only the advocated conclusion differs."),
    ("relevant_vs_irrelevant_rationale", "correct_rationale", "cv_irrelevant",
     "The H3 relevance contrast."),
    ("correct_vs_false_rationale", "correct_rationale", "false_rationale",
     "Both rationales relation-specific; only the advocated conclusion differs."),
    ("false_rationale_vs_neutral", "false_rationale", "neutral",
     "A rationale advocating the wrong conclusion, against no upstream information."),
    ("filler_vs_neutral", "filler", "neutral", "Pure token volume."),
    ("location_vs_neutral", "location", "neutral", "Location pointer only."),
]

res = {}
for name, a, b, desc in CONTRASTS:
    if a not in MARG or b not in MARG:
        res[name] = {"status": "NOT_AVAILABLE",
                     "missing_arm": [x for x in (a, b) if x not in MARG], "description": desc}
        continue
    r = paired(a, b)
    r["description"] = desc
    res[name] = r

payload = {"label": "TRANSFER_TABLE_RECONCILIATION",
           "source": "frozen trial keys only; no new inference",
           "stores": ["runs/exp3heldout_20260918_014959/matrix_trials.jsonl",
                      "runs/natureext_phase4_latest/h3control_trials.jsonl"],
           "arms": MARG, "contrasts": res,
           "bootstrap": {"draws": NBOOT, "seed": SEED, "unit": "manuscript"}}
(OUT / "data/TRANSFER_RECONCILIATION.json").write_text(json.dumps(payload, indent=1) + "\n")

print(f"{'arm':20}{'attempted':>10}{'valid':>8}{'correct':>9}{'acc%':>8}")
for a in ARMS:
    m = MARG[a]
    print(f"{a:20}{m['n_attempted']:>10}{m['n_valid']:>8}{m['n_correct']:>9}{m['accuracy_pct']:>8.2f}")
print()
hdr = f"{'contrast':44}{'pair n':>7}{'pA':>7}{'pB':>7}{'pdiff':>8}{'mdiff':>8}{'delta':>7}"
print(hdr); print("-" * len(hdr))
for name, r in res.items():
    if r.get("status") == "NOT_AVAILABLE":
        print(f"{name:44}  NOT AVAILABLE ({', '.join(r['missing_arm'])})")
        continue
    print(f"{name:44}{r['paired_n']:>7}{r['paired_accuracy_a_pct']:>7.1f}"
          f"{r['paired_accuracy_b_pct']:>7.1f}{r['paired_difference_pp']:>+8.2f}"
          f"{r['marginal_difference_pp']:>+8.2f}{r['paired_minus_marginal_pp']:>+7.2f}")
print("\nwrote data/TRANSFER_RECONCILIATION.json")

#!/usr/bin/env python3
"""C1-C3: manuscript-cluster-robust reanalysis of the primary blind-vs-localized contrast.

The 909 paired observations are 5 systems x ~182 relations nested in 21 manuscripts. Resampling
rows treats them as independent; resampling manuscripts does not. Both are reported.
"""
from __future__ import annotations
import csv, json, collections
from pathlib import Path
from decimal import Decimal, getcontext
from math import comb
import numpy as np

getcontext().prec = 80
OUT = Path(__file__).resolve().parents[1]
SEED = 20261016
NBOOT = 10000

rows = list(csv.DictReader((OUT / "data/PROFILE_5SYSTEM_184_ITEMLEVEL.csv").open()))
for r in rows:
    r["correct"] = int(r["correct"])

# pair blind_E0 against localized_E0 on the same system x relation
idx = collections.defaultdict(dict)
for r in rows:
    if r["axis"] in ("blind_E0", "localized_E0", "supported_E0"):
        idx[(r["system"], r["case_id"])][r["axis"]] = r

PAIRS = {}
for (sysname, cid), d in idx.items():
    if "blind_E0" in d and "localized_E0" in d:
        PAIRS[(sysname, cid)] = {
            "paper": d["blind_E0"]["paper"], "domain": d["blind_E0"]["domain"],
            "family": d["blind_E0"]["family"],
            "blind": d["blind_E0"]["correct"], "localized": d["localized_E0"]["correct"],
            "supported": d.get("supported_E0", {}).get("correct"),
        }
print(f"paired blind/localized observations: {len(PAIRS)}")


def exact_mcnemar(b, c):
    n = b + c
    if n == 0:
        return Decimal(1)
    k = min(b, c)
    return min(2 * sum(Decimal(comb(n, i)) for i in range(k + 1)) / (Decimal(2) ** n), Decimal(1))


def contrast(pairs, a="localized", b="blind"):
    both = sum(1 for p in pairs if p[a] and p[b])
    aonly = sum(1 for p in pairs if p[a] and not p[b])
    bonly = sum(1 for p in pairs if p[b] and not p[a])
    neither = len(pairs) - both - aonly - bonly
    n = len(pairs)
    return {"n": n, "both": both, "a_only": aonly, "b_only": bonly, "neither": neither,
            "rate_a": (both + aonly) / n, "rate_b": (both + bonly) / n,
            "diff_pp": 100 * (aonly - bonly) / n}


def cluster_bootstrap(pairs_by_paper, papers, stat, nboot=NBOOT, seed=SEED):
    rng = np.random.default_rng(seed)
    vals, eff = [], []
    for _ in range(nboot):
        pick = rng.integers(0, len(papers), len(papers))
        pool = []
        for i in pick:
            pool.extend(pairs_by_paper[papers[i]])
        vals.append(stat(pool))
        eff.append(len(set(pick)))
    v = np.asarray(vals, float)
    return {"mean": float(v.mean()), "lo": float(np.percentile(v, 2.5)),
            "hi": float(np.percentile(v, 97.5)), "sd": float(v.std(ddof=1)),
            "mean_distinct_manuscripts_per_draw": float(np.mean(eff))}


allp = list(PAIRS.values())
by_paper = collections.defaultdict(list)
for p in allp:
    by_paper[p["paper"]].append(p)
papers = sorted(by_paper)

results = {"seed": SEED, "n_bootstrap": NBOOT, "n_manuscripts": len(papers),
           "relations_per_manuscript": {k: len(v) // 5 for k, v in sorted(by_paper.items())}}

# ---- primary contrast
c = contrast(allp)
p_exact = exact_mcnemar(c["a_only"], c["b_only"])
boot = cluster_bootstrap(by_paper, papers, lambda pool: contrast(pool)["diff_pp"])
# row bootstrap for comparison
rng = np.random.default_rng(SEED)
rowb = []
for _ in range(NBOOT):
    pick = rng.integers(0, len(allp), len(allp))
    rowb.append(contrast([allp[i] for i in pick])["diff_pp"])
rowb = np.asarray(rowb)

results["primary_localized_vs_blind"] = {
    **c, "exact_mcnemar_p": f"{p_exact:.4E}",
    "manuscript_cluster_bootstrap": boot,
    "row_bootstrap_for_comparison": {"lo": float(np.percentile(rowb, 2.5)),
                                     "hi": float(np.percentile(rowb, 97.5)),
                                     "sd": float(rowb.std(ddof=1))},
}
print(f"\nPRIMARY localized vs blind: {c['diff_pp']:.1f} pp "
      f"(localized {100*c['rate_a']:.1f}%, blind {100*c['rate_b']:.1f}%, n={c['n']})")
print(f"  discordant: localized-only {c['a_only']}, blind-only {c['b_only']}")
print(f"  exact McNemar p = {p_exact:.4E}")
print(f"  manuscript-cluster bootstrap 95% CI [{boot['lo']:.1f}, {boot['hi']:.1f}] pp  (sd {boot['sd']:.2f})")
print(f"  row bootstrap 95% CI             [{np.percentile(rowb,2.5):.1f}, {np.percentile(rowb,97.5):.1f}] pp"
      f"  (sd {rowb.std(ddof=1):.2f})")
print(f"  cluster SD / row SD = {boot['sd']/rowb.std(ddof=1):.2f}x")

# ---- supported-localized vs blind
sp = [p for p in allp if p["supported"] is not None]
by_paper_s = collections.defaultdict(list)
for p in sp:
    by_paper_s[p["paper"]].append(p)
cs = contrast(sp, a="supported", b="blind")
ps = exact_mcnemar(cs["a_only"], cs["b_only"])
boots = cluster_bootstrap(by_paper_s, sorted(by_paper_s), lambda pool: contrast(pool, "supported", "blind")["diff_pp"])
results["supported_localized_vs_blind"] = {**cs, "exact_mcnemar_p": f"{ps:.4E}",
                                           "manuscript_cluster_bootstrap": boots}
print(f"\nSUPPORTED-localized vs blind: {cs['diff_pp']:.1f} pp "
      f"(supported {100*cs['rate_a']:.1f}%, blind {100*cs['rate_b']:.1f}%, n={cs['n']})")
print(f"  exact McNemar p = {ps:.4E}")
print(f"  manuscript-cluster bootstrap 95% CI [{boots['lo']:.1f}, {boots['hi']:.1f}] pp")

# ---- per-system
results["by_system"] = {}
print("\nper system (manuscript-cluster bootstrap):")
for m in sorted({k[0] for k in PAIRS}):
    sub = [v for k, v in PAIRS.items() if k[0] == m]
    bp = collections.defaultdict(list)
    for p in sub:
        bp[p["paper"]].append(p)
    cm = contrast(sub)
    bm = cluster_bootstrap(bp, sorted(bp), lambda pool: contrast(pool)["diff_pp"], nboot=2000)
    results["by_system"][m] = {**cm, "manuscript_cluster_bootstrap": bm,
                               "exact_mcnemar_p": f"{exact_mcnemar(cm['a_only'], cm['b_only']):.3E}"}
    print(f"  {m:14} {cm['diff_pp']:+6.1f} pp  CI [{bm['lo']:+6.1f}, {bm['hi']:+6.1f}]  n={cm['n']}")

json.dump(results, (OUT / "data/CLUSTER_ROBUST_PRIMARY.json").open("w"), indent=1)
print("\nwrote data/CLUSTER_ROBUST_PRIMARY.json")

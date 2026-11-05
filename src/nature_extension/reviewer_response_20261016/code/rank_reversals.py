#!/usr/bin/env python3
"""A2: cross-axis rank reversals and axis associations across the 12 systems.

Bootstrap resamples RELATIONS clustered within manuscripts (the relation is the unit shared
across systems, so resampling relations preserves the system-by-system pairing).
"""
from __future__ import annotations
import csv, json, itertools, collections
from pathlib import Path
import numpy as np

import sys
OUT = Path(__file__).resolve().parents[1]
DATASET = sys.argv[1] if len(sys.argv) > 1 else "PROFILE_12SYSTEM_ITEMLEVEL.csv"
TAG = sys.argv[2] if len(sys.argv) > 2 else "12SYSTEM"
ROWS = list(csv.DictReader((OUT / "data" / DATASET).open()))
for r in ROWS:
    r["correct"] = int(r["correct"])

AXES = ["blind_E0", "localized_E0", "localized_E2", "supported_E0", "localized_E1"]
AXIS_LABEL = {"blind_E0": "blind discovery (E0)", "localized_E0": "relation-localized (E0)",
              "localized_E2": "relation-localized (E2)", "supported_E0": "supported-localized (E0)",
              "localized_E1": "valid-state clearance (E1)"}
SYSTEMS = sorted({r["system"] for r in ROWS}, key=lambda s: -sum(
    x["correct"] for x in ROWS if x["system"] == s and x["axis"] == "localized_E0"))
RELATIONS = sorted({r["case_id"] for r in ROWS})
PAPER = {r["case_id"]: r["paper"] for r in ROWS}
SEED = 20261016
NBOOT = 10000


def rates(rows):
    d = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        k = (r["system"], r["axis"])
        d[k][0] += r["correct"]; d[k][1] += 1
    return {k: (v[0] / v[1] if v[1] else np.nan, v[0], v[1]) for k, v in d.items()}


BASE = rates(ROWS)


def spearman(x, y):
    def rk(v):
        order = np.argsort(np.argsort(v))
        # average ties
        out = np.zeros(len(v))
        s = collections.defaultdict(list)
        for i, val in enumerate(v):
            s[val].append(i)
        for val, idx in s.items():
            out[idx] = np.mean([order[i] for i in idx])
        return out
    a, b = rk(np.asarray(x, float)), rk(np.asarray(y, float))
    if np.std(a) == 0 or np.std(b) == 0:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def kendall(x, y):
    n, conc, disc = len(x), 0, 0
    for i, j in itertools.combinations(range(n), 2):
        dx, dy = x[i] - x[j], y[i] - y[j]
        if dx == 0 or dy == 0:
            continue
        conc += (dx > 0) == (dy > 0)
        disc += (dx > 0) != (dy > 0)
    return (conc - disc) / (conc + disc) if conc + disc else np.nan


def axis_vec(res, axis):
    """Works for both the triple-valued BASE table and the rate-only bootstrap tables."""
    out = []
    for s in SYSTEMS:
        v = res.get((s, axis))
        out.append(np.nan if v is None else (v[0] if isinstance(v, tuple) else v))
    return out


# ---------------------------------------------------------------- bootstrap
rng = np.random.default_rng(SEED)
by_rel = collections.defaultdict(list)
for r in ROWS:
    by_rel[r["case_id"]].append(r)

boot_rates = []          # list of dict[(system,axis)] -> rate
for _ in range(NBOOT):
    pick = rng.choice(len(RELATIONS), len(RELATIONS), replace=True)
    rows = []
    for i in pick:
        rows.extend(by_rel[RELATIONS[i]])
    boot_rates.append({k: v[0] for k, v in rates(rows).items()})

print(f"bootstrap: {NBOOT} resamples over {len(RELATIONS)} relations "
      f"in {len(set(PAPER.values()))} manuscripts, seed {SEED}")

# ---------------------------------------------------------------- axis correlations
corr_rows = []
for a, b in itertools.combinations(AXES, 2):
    va, vb = axis_vec(BASE, a), axis_vec(BASE, b)
    sp, kt = spearman(va, vb), kendall(va, vb)
    bs = [spearman(axis_vec(br, a), axis_vec(br, b)) for br in boot_rates]
    bs = [x for x in bs if not np.isnan(x)]
    lo, hi = (np.percentile(bs, [2.5, 97.5]) if bs else (np.nan, np.nan))
    corr_rows.append({"axis_a": a, "axis_b": b, "n_systems": len(SYSTEMS),
                      "spearman": round(sp, 3), "kendall_tau_b": round(kt, 3),
                      "spearman_boot_lo": round(lo, 3), "spearman_boot_hi": round(hi, 3)})

with (OUT / f"data/PROFILE_AXIS_CORRELATIONS_{TAG}.csv").open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(corr_rows[0])); w.writeheader(); w.writerows(corr_rows)

# ---------------------------------------------------------------- rank reversals
rev_rows = []
for a, b in itertools.combinations(AXES, 2):
    for s1, s2 in itertools.combinations(SYSTEMS, 2):
        r1a, r1b = BASE.get((s1, a), (np.nan,))[0], BASE.get((s1, b), (np.nan,))[0]
        r2a, r2b = BASE.get((s2, a), (np.nan,))[0], BASE.get((s2, b), (np.nan,))[0]
        if any(np.isnan(x) for x in (r1a, r1b, r2a, r2b)):
            continue
        da, db = r1a - r2a, r1b - r2b
        reversed_ = (da > 0) != (db > 0) and da != 0 and db != 0
        # how often the reversal reappears under the relation bootstrap
        hits = 0
        for br in boot_rates:
            try:
                x1a, x1b = br[(s1, a)], br[(s1, b)]
                x2a, x2b = br[(s2, a)], br[(s2, b)]
            except KeyError:
                continue
            d1, d2 = x1a - x2a, x1b - x2b
            if d1 == 0 or d2 == 0:
                continue
            hits += (d1 > 0) != (d2 > 0)
        rev_rows.append({
            "axis_a": a, "axis_b": b, "system_1": s1, "system_2": s2,
            "s1_rate_a": round(r1a, 4), "s2_rate_a": round(r2a, 4), "diff_a_pp": round(100 * da, 1),
            "s1_rate_b": round(r1b, 4), "s2_rate_b": round(r2b, 4), "diff_b_pp": round(100 * db, 1),
            "reversed": int(reversed_), "bootstrap_reversal_frequency": round(hits / NBOOT, 4),
        })

with (OUT / f"data/PROFILE_RANK_REVERSALS_{TAG}.csv").open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rev_rows[0])); w.writeheader(); w.writerows(rev_rows)

# ---------------------------------------------------------------- summary
pairs_by_axes = collections.defaultdict(lambda: [0, 0])
for r in rev_rows:
    k = (r["axis_a"], r["axis_b"])
    pairs_by_axes[k][0] += r["reversed"]; pairs_by_axes[k][1] += 1

robust = [r for r in rev_rows if r["reversed"] and r["bootstrap_reversal_frequency"] >= 0.95]
moderate = [r for r in rev_rows if r["reversed"] and 0.80 <= r["bootstrap_reversal_frequency"] < 0.95]

print("\nreversal counts by axis pair (reversed / comparable system pairs):")
for (a, b), (k, n) in sorted(pairs_by_axes.items()):
    print(f"  {a:14} vs {b:16} {k:3}/{n:3}  ({100*k/n:5.1f}%)")

print(f"\nrobust reversals (bootstrap frequency >= 0.95): {len(robust)}")
for r in sorted(robust, key=lambda x: -x["bootstrap_reversal_frequency"])[:25]:
    print(f"  {r['system_1']:16} vs {r['system_2']:16} | {r['axis_a']:13} {r['diff_a_pp']:+6.1f} pp"
          f" | {r['axis_b']:14} {r['diff_b_pp']:+6.1f} pp | boot {r['bootstrap_reversal_frequency']:.3f}")
print(f"moderate reversals (0.80-0.95): {len(moderate)}")

# focal pair named by the reviewer
print("\nfocal pair qwen36_27 vs qwen38_27:")
for r in rev_rows:
    if {r["system_1"], r["system_2"]} == {"qwen36_27", "qwen38_27"}:
        tag = "REVERSED" if r["reversed"] else "same order"
        print(f"  {r['axis_a']:14} vs {r['axis_b']:16} {tag:10} "
              f"({r['diff_a_pp']:+6.1f} pp vs {r['diff_b_pp']:+6.1f} pp) boot {r['bootstrap_reversal_frequency']:.3f}")

json.dump({"seed": SEED, "n_bootstrap": NBOOT, "systems": SYSTEMS, "axes": AXES,
           "n_robust_reversals": len(robust), "n_moderate_reversals": len(moderate),
           "reversals_by_axis_pair": {f"{a}|{b}": {"reversed": k, "comparable": n}
                                      for (a, b), (k, n) in pairs_by_axes.items()}},
          (OUT / f"data/PROFILE_RANKING_SUMMARY_{TAG}.json").open("w"), indent=1)
print(f"\nwrote *_{TAG}.csv/json")

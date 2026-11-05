#!/usr/bin/env python3
"""B4 decomposition: how much of the blind-to-localized difference is information, and how much
is response format?

The ladder arms and the relation-localized verdict task are compared on EXACTLY the same
60 relations x 5 systems, so the only thing that differs between the last two rungs is the
response format: a ranked finding list versus a binary verdict, on identical information.
"""
from __future__ import annotations
import csv, json, collections
from pathlib import Path
from decimal import Decimal, getcontext
from math import comb
import numpy as np

getcontext().prec = 60
OUT = Path(__file__).resolve().parents[1]
SEED, NBOOT = 20261016, 10000

lad = list(csv.DictReader((OUT / "data/LADDER_ITEMLEVEL.csv").open()))
prof = list(csv.DictReader((OUT / "data/PROFILE_12SYSTEM_ITEMLEVEL.csv").open()))
PRIMARY = ["qwen38_27", "qwen36_27", "gemma4_12", "granite42_30", "qwen3_8"]

# localized verdict outcome on the same subset, primary systems only
loc = {(r["system"], r["case_id"]): int(r["correct"]) for r in prof
       if r["axis"] == "localized_E0" and r["system"] in PRIMARY}
paper = {r["case_id"]: r["paper"] for r in prof}
arm = collections.defaultdict(dict)
for r in lad:
    arm[r["arm"]][(r["system"], r["case_id"])] = int(r["detected"])

RUNGS = [
    ("blind discovery", "BLIND_DISCOVERY", "ranked finding list", "none"),
    ("category-targeted discovery", "CATEGORY_TARGETED_DISCOVERY", "ranked finding list", "defect category"),
    ("relation-targeted discovery", "RELATION_TARGETED_DISCOVERY", "ranked finding list", "the specific relation"),
    ("relation-localized verdict", "__LOCALIZED__", "binary verdict", "the specific relation"),
]


def exact_p(b, c):
    n = b + c
    if n == 0:
        return Decimal(1)
    k = min(b, c)
    return min(2 * sum(Decimal(comb(n, i)) for i in range(k + 1)) / (Decimal(2) ** n), Decimal(1))


def get(key):
    return loc if key == "__LOCALIZED__" else arm[key]


# common support: units present in all four
units = set(loc)
for _, k, _, _ in RUNGS:
    units &= set(get(k))
units = sorted(units)
print(f"common support across all four rungs: {len(units)} system x relation units "
      f"({len({u[1] for u in units})} relations, {len({u[0] for u in units})} systems)\n")

rates = {}
print(f"{'rung':34}{'format':22}{'information':22}{'strict discovery':>18}")
print("-" * 96)
for label, key, fmt, info in RUNGS:
    d = get(key)
    x = sum(d[u] for u in units)
    rates[key] = {"label": label, "format": fmt, "information": info, "x": x, "n": len(units),
                  "pct": round(100 * x / len(units), 1)}
    print(f"{label:34}{fmt:22}{info:22}{x:>8}/{len(units):<4} {100*x/len(units):5.1f}%")


def paired(ka, kb):
    A, B = get(ka), get(kb)
    recs = [{"a": A[u], "b": B[u], "paper": paper[u[1]]} for u in units]
    ao = sum(1 for r in recs if r["a"] and not r["b"])
    bo = sum(1 for r in recs if r["b"] and not r["a"])
    n = len(recs)
    byp = collections.defaultdict(list)
    for r in recs:
        byp[r["paper"]].append(r)
    ps = sorted(byp)
    rng = np.random.default_rng(SEED)
    vals = []
    for _ in range(NBOOT):
        pick = rng.integers(0, len(ps), len(ps))
        pool = [x for i in pick for x in byp[ps[i]]]
        vals.append(100 * (sum(1 for r in pool if r["a"] and not r["b"])
                           - sum(1 for r in pool if r["b"] and not r["a"])) / len(pool))
    v = np.asarray(vals)
    return {"n": n, "a_only": ao, "b_only": bo, "diff_pp": round(100 * (ao - bo) / n, 2),
            "exact_p": f"{exact_p(ao, bo):.4E}",
            "lo": round(float(np.percentile(v, 2.5)), 2), "hi": round(float(np.percentile(v, 97.5)), 2)}


STEPS = [
    ("information: blind -> category", "CATEGORY_TARGETED_DISCOVERY", "BLIND_DISCOVERY"),
    ("information: category -> relation", "RELATION_TARGETED_DISCOVERY", "CATEGORY_TARGETED_DISCOVERY"),
    ("information total: blind -> relation (format held)", "RELATION_TARGETED_DISCOVERY", "BLIND_DISCOVERY"),
    ("FORMAT: relation-targeted -> relation-localized (information held)", "__LOCALIZED__", "RELATION_TARGETED_DISCOVERY"),
    ("the manuscript's contrast: blind -> localized", "__LOCALIZED__", "BLIND_DISCOVERY"),
]
print(f"\n{'step':66}{'diff':>9}{'exact p':>12}{'cluster 95% CI':>20}")
print("-" * 107)
steps = {}
for lab, a, b in STEPS:
    r = paired(a, b)
    steps[lab] = r
    print(f"{lab:66}{r['diff_pp']:>+9.2f}{r['exact_p']:>12}   [{r['lo']:+.2f}, {r['hi']:+.2f}]")

total = steps["the manuscript's contrast: blind -> localized"]["diff_pp"]
info = steps["information total: blind -> relation (format held)"]["diff_pp"]
fmt = steps["FORMAT: relation-targeted -> relation-localized (information held)"]["diff_pp"]
print(f"\nDECOMPOSITION of the {total:.1f} pp blind-to-localized difference on these units:")
print(f"  attributable to INFORMATION (format held constant): {info:+.1f} pp "
      f"= {100*info/total:.0f}% of the total")
print(f"  attributable to RESPONSE FORMAT (information held constant): {fmt:+.1f} pp "
      f"= {100*fmt/total:.0f}% of the total")

json.dump({"seed": SEED, "n_bootstrap": NBOOT, "common_support_units": len(units),
           "n_relations": len({u[1] for u in units}), "n_systems": len({u[0] for u in units}),
           "rungs": rates, "steps": steps,
           "decomposition": {"total_pp": total, "information_pp": info, "format_pp": fmt,
                             "information_share": round(info / total, 3),
                             "format_share": round(fmt / total, 3)}},
          (OUT / "data/LADDER_DECOMPOSITION.json").open("w"), indent=1)
print("\nwrote data/LADDER_DECOMPOSITION.json")

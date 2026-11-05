#!/usr/bin/env python3
"""D5-D8: axis ranking table, the two distinct false-alarm quantities, the error-taxonomy
definitions behind Figure 4c, and complete domain rows."""
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

RUN = ROOT / "runs/exp3heldout_20260918_014959"
O = json.loads((RUN / "analysis.json").read_text())
PROF = json.loads((ROOT / "nature_extension/phase0_methods/profile_exp3/profile.json").read_text())
plan = D.Plan(); cases = {c["case_id"]: c for c in plan.cases}
bl, _ = EV.load(RUN / "blind_trials.jsonl")
res = {}
SEED, NBOOT = 20261016, 10000

# ---------------------------------------------------------------- D5 ranking by axis
print("=" * 78); print("D5 — ranking by axis (no undefined 'strongest system')"); print("=" * 78)
rows = list(csv.DictReader((OUT / "data/PROFILE_5SYSTEM_184_ITEMLEVEL.csv").open()))
agg = collections.defaultdict(lambda: [0, 0])
for r in rows:
    agg[(r["system"], r["axis"])][0] += int(r["correct"]); agg[(r["system"], r["axis"])][1] += 1
AX = ["blind_E0", "localized_E0", "localized_E1", "localized_E2", "supported_E0"]
LAB = {"blind_E0": "highest blind discovery", "localized_E0": "highest relation-localized accuracy",
       "localized_E1": "highest valid-state clearance", "localized_E2": "highest alternate-defect accuracy",
       "supported_E0": "highest evidence-supported localized accuracy"}
rank = {}
for a in AX:
    order = sorted(D.PRIMARY, key=lambda m: -(agg[(m, a)][0] / agg[(m, a)][1]))
    rank[a] = [{"system": m, "x": agg[(m, a)][0], "n": agg[(m, a)][1],
                "pct": round(100 * agg[(m, a)][0] / agg[(m, a)][1], 1)} for m in order]
    print(f"\n{a} ({LAB[a]}):")
    for i, e in enumerate(rank[a], 1):
        print(f"  {i}. {e['system']:14} {e['x']:4}/{e['n']:<4} {e['pct']:5.1f}%")
# add the bias-aware ranking
bam = {r["group"]: r for r in csv.DictReader((OUT / "data/LOCALIZED_BIAS_AWARE_METRICS.csv").open())
       if r["dataset"] == "primary_184"}
rank["balanced_accuracy"] = sorted(
    [{"system": m, "pct": round(100 * float(bam[m]["balanced_accuracy"]), 1),
      "dprime": float(bam[m]["dprime_loglinear"])} for m in D.PRIMARY],
    key=lambda e: -e["pct"])
print("\nbalanced accuracy (bias-aware):")
for i, e in enumerate(rank["balanced_accuracy"], 1):
    print(f"  {i}. {e['system']:14} {e['pct']:5.1f}%   d'={e['dprime']:5.2f}")
res["D5_axis_rankings"] = rank
res["D5_note"] = ("The system with the highest relation-localized accuracy (qwen38_27) is not the "
                  "system with the highest valid-state clearance (gemma4_12). 'Strongest system' is "
                  "undefined and should be replaced by an explicit metric name everywhere.")

# ---------------------------------------------------------------- D6 two false-alarm quantities
print("\n" + "=" * 78); print("D6 — two distinct false-alarm quantities"); print("=" * 78)
fa = {}
for m in D.PRIMARY:
    d = PROF["by_model"][m]["false_alarm_rate"]
    fa[m] = {"localized_valid_relation_false_alarm": {
        "x": d["x"], "n": d["n"], "pct": round(100 * d["x"] / d["n"], 1),
        "definition": d["definition"]}}
# blind false positives on CLEAN manuscripts
clean = collections.defaultdict(lambda: {"fp": 0, "touch": 0, "findings": 0, "audits": 0})
for m in D.PRIMARY:
    for pid in plan.papers:
        for k in (1, 2):
            r = bl.get(f"blind::{m}::{pid}::clean{k}")
            if not EV.ok(r):
                continue
            _, valid = plan.clean_text(pid)
            fnd = r["result"]["parsed"]["findings"]
            clean[m]["audits"] += 1
            clean[m]["findings"] += len(fnd)
            for c in [x for x in plan.cases if x["paper"] == pid]:
                lab, _f = S.label_clean(fnd, c, plan.ledger, valid)
                clean[m]["fp"] += lab == "FALSE_POSITIVE"
                clean[m]["touch"] += lab == "TARGET_TOUCHED"
for m in D.PRIMARY:
    c = clean[m]
    fa[m]["blind_clean_manuscript_audit"] = {
        "n_audits": c["audits"], "total_findings": c["findings"],
        "findings_per_audit": round(c["findings"] / c["audits"], 2) if c["audits"] else None,
        "relation_level_false_positive_flags": c["fp"], "target_touched_flags": c["touch"],
        "definition": "blind audits of UNMODIFIED manuscripts; a finding is a relation-level false "
                      "positive when the strict clean scorer labels it FALSE_POSITIVE for a tested "
                      "relation. This is a per-audit finding rate, NOT a per-relation verdict rate, "
                      "and is not comparable to the localized false-alarm rate."}
print(f"\n{'system':14}{'localized FA (1-E1 clearance)':>32}{'blind findings/audit':>24}{'blind FP flags':>16}")
for m in D.PRIMARY:
    a = fa[m]["localized_valid_relation_false_alarm"]; b = fa[m]["blind_clean_manuscript_audit"]
    print(f"{m:14}{a['x']:>12}/{a['n']:<4}{a['pct']:>8.1f}%{b['findings_per_audit']:>20}"
          f"{b['relation_level_false_positive_flags']:>16}")
res["D6_false_alarms"] = fa

# ---------------------------------------------------------------- D7 error taxonomy
print("\n" + "=" * 78); print("D7 — Figure 4c error-taxonomy definitions"); print("=" * 78)
tax = O.get("error_taxonomy", {})
defs = {
    "MISS_DEFECT": {"definition": "relation-localized trial on the E0 defective state where the "
                                  "verdict was not ISSUE_PRESENT",
                    "denominator": "technically valid localized E0 trials for that system"},
    "MISS_REVERSAL": {"definition": "relation-localized trial on the E2 independently re-perturbed "
                                    "state where the verdict was not ISSUE_PRESENT",
                      "denominator": "technically valid localized E2 trials for that system"},
    "WRONG_EVIDENCE_BINDING": {"definition": "trial whose cited lines do not support the tested "
                                             "relation (target_support UNSUPPORTED)",
                               "denominator": "all technically valid localized trials across E0/E1/E2"},
    "INVALID_PROVENANCE": {"definition": "trial citing at least one line id that does not exist in "
                                         "the manuscript sent, or a malformed id",
                           "denominator": "all technically valid localized trials across E0/E1/E2"},
}
for k, v in defs.items():
    print(f"  {k:26} {v['definition'][:70]}")
    print(f"  {'':26} denominator: {v['denominator']}")
res["D7_taxonomy_definitions"] = defs
res["D7_note"] = ("MISS_DEFECT and MISS_REVERSAL share neither denominator nor trial set with "
                  "WRONG_EVIDENCE_BINDING and INVALID_PROVENANCE. The four categories are NOT a "
                  "partition and must not be read as shares of one whole; Figure 4c must state the "
                  "denominator per column.")

# ---------------------------------------------------------------- D8 domain rows
print("\n" + "=" * 78); print("D8 — complete domain rows"); print("=" * 78)


def exact_p(b, c):
    n = b + c
    if n == 0:
        return Decimal(1)
    k = min(b, c)
    return min(2 * sum(Decimal(comb(n, i)) for i in range(k + 1)) / (Decimal(2) ** n), Decimal(1))


prs = collections.defaultdict(dict)
for r in rows:
    if r["axis"] in ("blind_E0", "localized_E0"):
        prs[(r["system"], r["case_id"])][r["axis"]] = r
dom_rows = []
for dom in sorted({r["domain"] for r in rows}):
    sub = [v for v in prs.values() if len(v) == 2 and v["blind_E0"]["domain"] == dom]
    n = len(sub)
    bo = sum(1 for v in sub if int(v["blind_E0"]["correct"]) and not int(v["localized_E0"]["correct"]))
    lo_ = sum(1 for v in sub if int(v["localized_E0"]["correct"]) and not int(v["blind_E0"]["correct"]))
    bx = sum(int(v["blind_E0"]["correct"]) for v in sub)
    lx = sum(int(v["localized_E0"]["correct"]) for v in sub)
    bypaper = collections.defaultdict(list)
    for v in sub:
        bypaper[v["blind_E0"]["paper"]].append(v)
    papers = sorted(bypaper)
    rng = np.random.default_rng(SEED); vals = []
    for _ in range(NBOOT):
        pick = rng.integers(0, len(papers), len(papers))
        pool = [x for i in pick for x in bypaper[papers[i]]]
        a = sum(1 for v in pool if int(v["localized_E0"]["correct"]) and not int(v["blind_E0"]["correct"]))
        b = sum(1 for v in pool if int(v["blind_E0"]["correct"]) and not int(v["localized_E0"]["correct"]))
        vals.append(100 * (a - b) / len(pool))
    v = np.asarray(vals)
    dom_rows.append({"domain": dom, "n_paired": n, "n_manuscripts": len(papers),
                     "blind_x": bx, "blind_pct": round(100 * bx / n, 1),
                     "localized_x": lx, "localized_pct": round(100 * lx / n, 1),
                     "diff_pp": round(100 * (lo_ - bo) / n, 1),
                     "localized_only": lo_, "blind_only": bo,
                     "exact_p": f"{exact_p(lo_, bo):.3E}",
                     "cluster_boot_lo": round(float(np.percentile(v, 2.5)), 1),
                     "cluster_boot_hi": round(float(np.percentile(v, 97.5)), 1)})
print(f"{'domain':26}{'n':>5}{'ms':>4}{'blind':>14}{'localized':>14}{'diff':>8}{'cluster CI':>18}")
for d in dom_rows:
    print(f"{d['domain']:26}{d['n_paired']:>5}{d['n_manuscripts']:>4}"
          f"{d['blind_x']:>7}/{d['n_paired']:<6}{d['localized_x']:>7}/{d['n_paired']:<6}"
          f"{d['diff_pp']:>+8.1f}  [{d['cluster_boot_lo']:+.1f},{d['cluster_boot_hi']:+.1f}]")
res["D8_domain_rows"] = dom_rows
with (OUT / "data/DOMAIN_ROWS.csv").open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(dom_rows[0])); w.writeheader(); w.writerows(dom_rows)

json.dump(res, (OUT / "data/DEFINITIONS_AUDIT.json").open("w"), indent=1)
print("\nwrote data/DEFINITIONS_AUDIT.json and data/DOMAIN_ROWS.csv")

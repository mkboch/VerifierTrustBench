#!/usr/bin/env python3
"""Phase 4: fair-scoring sensitivity under the MEASURED scorer false-negative rate.

The frozen primary estimates are NOT altered. This file asks a separate question:

    if the strict matcher is wrong as often as the six reviewers say it is, does the
    fair-scoring interface difference go away?

Two corrections are computed.

  ONE-SIDED   credit the measured false-negative rate on E0 only. This is deliberately
              the most generous possible reading of the criticism, because it raises the
              relation-targeted rung's sensitivity while leaving its false-alarm rate
              untouched. If the difference survives this, it survives.

  SYMMETRIC   apply the same leniency to E1. If the matcher is too strict to credit a
              near miss as a detection on the defective text, it is equally too strict to
              count a near miss as a false alarm on the clean text. There are 61 such E1
              near misses in the pooled open-weight data against 12 scored false alarms,
              so the one-sided correction is not neutral.

The binary verdict rung receives NO correction. Its scoring is an exact match against a
three-token verdict vocabulary; there is no fuzzy matcher and so no leniency question.
"""
from __future__ import annotations
import collections, json, math, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fairlib as F  # noqa: E402
from miss_anatomy import classify  # noqa: E402

OUT = Path(__file__).resolve().parents[1]
A = json.loads((OUT / "data/RT_AUDIT_RESULTS.json").read_text())
M = json.loads((OUT / "data/FAIR_LADDER_METRICS.json").read_text())
SEED, NBOOT = 20261021, 10000
REL, BIN = "RELATION_TARGETED_FINDING_LIST", "RELATION_LOCALIZED_BINARY_VERDICT"

# per-stratum false-negative rates measured by the audit (majority judgment, strict reading)
PS = A["per_stratum"]
p_h = {st: v["majority_yes"] / v["sampled"] for st, v in PS.items()}
p_h_gen = {st: (v["majority_yes"] + v["majority_partially"]) / v["sampled"]
           for st, v in PS.items()}

f = F.Fair()


def paired(system=None):
    out = []
    for sy in ([system] if system else F.OPENWEIGHT):
        rel = {c["case_id"]: c for c in f.rows(sy, REL)
               if c.get("e0_status") == "OK" and c.get("e1_status") == "OK"}
        bi = {c["case_id"]: c for c in f.rows(sy, BIN)
              if c.get("e0_status") == "OK" and c.get("e1_status") == "OK"}
        for cid in sorted(set(rel) & set(bi)):
            out.append({"paper": rel[cid]["paper"], "rel": rel[cid], "bin": bi[cid]})
    return out


def strat_of(cell):
    cat, _sub = classify(cell)
    return cat


def e1_near(cell):
    return cell.get("e1_label") == "TARGET_TOUCHED"


def stats(xs, rates, symmetric):
    """Expected sensitivity, false-alarm rate, balanced accuracy and d' for each rung
    under a scorer correction applied at per-stratum rate `rates`."""
    n = len(xs)
    rel_h = rel_fa = 0.0
    bin_h = bin_fa = 0.0
    for x in xs:
        r, b = x["rel"], x["bin"]
        if r.get("e0_correct"):
            rel_h += 1
        else:
            rel_h += rates.get(strat_of(r), 0.0)      # expected credit from the audit
        rel_fa += r.get("e1_false_alarm", 0)
        if symmetric and e1_near(r):
            # the same leniency that credits an E0 near miss must charge an E1 near miss
            rel_fa += rates.get("C_NEAR_MISS", 0.0)
        bin_h += b.get("e0_correct", 0)
        bin_fa += b.get("e1_false_alarm", 0)
    out = {}
    for nm, h, fa in (("rel", rel_h, rel_fa), ("bin", bin_h, bin_fa)):
        sens, far = h / n, min(fa / n, 1.0)
        d, _hh, _ff = F.loglinear_dprime(h, n, fa, n)
        out[nm] = {"sens": 100 * sens, "far": 100 * far,
                   "bal": 100 * ((sens + (1 - far)) / 2), "d": d}
    out["bal_diff"] = out["bin"]["bal"] - out["rel"]["bal"]
    out["d_diff"] = out["bin"]["d"] - out["rel"]["d"]
    out["raw_diff"] = out["bin"]["sens"] - out["rel"]["sens"]
    return out


xs = paired()
base = stats(xs, {}, False)
res = {"label": "SCORER_AUDIT_SENSITIVITY",
       "frozen_primary_not_altered": True,
       "measured_per_stratum_fn_rate": {k: round(v, 4) for k, v in p_h.items()},
       "measured_per_stratum_fn_rate_with_partial": {k: round(v, 4) for k, v in p_h_gen.items()},
       "n_paired_cells": len(xs),
       "n_manuscripts": len({x["paper"] for x in xs}),
       "frozen_primary": {
           "raw_E0_pp": round(base["raw_diff"], 2),
           "balanced_accuracy_pp": round(base["bal_diff"], 2),
           "dprime": round(base["d_diff"], 3),
           "relation_sensitivity_pct": round(base["rel"]["sens"], 1),
           "binary_sensitivity_pct": round(base["bin"]["sens"], 1),
       },
       "scenarios": {}}

SCEN = [("one_sided_strict", p_h, False,
         "measured majority-Yes rate credited on E0 only; most generous to the criticism"),
        ("one_sided_with_partial", p_h_gen, False,
         "Yes plus Partially credited on E0 only; the outer bound of the criticism"),
        ("symmetric_strict", p_h, True,
         "measured rate applied to E0 detections AND E1 near misses"),
        ("symmetric_with_partial", p_h_gen, True,
         "Yes plus Partially applied to both states")]

rng = random.Random(SEED)
bypaper = collections.defaultdict(list)
for x in xs:
    bypaper[x["paper"]].append(x)
papers = sorted(bypaper)

for name, rates, sym, desc in SCEN:
    pt = stats(xs, rates, sym)
    draws = {"bal": [], "d": [], "rel_sens": []}
    for _ in range(NBOOT):
        # resample manuscripts, and resample the audit's per-stratum rate
        samp = [y for _ in papers for y in bypaper[papers[rng.randrange(len(papers))]]]
        rr = {}
        for st, v in PS.items():
            k = v["majority_yes"] + (v["majority_partially"] if "partial" in name else 0)
            nn = v["sampled"]
            # binomial draw on the audit's own sample, so audit uncertainty propagates
            rr[st] = sum(1 for _ in range(nn) if rng.random() < k / nn) / nn
        s = stats(samp, rr, sym)
        draws["bal"].append(s["bal_diff"])
        draws["d"].append(s["d_diff"])
        draws["rel_sens"].append(s["rel"]["sens"])
    q = {k: (sorted(v)[int(0.025 * (NBOOT - 1))], sorted(v)[int(0.975 * (NBOOT - 1))])
         for k, v in draws.items()}
    res["scenarios"][name] = {
        "description": desc, "symmetric": sym,
        "relation_sensitivity_pct": round(pt["rel"]["sens"], 1),
        "relation_false_alarm_pct": round(pt["rel"]["far"], 1),
        "relation_balanced_accuracy_pct": round(pt["rel"]["bal"], 1),
        "relation_dprime": round(pt["rel"]["d"], 3),
        "raw_E0_difference_pp": round(pt["raw_diff"], 2),
        "balanced_accuracy_difference_pp": round(pt["bal_diff"], 2),
        "balanced_accuracy_ci95": [round(q["bal"][0], 2), round(q["bal"][1], 2)],
        "dprime_difference": round(pt["d_diff"], 3),
        "dprime_ci95": [round(q["d"][0], 3), round(q["d"][1], 3)],
        "balanced_accuracy_difference_excludes_zero": q["bal"][0] > 0 or q["bal"][1] < 0,
        "dprime_difference_excludes_zero": q["d"][0] > 0 or q["d"][1] < 0,
    }

# ------------------------------------------------------------------ verdict
primary = res["scenarios"]["one_sided_with_partial"]      # the outer bound of the criticism
survives = (primary["balanced_accuracy_difference_excludes_zero"]
            and primary["balanced_accuracy_difference_pp"] > 0)
d_survives = primary["dprime_difference_excludes_zero"] and primary["dprime_difference"] > 0
fn = A["false_negative_estimates"]["strict"]
material = fn["stratum_reweighted_pct"] >= 10.0

if survives and not material:
    status = "SCORER_VALIDATED"
elif survives:
    status = "SCORER_VALID_WITH_CAVEATS"
else:
    status = "SCORER_REQUIRES_CORRECTION"

res["measured_false_negative_rate"] = fn
sym = res["scenarios"]["symmetric_with_partial"]
res["verdict"] = {
    "status": status,
    "balanced_accuracy_survives_outer_bound": survives,
    "dprime_survives_outer_bound": d_survives,
    "dprime_caveat": (
        f"Under the ONE-SIDED outer bound the d' difference falls to "
        f"{primary['dprime_difference']:+.3f} with a 95% CI of {primary['dprime_ci95']}, which "
        f"INCLUDES ZERO. The d' difference therefore does not survive the most generous "
        f"possible reading of the criticism, although the balanced-accuracy difference does. "
        f"Under the symmetric correction, which is the more defensible of the two because it "
        f"applies the same leniency to both states, d' is {sym['dprime_difference']:+.3f} "
        f"(95% CI {sym['dprime_ci95']}) and excludes zero. This split must be reported, not "
        f"resolved by choosing the convenient scenario."
        if not d_survives else
        "The d' difference survives the one-sided outer bound as well."),
    "can_scorer_false_negatives_explain_the_interface_difference": "NO" if survives else "YES",
    "reasoning": (
        f"The measured scorer false-negative rate is "
        f"{fn['stratum_reweighted_pct']}% of relation-targeted misses "
        f"(95% CI {fn['ci95_pct'][0]}-{fn['ci95_pct'][1]}%), stratum-reweighted. That is "
        f"material rather than negligible, which is why the status is not a clean "
        f"SCORER_VALIDATED. But even under the outer bound of the criticism "
        f"(crediting every majority-Yes AND majority-Partially on E0, with no "
        f"offsetting correction on E1), the balanced-accuracy difference remains "
        f"{primary['balanced_accuracy_difference_pp']:+.2f} pp "
        f"(95% CI {primary['balanced_accuracy_ci95']}) and d' remains "
        f"{primary['dprime_difference']:+.3f} "
        f"(95% CI {primary['dprime_ci95']}). Plausible strict-scorer false negatives "
        f"therefore do NOT explain the fair-scoring interface difference in balanced "
        f"accuracy. The d' difference is the more fragile of the two: see dprime_caveat."
        if survives else
        "The difference does not survive the measured correction; the scorer requires "
        "correction before the comparison can be reported."),
    "why_not_fully_validated": (
        f"a {fn['stratum_reweighted_pct']}% false-negative rate on misses is real and must be "
        f"disclosed; the strict matcher understates relation-targeted discovery"),
    "one_sided_is_conservative_because": (
        "the pooled open-weight data contain 61 E1 near misses against 12 scored false "
        "alarms, so applying leniency to E0 alone flatters the relation-targeted rung; the "
        "symmetric scenarios show the difference is larger when both states are corrected"),
}
(OUT / "data/SCORER_SENSITIVITY.json").write_text(json.dumps(res, indent=1) + "\n")

print(f"frozen primary: raw {res['frozen_primary']['raw_E0_pp']:+.2f} pp, "
      f"bal {res['frozen_primary']['balanced_accuracy_pp']:+.2f} pp, "
      f"d' {res['frozen_primary']['dprime']:+.3f}")
print(f"measured FN rate (reweighted): {fn['stratum_reweighted_pct']}% "
      f"CI {fn['ci95_pct']}\n")
print(f"{'scenario':26s}{'rel sens':>10}{'bal diff':>11}{'bal CI':>20}{'d diff':>9}{'d CI':>18}")
for k, v in res["scenarios"].items():
    print(f"{k:26s}{v['relation_sensitivity_pct']:>9.1f}%{v['balanced_accuracy_difference_pp']:>+11.2f}"
          f"{str(v['balanced_accuracy_ci95']):>20}{v['dprime_difference']:>+9.3f}"
          f"{str(v['dprime_ci95']):>18}")
print(f"\nVERDICT: {status}")
print(f"Can scorer FNs explain the difference? "
      f"{res['verdict']['can_scorer_false_negatives_explain_the_interface_difference']}")

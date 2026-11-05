#!/usr/bin/env python3
"""Phases 2 and 3: relation-targeted scorer validity from the six-reviewer audit.

Every one of the 30 items is a case the frozen strict scorer recorded as a MISS. So on Q1
("does the finding identify the relation being tested?"):

    Yes        -> the scorer denied credit the reviewer would have given: a FALSE NEGATIVE
    Partially  -> contested; counted separately and never silently folded into either side
    No         -> the reviewer endorses the scorer
    Ambiguous  -> undetermined; never imputed

The sample is deliberately NON-PROPORTIONAL, so the raw 30-item rate is not a corpus rate.
Both are reported and the reweighted one is the estimate.
"""
from __future__ import annotations
import csv, itertools, json, math, random
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
SRC = OUT / "relation_targeted_scorer_human_review_responses"
V = json.loads((OUT / "audit/RT_RESPONSE_VERIFICATION.json").read_text())
if V["status"] != "PASS":
    raise SystemExit("REFUSING: response verification did not pass; nothing is analysed.")

frozen = json.loads((OUT / "audit/RELATION_TARGETED_AUDIT_SAMPLE.json").read_text())
META = {it["audit_id"]: it for it in frozen["items"]}
STRAT = frozen["stratification"]
LEVELS = ["Yes", "Partially", "No", "Ambiguous / Cannot determine"]
SEED, NBOOT = 20261021, 10000

rows = []
for p in sorted(SRC.glob("*.csv")):
    with p.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("item_id") or "").strip():
                rows.append({k: (v or "").strip() for k, v in r.items()})

by_item = defaultdict(list)
for r in rows:
    by_item[r["item_id"]].append(r)

# ------------------------------------------------------------------ judgment level
jc = Counter(r["q1_identifies_tested_relation"] for r in rows)
n_j = len(rows)
judgment = {
    "total_judgments": n_j,
    "counts": {k: jc.get(k, 0) for k in LEVELS},
    "pct": {k: round(100 * jc.get(k, 0) / n_j, 1) for k in LEVELS},
    "scorer_endorsed_pct": round(100 * jc.get("No", 0) / n_j, 1),
    "scorer_false_negative_pct": round(100 * jc.get("Yes", 0) / n_j, 1),
    "definition": "every item is a scorer MISS, so a 'Yes' is a scorer false negative",
}

# ------------------------------------------------------------------ item level
def majority(votes):
    c = Counter(votes)
    top = max(c.values())
    winners = sorted([k for k, v in c.items() if v == top], key=LEVELS.index)
    return winners[0], (len(winners) > 1), c


items = {}
for iid, rs in by_item.items():
    votes = [r["q1_identifies_tested_relation"] for r in rs]
    maj, tied, c = majority(votes)
    items[iid] = {
        "audit_id": iid,
        "votes": {k: c.get(k, 0) for k in LEVELS},
        "majority": maj,
        "majority_tied": tied,
        "unanimous": len(set(votes)) == 1,
        "any_yes_or_partial": any(v in ("Yes", "Partially") for v in votes),
        "n_yes": c.get("Yes", 0),
        "n_partial": c.get("Partially", 0),
        "stratum": META[iid]["category"],
        "subtype": META[iid]["subtype"],
        "sampling_weight": META[iid]["sampling_weight"],
        "scorer_outcome": "MISSED (no finding credited as identifying the tested relation)",
        "family": META[iid]["family"],
        "domain": META[iid]["domain"],
    }

n_i = len(items)
mc = Counter(v["majority"] for v in items.values())
item_level = {
    "n_items": n_i,
    "majority_counts": {k: mc.get(k, 0) for k in LEVELS},
    "majority_pct": {k: round(100 * mc.get(k, 0) / n_i, 1) for k in LEVELS},
    "unanimous_items": sum(1 for v in items.values() if v["unanimous"]),
    "items_with_any_yes_or_partial": sum(1 for v in items.values() if v["any_yes_or_partial"]),
    "items_majority_disagrees_with_scorer": sorted(
        k for k, v in items.items() if v["majority"] in ("Yes", "Partially")),
    "items_majority_yes": sorted(k for k, v in items.items() if v["majority"] == "Yes"),
    "tied_items": sorted(k for k, v in items.items() if v["majority_tied"]),
}

# ------------------------------------------------------------------ agreement
def fleiss(level_counts, n_raters):
    """Fleiss' kappa for a fixed number of raters. `level_counts` is one row per item
    giving the number of raters assigning each category; the category count is taken
    from the rows, so the same function serves the 4-level and the binary collapse."""
    N = len(level_counts)
    if N == 0:
        return None, None, None, None
    k = len(level_counts[0])
    pj = [sum(r[j] for r in level_counts) / (N * n_raters) for j in range(k)]
    Pi = [(sum(c * c for c in r) - n_raters) / (n_raters * (n_raters - 1)) for r in level_counts]
    Pbar = sum(Pi) / N
    Pe = sum(p * p for p in pj)
    return (Pbar - Pe) / (1 - Pe) if Pe != 1 else None, Pbar, Pe, pj


lc4 = [[items[i]["votes"][l] for l in LEVELS] for i in sorted(items)]
k4, Pbar4, Pe4, pj4 = fleiss(lc4, 6)

# binary collapse: did the reviewer credit the model at all (Yes/Partially) or not
BIN = {"Yes": 0, "Partially": 0, "No": 1, "Ambiguous / Cannot determine": 1}
lc2 = []
for i in sorted(items):
    b = [0, 0]
    for l in LEVELS:
        b[BIN[l]] += items[i]["votes"][l]
    lc2.append(b)
k2, Pbar2, Pe2, pj2 = fleiss(lc2, 6)

revs = sorted({r["reviewer"] for r in rows})
vote = {(r["reviewer"], r["item_id"]): r["q1_identifies_tested_relation"] for r in rows}
pairs = []
for a, b in itertools.combinations(revs, 2):
    agree4 = sum(1 for i in items if vote[(a, i)] == vote[(b, i)])
    agree2 = sum(1 for i in items if BIN[vote[(a, i)]] == BIN[vote[(b, i)]])
    pairs.append({"pair": f"{a} vs {b}", "raw_agreement_4level": round(agree4 / n_i, 4),
                  "raw_agreement_binary": round(agree2 / n_i, 4)})

per_rev = {}
for rv in revs:
    c = Counter(vote[(rv, i)] for i in items)
    per_rev[rv] = {"counts": {k: c.get(k, 0) for k in LEVELS},
                   "scorer_endorsed_pct": round(100 * c.get("No", 0) / n_i, 1),
                   "called_false_negative": c.get("Yes", 0)}

agreement = {
    "fleiss_kappa_4level": round(k4, 4) if k4 is not None else None,
    "fleiss_kappa_binary_credited_vs_not": round(k2, 4) if k2 is not None else None,
    "observed_agreement_4level": round(Pbar4, 4),
    "expected_agreement_4level": round(Pe4, 4),
    "observed_agreement_binary": round(Pbar2, 4),
    "expected_agreement_binary": round(Pe2, 4),
    "mean_pairwise_raw_agreement_4level": round(
        sum(p["raw_agreement_4level"] for p in pairs) / len(pairs), 4),
    "mean_pairwise_raw_agreement_binary": round(
        sum(p["raw_agreement_binary"] for p in pairs) / len(pairs), 4),
    "pairwise": pairs,
    "per_reviewer": per_rev,
    "prevalence_caveat": (
        "Kappa is depressed when one category dominates, because the chance-agreement term "
        "rises. Report the observed agreement alongside it, and read the binary kappa "
        "(credited vs not) rather than the 4-level one when the Partially/Ambiguous split "
        "is not the quantity of interest."),
}

# ------------------------------------------------------------------ reweighting
POP = {k: v["population"] for k, v in STRAT.items() if v["sampled"]}
TOTAL_POP = sum(v["population"] for v in STRAT.values())
by_strat = defaultdict(list)
for v in items.values():
    by_strat[v["stratum"]].append(v)


def fn_flag(v, mode):
    if mode == "strict":
        return 1.0 if v["majority"] == "Yes" else 0.0
    if mode == "with_partial_half":
        return 1.0 if v["majority"] == "Yes" else (0.5 if v["majority"] == "Partially" else 0.0)
    return 1.0 if v["majority"] in ("Yes", "Partially") else 0.0   # generous


def weighted(mode, sample=None):
    src = sample if sample is not None else by_strat
    num = 0.0
    for st, pop in POP.items():
        xs = src.get(st, [])
        if not xs:
            continue
        num += pop * (sum(fn_flag(x, mode) for x in xs) / len(xs))
    return 100 * num / TOTAL_POP


rng = random.Random(SEED)
est = {}
for mode in ("strict", "with_partial_half", "generous"):
    raw = 100 * sum(fn_flag(v, mode) for v in items.values()) / n_i
    pt = weighted(mode)
    draws = []
    for _ in range(NBOOT):
        samp = {st: [xs[rng.randrange(len(xs))] for _ in xs] for st, xs in by_strat.items()}
        draws.append(weighted(mode, samp))
    draws.sort()
    est[mode] = {
        "raw_unweighted_pct": round(raw, 1),
        "stratum_reweighted_pct": round(pt, 2),
        "ci95_pct": [round(draws[int(0.025 * (NBOOT - 1))], 2),
                     round(draws[int(0.975 * (NBOOT - 1))], 2)],
        "implied_corpus_misses_affected": round(TOTAL_POP * pt / 100, 1),
    }

# --- tie-break sensitivity. A tie is resolved toward the EARLIER level in LEVELS, which
# puts "Yes" ahead of "No" and so favours the criticism rather than the scorer. Only ties
# that sit on the Yes/No boundary can move the estimate, so they are re-run the other way.
tie_ids = [k for k, v in items.items() if v["majority_tied"]]
tie_sens = {}
for mode in ("strict", "with_partial_half", "generous"):
    flipped = {}
    for st, xs in by_strat.items():
        flipped[st] = []
        for x in xs:
            if x["audit_id"] in tie_ids and x["majority"] in ("Yes", "Partially"):
                y = dict(x)
                y["majority"] = "No"          # resolve the tie toward the scorer instead
                flipped[st].append(y)
            else:
                flipped[st].append(x)
    tie_sens[mode] = {
        "tie_toward_criticism_pct": round(weighted(mode), 2),
        "tie_toward_scorer_pct": round(weighted(mode, flipped), 2),
    }

per_stratum = {
    st: {"population": STRAT[st]["population"], "sampled": len(xs),
         "weight": STRAT[st]["weight"],
         "majority_yes": sum(1 for x in xs if x["majority"] == "Yes"),
         "majority_partially": sum(1 for x in xs if x["majority"] == "Partially"),
         "majority_no": sum(1 for x in xs if x["majority"] == "No"),
         "fn_rate_strict_pct": round(100 * sum(fn_flag(x, "strict") for x in xs) / len(xs), 1)}
    for st, xs in by_strat.items()}

payload = {
    "label": "RELATION_TARGETED_SCORER_AUDIT_RESULTS",
    "question": ("When the relation-targeted finding-list scorer records a miss, how often did "
                 "the model actually identify the tested relation in substantively correct "
                 "language that the strict matcher failed to credit?"),
    "n_reviewers": len(revs), "n_items": n_i,
    "llm_judge_used": False,
    "judgment_level": judgment,
    "item_level": item_level,
    "agreement": agreement,
    "per_stratum": per_stratum,
    "false_negative_estimates": est,
    "tied_items": tie_ids,
    "tie_break_rule": ("a tie is resolved toward the earlier level in "
                       "[Yes, Partially, No, Ambiguous], which favours the criticism rather "
                       "than the scorer; the sensitivity below resolves ties the other way"),
    "tie_break_sensitivity": tie_sens,
    "corpus_miss_population": TOTAL_POP,
    "reweighting_note": frozen["reweighting_note"],
    "bootstrap": {"draws": NBOOT, "seed": SEED, "design": "stratified, items resampled "
                                                          "within stratum"},
    "items": {k: items[k] for k in sorted(items)},
}
(OUT / "data/RT_AUDIT_RESULTS.json").write_text(json.dumps(payload, indent=1) + "\n")

print(f"judgments {n_j}: " + "  ".join(f"{k}={jc.get(k,0)}" for k in LEVELS))
print(f"scorer endorsed {judgment['scorer_endorsed_pct']}% of judgments; "
      f"called a false negative in {judgment['scorer_false_negative_pct']}%")
print(f"\nitem majorities: " + "  ".join(f"{k}={mc.get(k,0)}" for k in LEVELS))
print(f"unanimous {item_level['unanimous_items']}/{n_i}; "
      f"any Yes/Partially {item_level['items_with_any_yes_or_partial']}; "
      f"majority disagrees with scorer on {len(item_level['items_majority_disagrees_with_scorer'])}")
print(f"\nFleiss kappa 4-level {agreement['fleiss_kappa_4level']}, "
      f"binary {agreement['fleiss_kappa_binary_credited_vs_not']}; "
      f"mean pairwise raw {agreement['mean_pairwise_raw_agreement_4level']} / "
      f"{agreement['mean_pairwise_raw_agreement_binary']}")
print("\nper stratum:")
for st, v in per_stratum.items():
    print(f"  {st:16s} pop={v['population']:3d} n={v['sampled']:2d} w={v['weight']:7.4f} "
          f"Yes={v['majority_yes']} Part={v['majority_partially']} No={v['majority_no']}")
print(f"\ntied items: {tie_ids}")
for m, v in tie_sens.items():
    print(f"  tie-break {m:18s} toward criticism {v['tie_toward_criticism_pct']:5.2f}%  "
          f"toward scorer {v['tie_toward_scorer_pct']:5.2f}%")
print("\nfalse-negative estimates:")
for m, v in est.items():
    print(f"  {m:18s} raw={v['raw_unweighted_pct']:5.1f}%  reweighted="
          f"{v['stratum_reweighted_pct']:5.2f}% CI {v['ci95_pct']}  "
          f"~{v['implied_corpus_misses_affected']} of {TOTAL_POP} misses")

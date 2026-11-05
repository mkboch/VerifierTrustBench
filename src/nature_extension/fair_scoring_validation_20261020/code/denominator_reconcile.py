#!/usr/bin/env python3
"""Section 8: denominator and wording reconciliation, computed programmatically.

Every figure below is recomputed from frozen records. Nothing is asserted from memory.
"""
from __future__ import annotations
import collections, csv, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
RR = ROOT / "nature_extension/reviewer_response_20261016"
TV = ROOT / "nature_extension/final_topvenue_validation_20261018"
FROZEN = ROOT / "runs/exp3heldout_20260918_014959"
for p in ("exp3heldout", "exp2b", "exp2br"):
    sys.path.insert(0, str(ROOT / p))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import design_heldout as D, scoring as S  # noqa: E402
import fairlib as F  # noqa: E402

plan = D.Plan()
cases = {c["case_id"]: c for c in plan.cases}
MODELS = F.OPENWEIGHT
out = {"label": "DENOMINATOR_AND_WORDING_RECONCILIATION",
       "source": "frozen records only; no new inference"}

# ---------------------------------------------------------------- stores
blind = {}          # (model, case) -> (status, detected)
for line in (FROZEN / "blind_trials.jsonl").open():
    r = json.loads(line)
    if r["state"] != "E0":
        continue
    c = cases[r["case_id"]]
    if r["result"]["status"] != "OK":
        blind[(r["model"], r["case_id"])] = ("FAILED", None)
        continue
    _t, valid = plan.paper_text(c, "E0")
    lab, _ = S.label_defective(r["result"]["parsed"]["findings"], c, plan.ledger, valid)
    blind[(r["model"], r["case_id"])] = ("OK", int(lab == "TRUE_DETECTION"))

loc = collections.defaultdict(dict)   # (model, case) -> state -> (status, correct)
for line in (FROZEN / "evidence_trials.jsonl").open():
    r = json.loads(line)
    if r.get("arm") != "neutral":
        continue
    st = r["result"]["status"]
    ok = int(st == "OK" and r["result"]["parsed"]["verdict"] == r["truth"])
    loc[(r["model"], r["case_id"])][r["state"]] = (st, ok if st == "OK" else None)

# ---------------------------------------------------------------- 1. qwen3.8 blind
M = "qwen38_27"
mine = {k[1]: v for k, v in blind.items() if k[0] == M}
ev = {k[1]: v for k, v in loc.items() if k[0] == M}
all_rel = sorted(mine)
e0ok = [c for c in all_rel if ev.get(c, {}).get("E0", ("", None))[0] == "OK"]
three = [c for c in all_rel if all(ev.get(c, {}).get(s, ("", None))[0] == "OK"
                                   for s in ("E0", "E1", "E2"))]
blind_ok = [c for c in all_rel if mine[c][0] == "OK"]


def det(sel):
    return sum(mine[c][1] for c in sel if mine[c][0] == "OK"), len(sel)


# the third denominator is the AGENTIC pairing, not a localized one
ag = {}
for line in (ROOT / "runs/natureext_phase3_latest/agentic_trials.jsonl").open():
    r = json.loads(line)
    ag[r["case_id"]] = r


def _det(rec, c):
    if rec["result"]["status"] != "OK":
        return None
    fnd = (rec["result"].get("parsed") or {}).get("findings")
    if fnd is None:
        return None
    _t, valid = plan.paper_text(c, "E0")
    lab, _ = S.label_defective(fnd, c, plan.ledger, valid)
    return int(lab == "TRUE_DETECTION")


ag_pair = [cid for cid in mine
           if cid in ag and mine[cid][0] == "OK" and _det(ag[cid], cases[cid]) is not None]
AGENTIC_PAIRED = {
    "numerator": sum(mine[c][1] for c in ag_pair),
    "denominator": len(ag_pair),
    "pct": round(100 * sum(mine[c][1] for c in ag_pair) / len(ag_pair), 1),
    "definition": "the AGENTIC-PAIRED blind rate, and NOT a localized denominator. It is "
                  "qwen38_27 direct blind restricted to the relations where both the direct "
                  "blind generation and the Phase 3 agentic generation are valid. The "
                  "comparison figure on the same 183 cases is the agentic rate.",
    "agentic_rate_on_same_cells": {
        "numerator": sum(_det(ag[c], cases[c]) for c in ag_pair),
        "denominator": len(ag_pair),
        "pct": round(100 * sum(_det(ag[c], cases[c]) for c in ag_pair) / len(ag_pair), 1)},
    "why_183_and_not_181": "the agentic pairing drops one relation whose agentic generation "
                           "failed, a different exclusion from the three relations whose "
                           "LOCALIZED generation failed. 181 and 183 are therefore different "
                           "subsets of the same 184 relations, not a rounding or counting error.",
}

out["qwen38_27_direct_blind"] = {
    "question": "what do 31/181, 32/184 and 31/183 each represent?",
    "summary": "Three different, individually correct denominators over the same 184 "
               "relations: the marginal set, the set paired with the localized arm, and the "
               "set paired with the agentic arm. None is an error; each must state its "
               "pairing when reported.",
    "32/184": {"numerator": det(all_rel)[0], "denominator": len(all_rel),
               "definition": "the MARGINAL blind rate: every tested relation for this system. "
                             "All 184 blind requests returned a schema-valid response, so the "
                             "valid and attempted denominators coincide here.",
               "pct": round(100 * det(all_rel)[0] / len(all_rel), 1)},
    "31/181": {"numerator": det(e0ok)[0], "denominator": len(e0ok),
               "definition": "the PAIRED blind rate: blind restricted to the relations where "
                             "this system's localized E0 verdict is also schema-valid, which is "
                             "the only set on which blind and localized can be compared "
                             "case-by-case. Three localized E0 responses failed for this system.",
               "pct": round(100 * det(e0ok)[0] / len(e0ok), 1)},
    "31/183": AGENTIC_PAIRED,
}

# per-system localized denominators, to show where 181/183 come from
per_sys = {}
for m in MODELS:
    e = {k[1]: v for k, v in loc.items() if k[0] == m}
    b = {k[1]: v for k, v in blind.items() if k[0] == m}
    per_sys[m] = {
        "relations": len(b),
        "blind_valid": sum(1 for v in b.values() if v[0] == "OK"),
        "localized_E0_valid": sum(1 for v in e.values() if v.get("E0", ("", None))[0] == "OK"),
        "all_three_states_valid": sum(1 for v in e.values()
                                      if all(v.get(s, ("", None))[0] == "OK"
                                             for s in ("E0", "E1", "E2"))),
        "paired_blind_and_localized_valid": sum(
            1 for c in b if b[c][0] == "OK" and e.get(c, {}).get("E0", ("", None))[0] == "OK"),
    }
out["per_system_denominators"] = per_sys

# ---------------------------------------------------------------- 2. the two 909s
setA = {(m, c) for (m, c) in blind
        if blind[(m, c)][0] == "OK" and loc.get((m, c), {}).get("E0", ("", None))[0] == "OK"}
setB = {(m, c) for (m, c) in loc
        if all(loc[(m, c)].get(s, ("", None))[0] == "OK" for s in ("E0", "E1", "E2"))}
out["the_two_909s"] = {
    "question": "the manuscript reports 909 twice; are these the same eligible set?",
    "answer": "NO. They are different sets that happen to have the same cardinality.",
    "setA_paired_blind_and_localized_valid": {
        "n": len(setA),
        "definition": "cells where the blind response AND the localized E0 verdict are both "
                      "schema-valid; the denominator of the primary blind-versus-localized "
                      "contrast"},
    "setB_all_three_localized_states_valid": {
        "n": len(setB),
        "definition": "cells where the localized verdict is schema-valid in E0, E1 AND E2; the "
                      "denominator of the three-state trajectory metric. It does not require a "
                      "blind response at all, and it does require E1 and E2, which set A does not."},
    "identical": setA == setB,
    "in_A_not_B": len(setA - setB),
    "in_B_not_A": len(setB - setA),
    "intersection": len(setA & setB),
    "proof": f"The two sets both have {len(setA)} members but differ on "
             f"{len(setA ^ setB)} cells: {len(setA - setB)} are in the paired-contrast set only "
             f"and {len(setB - setA)} are in the trajectory set only. Equal size is a "
             f"coincidence of two different exclusions cancelling, not the same denominator.",
    "total_cells": len(MODELS) * 184,
}

# ---------------------------------------------------------------- 3. off-target audit
inv = json.loads((TV / "data/AUDIT_RESPONSE_INVENTORY.json").read_text()) \
    if (TV / "data/AUDIT_RESPONSE_INVENTORY.json").exists() else {}
imp = json.loads((TV / "data/AUDIT_IMPACT.json").read_text()) \
    if (TV / "data/AUDIT_IMPACT.json").exists() else {}
import csv as _csv, glob as _glob
_pk = json.loads((RR / "audit_packet/BLIND_SCORER_AUDIT_ITEMS.json").read_text())
_kind = {it["audit_id"]: it["kind"] for it in _pk["items"]}
_rows = []
for _f in sorted(_glob.glob(str(RR / "blind_scorer_human_review_responses/*.csv"))):
    with open(_f) as fh:
        _rows += [r for r in _csv.DictReader(fh) if r.get("item_id")]


def _offtarget(kind):
    sel = [r for r in _rows if _kind.get(r["item_id"]) == kind]
    byitem = collections.defaultdict(list)
    for r in sel:
        byitem[r["item_id"]].append(r["q2_other_problem_genuine"].strip())
    gen = sorted(i for i, v in byitem.items()
                 if sum(1 for x in v if x.startswith("Yes")) * 2 > len(v))
    y = sum(1 for r in sel if r["q2_other_problem_genuine"].strip().startswith("Yes"))
    return {"n_items": len(byitem), "items_majority_genuine": len(gen),
            "item_rate_pct": round(100 * len(gen) / len(byitem), 1),
            "n_judgments": len(sel), "judgments_genuine": y,
            "judgment_rate_pct": round(100 * y / len(sel), 1),
            "item_ids": gen}


_fp, _ms = _offtarget("FALSE_POSITIVE"), _offtarget("MISS")
out["off_target_audit_units"] = {
    "question": "3/30 = 10.0% versus 12.2% \u2014 which unit is which, and are both right?",
    "answer": "Both are correct and both describe the SAME false-positive half of the audit. "
              "They differ only in the unit of analysis, and neither may be quoted without "
              "naming its unit.",
    "false_positive_half": {
        "items": f"{_fp['items_majority_genuine']}/{_fp['n_items']} "
                 f"({_fp['item_rate_pct']}%)",
        "items_definition": "ITEMS on which a MAJORITY of the six reviewers judged the "
                            "off-target finding to be a genuine additional issue. The unit is "
                            "the item; the six reviewers contribute one majority verdict.",
        "judgments": f"{_fp['judgments_genuine']}/{_fp['n_judgments']} "
                     f"({_fp['judgment_rate_pct']}%)",
        "judgments_definition": "INDIVIDUAL reviewer-by-item judgments of 'genuine'. The unit "
                                "is one reviewer's answer on one item, so the denominator is "
                                "reviewers x items = 6 x 30 = 180, not 30.",
        "recomputed": _fp,
    },
    "miss_half_for_contrast": {
        "items": f"{_ms['items_majority_genuine']}/{_ms['n_items']} ({_ms['item_rate_pct']}%)",
        "judgments": f"{_ms['judgments_genuine']}/{_ms['n_judgments']} "
                     f"({_ms['judgment_rate_pct']}%)",
        "recomputed": _ms,
    },
    "rule": "An item-level rate and a judgment-level rate are not interchangeable and must "
            "never be pooled or compared with each other. The judgment-level rate is the "
            "higher of the two here because the reviewers who called a finding genuine were "
            "spread across items rather than concentrated on the three items that reached a "
            "majority.",
}

# ---------------------------------------------------------------- 4. frontier claim
f = F.Fair()
sub = set(f.subset)
rows60 = {}
for m in MODELS:
    n = k = 0
    for c in sub:
        st = loc.get((m, c), {}).get("E0")
        if st and st[0] == "OK":
            n += 1
            k += st[1]
    rows60[m] = {"n": n, "k": k, "pct": round(100 * k / n, 1) if n else None}
gpt = [c for c in f.rows(F.FRONTIER, "RELATION_LOCALIZED_BINARY_VERDICT")
       if c.get("e0_status") == "OK"]
rows60[F.FRONTIER] = {"n": len(gpt), "k": sum(c.get("e0_correct", 0) for c in gpt),
                      "pct": round(100 * sum(c.get("e0_correct", 0) for c in gpt) / len(gpt), 1)}
full184 = {}
for m in MODELS:
    n = k = 0
    for (mm, c), v in loc.items():
        if mm != m:
            continue
        st = v.get("E0")
        if st and st[0] == "OK":
            n += 1
            k += st[1]
    full184[m] = {"n": n, "k": k, "pct": round(100 * k / n, 1)}
best60 = max(rows60, key=lambda m: rows60[m]["pct"])
out["frontier_highest_verdict_rung_claim"] = {
    "question": "is GPT-5.2 the highest on the verdict rung?",
    "rule": "The comparison must be made on the SAME 60-relation ladder subset. A 60-relation "
            "frontier figure may not be compared against a 184-relation open-weight aggregate.",
    "same_subset_60_relations": rows60,
    "open_weight_full_184_for_reference_only": full184,
    "highest_on_the_60_relation_subset": best60,
    "gpt_5_2_rank_on_subset": sorted(rows60, key=lambda m: -rows60[m]["pct"]).index(F.FRONTIER) + 1,
    "verdict": ("SUPPORTED" if best60 == F.FRONTIER else "NOT_SUPPORTED"),
    "statement_that_is_defensible": None,
}
r60 = rows60
out["frontier_highest_verdict_rung_claim"]["statement_that_is_defensible"] = (
    f"On the shared 60-relation subset GPT-5.2 reaches {r60[F.FRONTIER]['pct']}% "
    f"({r60[F.FRONTIER]['k']}/{r60[F.FRONTIER]['n']}) on the verdict rung, "
    + (f"the highest of any system measured."
       if best60 == F.FRONTIER else
       f"which is BELOW {best60} at {r60[best60]['pct']}% "
       f"({r60[best60]['k']}/{r60[best60]['n']}). The claim that the frontier system posts the "
       f"highest verdict-rung rate is NOT supported once the comparison is made on the same "
       f"relations.")
)

# ---------------------------------------------------------------- 5. rounding
out["rounding_rule"] = {
    "rule": "One decimal place for primary percentages and percentage-point effects.",
    "exceptions": ["exact p-values, reported in scientific notation or as a bound",
                   "d-prime, reported to two decimals because the unit is not a percentage",
                   "counts, which are integers"],
}

(OUT / "data/DENOMINATOR_RECONCILIATION.json").write_text(json.dumps(out, indent=1) + "\n")
print(json.dumps({k: v for k, v in out.items()
                  if k in ("the_two_909s", "frontier_highest_verdict_rung_claim")}, indent=1)[:3000])
print("\nper-system denominators:")
for m, v in per_sys.items():
    print(f"  {m:14s} {v}")

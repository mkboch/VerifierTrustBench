#!/usr/bin/env python3
"""Build the held-out benchmark from mined cases (no model involvement anywhere).

    python exp3heldout/build_dataset.py --papers <id> ...

For every mined case this writes the E0 and E2 manuscript variants, a templated target question, templated true/false
rationales for the exposure matrix, blind-scorer tokens, and the ledger entry expected by the frozen 2B scorer
(exp2b/scoring.py). Question and rationale templates are frozen here, before any verifier inference, and are the same
for E0, E1 and E2 of a case: they name the relation, never its state and never the location of a defect.
Outputs: exp3heldout/benchmark/<paper>/<case_id>/{E0,E2}.tex and exp3heldout/ledger.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2b"))
sys.path.insert(0, str(ROOT / "exp3heldout"))
import normalize as N  # noqa: E402
import checkers as C  # noqa: E402
import mine_cases as M  # noqa: E402

PAPERS = ROOT / "exp3heldout/papers"
MINED = ROOT / "exp3heldout/mined"
BENCH = ROOT / "exp3heldout/benchmark"
LEDGER = ROOT / "exp3heldout/ledger.json"

OP_WORD = {"pct": "percentage", "div": "ratio", "diff": "difference", "sum": "total"}
FAMILY_ABBR = {"arithmetic": "arith", "numerical": "num", "cross_reference": "xref", "statistical": "stat",
               "claim_evidence": "claim", "method_result": "method"}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def num_token(lit: str) -> str:
    return rf"(?<![\d.]){re.escape(lit)}(?![\d])"


# --------------------------------------------------------------------------- frozen templates

def question_for(case: dict) -> str:
    f, v, a = case["family"], case["values"], case["anchor"]
    if f == "arithmetic":
        return (f"In the passage about {a}, is the stated {OP_WORD.get(v['op'], 'value')} arithmetically consistent "
                f"with the two quantities it is computed from in the same sentence?")
    if f == "numerical":
        return (f"The manuscript reports the same {v.get('keyword', 'quantity')} value for {a} in more than one place. "
                f"Are those reported values mutually consistent?")
    if f == "cross_reference":
        return (f"In the passage about {a}, does the cited {v['declared']} cross-reference resolve to an existing "
                f"{v['declared']} of that kind in this manuscript?")
    if f == "statistical":
        if v.get("kind") == "range_containment":
            return (f"In the passage about {a}, is the reported central value consistent with the range reported in "
                    f"the same sentence?")
        return (f"In the passage about {a}, is the statistical-significance statement consistent with the reported "
                f"p-value at the stated threshold?")
    if f == "claim_evidence":
        return (f"In the passage about {a}, is the comparative claim supported by the values reported in the same "
                f"sentence?")
    return (f"The manuscript states the {v.get('setting', 'configuration')} setting for {a} in more than one place. "
            f"Are those statements mutually consistent?")


def rationales_for(case: dict, lines: dict) -> dict:
    """True/false rationales for E0 and E1, built from the checker's own values (frozen templates)."""
    f, v = case["family"], case["values"]
    t0 = case["target_lines"][0]
    loc = ", ".join(f"L{n:05d}" for n in case["target_lines"])
    if f == "arithmetic":
        base = (f"{loc} reports {v['operand_a']} and {v['operand_b']} together with a stated "
                f"{OP_WORD.get(v['op'], 'value')}")
        e0_true = (f"{base}. Recomputing the {OP_WORD.get(v['op'], 'value')} from those two quantities does not give "
                   f"the stated {v['e0_value']}, so the sentence is internally inconsistent.")
        e0_false = (f"{base}. Recomputing it from those two quantities reproduces the stated {v['e0_value']}, so the "
                    f"sentence is internally consistent.")
        e1_true = (f"{base}. Recomputing it from those two quantities reproduces the stated {v['stated']}, so the "
                   f"relation holds.")
        e1_false = (f"{base}. Recomputing it from those two quantities does not give the stated {v['stated']}, so the "
                    f"sentence is internally inconsistent.")
    elif f in ("numerical", "method_result"):
        what = v.get("keyword") or v.get("setting") or "value"
        e0_true = (f"{loc} report the same {what}, but the two statements now give {v['e0_value']} and {v['value']}; "
                   f"they do not agree.")
        e0_false = (f"{loc} report the same {what} and the two statements agree on {v['e0_value']}; there is no "
                    f"discrepancy.")
        e1_true = f"{loc} report the same {what} and both statements give {v['value']}; the manuscript is consistent."
        e1_false = (f"{loc} report the same {what} but the two statements disagree, giving {v['value']} in one place "
                    f"and a different value in the other.")
    elif f == "cross_reference":
        e0_true = (f"L{t0:05d} cites a {v['declared']} cross-reference, but the cited label does not resolve to a "
                   f"{v['declared']} in this manuscript.")
        e0_false = (f"L{t0:05d} cites a {v['declared']} cross-reference and the cited label resolves to the "
                    f"{v['declared']} it names.")
        e1_true = (f"L{t0:05d} cites the {v['declared']} label {v['label']}, which is defined on a {v['declared']} in "
                   f"this manuscript; the reference resolves correctly.")
        e1_false = (f"L{t0:05d} cites the {v['declared']} label {v['label']}, which does not resolve to a "
                    f"{v['declared']} in this manuscript.")
    elif f == "statistical" and v.get("kind") == "range_containment":
        e0_true = (f"L{t0:05d} reports a central value together with a range of {v['low']} to {v['high']}; the stated "
                   f"central value lies outside that range.")
        e0_false = (f"L{t0:05d} reports a central value inside the stated range of {v['low']} to {v['high']}.")
        e1_true = (f"L{t0:05d} reports a central value of {v['value']} inside the stated range {v['low']} to "
                   f"{v['high']}; the two are consistent.")
        e1_false = (f"L{t0:05d} reports a central value of {v['value']} that lies outside the stated range {v['low']} "
                    f"to {v['high']}.")
    elif f == "statistical":
        e0_true = (f"L{t0:05d} makes a significance statement together with a p-value of {v['e0_value']} at the "
                   f"0.05 threshold; the statement and the p-value disagree.")
        e0_false = (f"L{t0:05d} makes a significance statement together with a p-value of {v['e0_value']}; at the "
                    f"0.05 threshold the two agree.")
        e1_true = (f"L{t0:05d} makes a significance statement together with a p-value of {v['p']}; at the 0.05 "
                   f"threshold the statement and the p-value agree.")
        e1_false = (f"L{t0:05d} makes a significance statement together with a p-value of {v['p']}; at the 0.05 "
                    f"threshold the statement and the p-value disagree.")
    else:  # claim_evidence
        comp = ", ".join(v["others"])
        word = "highest" if v["direction"] == "max" else "lowest"
        e0_true = (f"L{t0:05d} claims the {word} value, but the value it reports for the named item ({v['e0_value']}) "
                   f"is not the {word} of the values in the same sentence ({comp}).")
        e0_false = (f"L{t0:05d} claims the {word} value and the value it reports for the named item "
                    f"({v['e0_value']}) is indeed the {word} of the values in the same sentence ({comp}).")
        e1_true = (f"L{t0:05d} claims the {word} value and reports {v['claimed']} for the named item, which is the "
                   f"{word} of the values in the same sentence ({comp}).")
        e1_false = (f"L{t0:05d} claims the {word} value but reports {v['claimed']} for the named item, which is not "
                    f"the {word} of the values in the same sentence ({comp}).")
    return {"E0": {"true": e0_true, "false": e0_false}, "E1": {"true": e1_true, "false": e1_false}}


def blind_tokens_for(case: dict) -> dict:
    v = case["values"]
    if case["family"] == "cross_reference":
        e0 = [re.escape(v["wrong_label"]), re.escape(v["dangling"]), re.escape(v["label"])]
        e1 = [re.escape(v["label"])]
    elif case["family"] == "arithmetic":
        e0 = [num_token(v["e0_value"]), num_token(v["operand_a"]), num_token(v["operand_b"])]
        e1 = [num_token(v["stated"]), num_token(v["operand_a"]), num_token(v["operand_b"])]
    elif case["family"] in ("numerical", "method_result"):
        e0 = [num_token(v["e0_value"]), num_token(v["value"])]
        e1 = [num_token(v["value"])]
    elif case["family"] == "statistical" and v.get("kind") == "range_containment":
        e0 = [num_token(v["low"]), num_token(v["high"])]
        e1 = [num_token(v["value"]), num_token(v["low"]), num_token(v["high"])]
    elif case["family"] == "statistical":
        e0 = [num_token(v.get("e0_value", "0.21")), r"signific"]
        e1 = [num_token(v["p"]), r"signific"]
    else:
        e0 = [num_token(v["e0_value"])] + [num_token(o) for o in v["others"]]
        e1 = [num_token(v["claimed"])] + [num_token(o) for o in v["others"]]
    return {"E0": e0, "E1": e1}


def gold_explanation(case: dict) -> str:
    v, f = case["values"], case["family"]
    if f == "arithmetic":
        return (f"E1: the stated {OP_WORD.get(v['op'])} {v['stated']} follows from {v['operand_a']} and "
                f"{v['operand_b']} (checker chk_arith, op={v['op']}). E0 changes the stated value to {v['e0_value']}; "
                f"E2 changes the operand {v['operand_a']} to {v['e2_value']}.")
    if f in ("numerical", "method_result"):
        return (f"E1: both statements report {v['value']} (chk_equal). E0 changes the first occurrence to "
                f"{v['e0_value']}; E2 changes the second occurrence to {v['e2_value']}.")
    if f == "cross_reference":
        return (f"E1: the cited label {v['label']} resolves to a {v['declared']} (chk_xref). E0 retargets it to "
                f"{v['wrong_label']} (wrong float type); E2 retargets it to the non-existent label {v['dangling']}.")
    if f == "statistical" and v.get("kind") == "range_containment":
        return (f"E1: the central value {v['value']} lies inside [{v['low']}, {v['high']}] (chk_range). E0 moves the "
                f"central value outside the range; E2 moves the range bound instead.")
    if f == "statistical":
        return (f"E1: p={v['p']} agrees with the significance statement at alpha=0.05 (chk_stat_sig). E0 changes the "
                f"p-value to {v.get('e0_value')}; E2 flips the significance wording instead.")
    return (f"E1: the claimed value {v['claimed']} is the {'max' if v['direction'] == 'max' else 'min'} of "
            f"{v['others']} (chk_extreme). E0 lowers/raises the claimed value to {v['e0_value']}; E2 changes a "
            f"comparator to {v['e2_value']}.")


def build(pids: list[str], domains: dict) -> dict:
    BENCH.mkdir(parents=True, exist_ok=True)
    cases_out, papers = [], []
    for pid in pids:
        mined = json.loads((MINED / f"{pid}.json").read_text())
        body = (PAPERS / pid / "E1.tex").read_text()
        numbered, _ = N.number(body)
        lines = C.lines_of(numbered)
        e1_path = f"exp3heldout/papers/{pid}/E1.tex"
        for i, cand in enumerate(mined["cases"], start=1):
            cid = f"p{pid.replace('.', '')[-5:]}_{FAMILY_ABBR[cand['family']]}_{i:02d}"
            d = BENCH / pid / cid
            d.mkdir(parents=True, exist_ok=True)
            variants = M.validate(cand, body)
            if variants is None:
                raise SystemExit(f"case no longer validates: {pid} {cid}")
            paths = {"E1": e1_path}
            shas = {"E1": sha(body)}
            for st in ("E0", "E2"):
                p = d / f"{st}.tex"
                p.write_text(variants[st])
                paths[st] = str(p.relative_to(ROOT))
                shas[st] = sha(variants[st])
            checks = {st: C.check(cand["spec"], N.number(variants[st] if st != "E1" else body)[0])
                      for st in ("E0", "E1", "E2")}
            cases_out.append({
                "paper": pid, "domain": domains[pid], "case_id": cid, "family": cand["family"],
                "title": f"{cand['family']} relation on {cand['anchor'][:60]}",
                "question": question_for(cand), "target_lines": cand["target_lines"],
                "location_text": ", ".join(f"L{n:05d}" for n in cand["target_lines"]),
                "edits": cand["edits"], "paths": paths, "sha256": shas,
                "truth": {"E0": "ISSUE_PRESENT", "E1": "NO_ISSUE", "E2": "ISSUE_PRESENT"},
                "checker": cand["spec"]["fn"], "checker_spec": cand["spec"], "checker_results": checks,
                "gold_explanation": gold_explanation(cand), "blind_tokens": blind_tokens_for(cand),
                "values": cand["values"], "anchor": cand["anchor"], "matrix": False,
                "rationales": rationales_for(cand, lines)})
        papers.append(pid)
    old = json.loads((ROOT / "exp2b/ledger.json").read_text())
    ledger = {"benchmark": "VerifierTrustBench held-out corpus (exp3heldout)",
              "states": ["E0", "E1", "E2"], "truth": {"E0": "ISSUE_PRESENT", "E1": "NO_ISSUE", "E2": "ISSUE_PRESENT"},
              "roles": {"E0": "defective native edit", "E1": "unmodified manuscript", "E2": "alternate native edit"},
              "papers": papers, "domains": domains,
              "family_counts": {f: sum(1 for c in cases_out if c["family"] == f)
                                for f in sorted({c["family"] for c in cases_out})},
              "family_terms": old["family_terms"], "generic_flag_terms": old["generic_flag_terms"],
              "cases": cases_out}
    LEDGER.write_text(json.dumps(ledger, indent=1) + "\n")
    return ledger


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--papers", nargs="+", required=True)
    ap.add_argument("--domains", required=True, help="json map paper->domain")
    a = ap.parse_args()
    led = build(a.papers, json.loads(Path(a.domains).read_text()))
    print(f"{len(led['papers'])} papers, {len(led['cases'])} cases, families {led['family_counts']}")


if __name__ == "__main__":
    main()

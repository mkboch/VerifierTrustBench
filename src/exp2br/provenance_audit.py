#!/usr/bin/env python3
"""No-inference evidence-provenance audit of the immutable Experiment 2B targeted records.

    python exp2br/provenance_audit.py --out-dir runs/exp2br_<ts>

For every valid targeted trial (evidence, matrix, pair) in runs/exp2b_20260914_142911, each cited line ID is classified
against the exact manuscript variant that was sent:
  TARGET_EXACT      a non-empty line that belongs to the tested relation (the case's target lines)
  OUTSIDE_RELATION  a non-empty manuscript line that is not part of the tested relation
  ADJACENT_BLANK    an empty line immediately next to a content line (off-by-one); '->target' if that neighbour is a target line
  NONEXISTENT       no such line in the manuscript
  MALFORMED         not in the L00000 form
Trial categories: GROUNDED (>= 1 TARGET_EXACT), GROUNDED_VIA_ADJACENT (only via an adjacent blank next to a target line),
UNGROUNDED_VALID_LINES (only outside-relation content lines), INVALID_ONLY (only nonexistent/malformed), NO_CITATION.
Verdict correctness and provenance are reported separately. Writes PROVENANCE_AUDIT.md and provenance_audit.csv.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2b"))
import design as D  # noqa: E402
import evaluate as EV  # noqa: E402

RUN_2B = ROOT / "runs/exp2b_20260914_142911"


def classify(ids, malformed, valid, targets):
    cats = []
    for i in ids:
        if i in valid:
            cats.append("TARGET_EXACT" if i in targets else "OUTSIDE_RELATION")
        elif (i - 1) in valid or (i + 1) in valid:
            cats.append("ADJACENT_BLANK->target" if ({i - 1, i + 1} & set(targets)) else "ADJACENT_BLANK")
        else:
            cats.append("NONEXISTENT")
    cats += ["MALFORMED"] * len(malformed)
    if not cats:
        trial = "NO_CITATION"
    elif "TARGET_EXACT" in cats:
        trial = "GROUNDED"
    elif "ADJACENT_BLANK->target" in cats:
        trial = "GROUNDED_VIA_ADJACENT"
    elif "OUTSIDE_RELATION" in cats or "ADJACENT_BLANK" in cats:
        trial = "UNGROUNDED_VALID_LINES"
    else:
        trial = "INVALID_ONLY"
    return cats, trial


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    od = Path(ap.parse_args().out_dir)
    od = od if od.is_absolute() else ROOT / od
    od.mkdir(parents=True, exist_ok=True)
    plan = D.Plan("full")
    cases = {c["case_id"]: c for c in plan.all_cases}
    ids_c = defaultdict(Counter)
    trial_c = defaultdict(Counter)
    rows = []
    for exp in ("evidence", "matrix", "pair"):
        latest, _ = EV.load(RUN_2B / f"{exp}_trials.jsonl")
        for r in latest.values():
            if r["result"]["status"] != "OK":
                continue
            c = cases[r["case_id"]]
            text, valid = plan.paper(c, r["state"])
            p = r["result"]["parsed"]
            cats, trial = classify(p["evidence_line_ids"], p["evidence_line_ids_malformed"], valid, c["target_lines"])
            correct = p["verdict"] == r["truth"]
            ids_c[(exp, r["model"])].update(cats)
            trial_c[(exp, r["model"], correct)][trial] += 1
            if exp == "evidence":
                rows.append({"model": r["model"], "paper": r["paper"], "case_id": r["case_id"], "family": r["family"], "state": r["state"],
                             "verdict": p["verdict"], "correct": correct, "n_ids": len(cats), "trial_provenance": trial,
                             **{k: cats.count(k) for k in ("TARGET_EXACT", "OUTSIDE_RELATION", "ADJACENT_BLANK", "ADJACENT_BLANK->target", "NONEXISTENT", "MALFORMED")}})
    EV.to_csv(od / "provenance_audit.csv", rows)
    models = D.PRIMARY
    cat_order = ("TARGET_EXACT", "OUTSIDE_RELATION", "ADJACENT_BLANK->target", "ADJACENT_BLANK", "NONEXISTENT", "MALFORMED")
    trial_order = ("GROUNDED", "GROUNDED_VIA_ADJACENT", "UNGROUNDED_VALID_LINES", "INVALID_ONLY", "NO_CITATION")
    L = ["# Evidence-provenance audit (no new inference)", "",
         "Source: immutable Experiment 2B targeted records (`runs/exp2b_20260914_142911`: evidence, matrix and pair trials with valid output). "
         "Each cited line ID is classified against the manuscript variant actually sent and the tested relation's target lines "
         "(`exp2b/ledger.json`). Verdict correctness and provenance are separate measurements.", "",
         "## 1. Cited line IDs (evidence trials)", "", "| Model | IDs | Target line (exact) | Valid line outside relation | Adjacent blank next to target | Adjacent blank elsewhere | Nonexistent | Malformed |", "|---|---|---|---|---|---|---|---|"]
    for m in models:
        c = ids_c[("evidence", m)]
        n = sum(c.values())
        L.append(f"| {m} | {n} | " + " | ".join(f"{c[k]} ({100 * c[k] / n:.1f}%)" for k in cat_order) + " |")
    L += ["", "## 2. Trial-level provenance by verdict correctness (evidence trials)", "",
          "GROUNDED = cites at least one exact line of the tested relation.", "",
          "| Model | Verdict | Trials | Grounded | Grounded only via adjacent blank | Only outside-relation lines | Only invalid IDs | No citation |", "|---|---|---|---|---|---|---|---|"]
    summary = {}
    for m in models:
        for correct in (True, False):
            c = trial_c[("evidence", m, correct)]
            n = sum(c.values())
            if not n:
                continue
            L.append(f"| {m} | {'correct' if correct else 'incorrect'} | {n} | " + " | ".join(f"{c[k]} ({100 * c[k] / n:.1f}%)" for k in trial_order) + " |")
        allc = trial_c[("evidence", m, True)] + trial_c[("evidence", m, False)]
        n = sum(allc.values())
        summary[m] = {"trials": n, "grounded_rate": round(allc["GROUNDED"] / n, 4), "ungrounded_valid_rate": round(allc["UNGROUNDED_VALID_LINES"] / n, 4),
                      "correct_trials": sum(trial_c[("evidence", m, True)].values()),
                      "correct_and_grounded": trial_c[("evidence", m, True)]["GROUNDED"]}
    L += ["", "## 3. Same audit for matrix and pair trials (trial level, all verdicts)", "", "| Experiment | Model | Trials | Grounded | Only outside-relation lines | Only invalid |", "|---|---|---|---|---|---|"]
    for exp in ("matrix", "pair"):
        for m in models:
            c = trial_c[(exp, m, True)] + trial_c[(exp, m, False)]
            n = sum(c.values())
            if n:
                L.append(f"| {exp} | {m} | {n} | {c['GROUNDED']} ({100 * c['GROUNDED'] / n:.1f}%) | {c['UNGROUNDED_VALID_LINES']} ({100 * c['UNGROUNDED_VALID_LINES'] / n:.1f}%) | {c['INVALID_ONLY']} |")
    q = summary.get("qwen3_8")
    L += ["", "## 4. Interpretation for manuscript wording", "",
          "- A verifier is described as evidence-grounded on a trial only when its cited lines include the tested relation. Verdict "
          "correctness alone does not establish that.",
          f"- qwen3_8: {q['trials']} evidence trials, grounded {100 * q['grounded_rate']:.1f}%, citing only valid lines outside the relation "
          f"{100 * q['ungrounded_valid_rate']:.1f}%; of its {q['correct_trials']} correct verdicts, {q['correct_and_grounded']} cite the relation. "
          "Its verdict responsiveness and its evidence-provenance validity must be reported separately; claims about qwen3_8 should say "
          "'verdict accuracy', not 'evidence-grounded verification'." if q else "",
          "- For qwen38_27, qwen36_27 and gemma4_12 see the table: nearly every trial, correct or incorrect, cites the tested relation, so "
          "their citations support (but do not prove) that the verdict was based on the relevant lines.", ""]
    (od / "PROVENANCE_AUDIT.md").write_text("\n".join(L) + "\n")
    (od / "provenance_audit.json").write_text(json.dumps({"ids": {f"{e}|{m}": dict(v) for (e, m), v in ids_c.items()},
                                                          "trials": {f"{e}|{m}|{'correct' if c else 'incorrect'}": dict(v) for (e, m, c), v in trial_c.items()},
                                                          "summary": summary}, indent=1) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()

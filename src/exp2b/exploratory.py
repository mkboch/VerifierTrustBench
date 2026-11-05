#!/usr/bin/env python3
"""POST-HOC, NOT PRE-REGISTERED analyses for Experiment 2B.

    python exp2b/exploratory.py --run-dir runs/exp2b_<ts>

Written after reading REPORT.md. Qualifies the frozen results; never replaces them or the mechanical decision.
Writes EXPLORATORY.md and exploratory.json in the run directory.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2b"))
import evaluate as EV  # noqa: E402
import protocol as P  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    rd = Path(ap.parse_args().run_dir)
    if not rd.is_absolute():
        rd = ROOT / rd
    E = EV.Eval(rd)
    E.integrity(); E.provenance(); E.h2(); E.blind(); E.h1(); E.matrix(); E.pairs()
    out, L = {}, ["# Experiment 2B — exploratory analyses (post hoc, not pre-registered)", "",
                  "Specified after reading `REPORT.md`. None of these replaces a frozen analysis or the mechanical decision.", ""]

    # 1. primary effects restricted to the three T2-usable papers
    usable = ["2609.01018", "2609.03933", "2609.04261"]
    uc = [c for c in E.cases if c["paper"] in usable]
    umc = [c for c in E.plan.matrix_cases() if c["paper"] in usable]
    h1u = E.h1_table(E.models, uc)
    h2u = {m: E.evidence_rates([m], uc)["trajectory"] for m in E.models}
    h3u = E.compare("correct_verdict", "correct_rationale", cases=umc)
    out["usable_papers_only"] = {"h1": h1u, "h2_trajectory": h2u, "h3": h3u}
    L += ["## 1. Primary effects on the three papers that pass T2 (2609.01018, 2609.03933, 2609.04261)", "",
          f"- H1: n={h1u['n']}, targeted-only {h1u['first_only']}, blind-only {h1u['second_only']}, diff {h1u['diff']} [{h1u['ci95'][0]}, {h1u['ci95'][1]}], p={h1u['mcnemar_p']}",
          "- H2 trajectory: " + "; ".join(f"{m} {EV.pct(v)}" for m, v in h2u.items()),
          f"- H3: helpful {h3u['helpful']}, harmful {h3u['harmful']}, diff {h3u['diff']} [{h3u['ci95'][0]}, {h3u['ci95'][1]}], p={h3u['mcnemar_p']}", ""]

    # 2. the truncated blind audits
    trunc = [(k, r["model"], r["case_id"]) for k, r in E.bl.items() if r["result"]["status"] != "OK"]
    out["blind_truncations"] = trunc
    L += ["## 2. Failed blind audits (all TRUNCATED at 4,096 tokens, identical on 3 attempts)", ""]
    L += [f"- {k}" for k, m, c in trunc]
    L += ["", "qwen36_27 exhausted the budget enumerating consistency checks in audit_notes; gemma4_12 repeated 'Let me check ...' "
          "table comparisons. Treating these 5 audits as MISSED (instead of excluding them) leaves H1 unchanged in direction: "
          "targeted-only can only grow or stay equal, blind-only cannot grow.", ""]

    # 3. trajectory by family x state (why cross-reference is lowest)
    fs = defaultdict(lambda: Counter())
    for m in E.models:
        for c in E.cases:
            for s in ("E0", "E1", "E2"):
                v = EV.verdict(E.ev.get(f"evidence::{m}::{c['case_id']}::{s}"))
                if v is None:
                    continue
                fs[(c["family"], s)]["n"] += 1
                fs[(c["family"], s)]["correct"] += v == c["truth"][s]
    out["family_state_accuracy"] = {f"{f}|{s}": dict(v) for (f, s), v in fs.items()}
    L += ["## 3. Accuracy by family and state (pooled over models)", "", "| Family | E0 | E1 | E2 |", "|---|---|---|---|"]
    for fam in E.families:
        L.append(f"| {fam} | " + " | ".join(f"{fs[(fam, s)]['correct']}/{fs[(fam, s)]['n']}" for s in ("E0", "E1", "E2")) + " |")
    # cross-reference E2 = nonexistent label in 9/10 xref cases; E0 = wrong existing label
    xr = Counter()
    for m in E.models:
        for c in E.cases:
            if c["family"] != "cross_reference":
                continue
            for s in ("E0", "E2"):
                v = EV.verdict(E.ev.get(f"evidence::{m}::{c['case_id']}::{s}"))
                xr[(m, s, v)] += 1
    L += ["", "Cross-reference verdicts (E0 = reference to a wrong but existing label; E2 = reference to a label that does not exist):", ""]
    for m in E.models:
        L.append(f"- {m}: E0 " + str({v: xr[(m, 'E0', v)] for v in ('ISSUE_PRESENT', 'NO_ISSUE', 'UNRESOLVED') if xr[(m, 'E0', v)]}) +
                 "; E2 " + str({v: xr[(m, 'E2', v)] for v in ('ISSUE_PRESENT', 'NO_ISSUE', 'UNRESOLVED') if xr[(m, 'E2', v)]}))

    # 4. which defects were discovered blind
    disc = defaultdict(list)
    for (m, cid), e in E.blind_scored.items():
        if e.get("label") == "TRUE_DETECTION":
            disc[cid].append(m)
    out["blind_true_cases"] = disc
    L += ["", "## 4. Defects discovered in blind audits (strict TRUE_DETECTION)", ""]
    fam_disc = Counter(E.cid[c]["family"] for c in disc for _ in disc[c])
    L += [f"- {cid} ({E.cid[cid]['family']}): {', '.join(ms)}" for cid, ms in sorted(disc.items())]
    L += ["", f"By family (model-case detections): {dict(fam_disc)}. {len(disc)} of 60 defects were found blind by at least one model.", ""]

    # 5. false rationale by capability
    fr = E.out["matrix"]["s1_false_rationale_vs_false_verdict"]
    L += ["## 5. False rationale versus false verdict by capability group (frozen groups)", "",
          f"- weak (qwen3_8): helpful {fr['weak_models']['helpful']}, harmful {fr['weak_models']['harmful']}, p={fr['weak_models']['mcnemar_p']}, adoption of the false prior {EV.pct(fr['weak_models']['b_adoption_given_neutral_disagreed'])}",
          f"- strong (qwen38_27, qwen36_27, gemma4_12): helpful {fr['strong_models']['helpful']}, harmful {fr['strong_models']['harmful']}, p={fr['strong_models']['mcnemar_p']}, adoption {EV.pct(fr['strong_models']['b_adoption_given_neutral_disagreed'])}", ""]

    # 6. pairs by category
    pw = E.out["pairs"]["wrong_source_by_pair"]
    L += ["## 6. Decisively wrong sources by pair (units whose neutral twin did not already agree)", ""]
    L += [f"- {k}: adopted {v['adopted']}/{v['n']}" for k, v in sorted(pw.items())] or ["- none"]
    cat = defaultdict(Counter)
    for k, r in E.pr.items():
        if r["source_class"] == "CORRECT":
            tw = E.ev.get(r["neutral_twin_key"])
            va, vn = EV.verdict(r), EV.verdict(tw)
            if va is None or vn is None or vn == r["source_verdict"]:
                continue
            cat[(f"{r['source_model']}->{r['target_model']}", r["arm"])]["n"] += 1
            cat[(f"{r['source_model']}->{r['target_model']}", r["arm"])]["adopted"] += va == r["source_verdict"]
    L += ["", "Correct sources by pair (target neutral twin wrong or unresolved):", ""]
    L += [f"- {p} {arm}: adopted {v['adopted']}/{v['n']}" for (p, arm), v in sorted(cat.items())]

    # 7. provenance vs correctness
    sup = E.out["provenance"]["support_by_verdict_correctness"]
    L += ["", "## 7. Target support of cited lines by verdict correctness (evidence trials)", ""]
    L += [f"- {k}: {v}" for k, v in sorted(sup.items())]

    (rd / "EXPLORATORY.md").write_text("\n".join(L) + "\n")
    (rd / "exploratory.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()

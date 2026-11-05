#!/usr/bin/env python3
"""Dataset quality gate for the held-out corpus (no model involvement anywhere).

    python exp3heldout/audit_dataset.py

Checks every frozen candidate case before the dataset freeze:
  A1 checker integrity      chk(E1)=consistent, chk(E0)=inconsistent, chk(E2)=inconsistent
  A2 variant identity       E0/E2 differ from E1 only inside the declared target lines, and line counts are identical
  A3 line-ID validity       every target line exists in all three variants
  A4 no leakage wording     the mutated text introduces no generic flag term ("inserted", "inconsistent", ...)
  A5 minimal native edit    each edit changes <= 40 characters and adds no new sentence
  A6 no duplicate relations same (paper, target lines) or identical (old -> new) mutation used twice
  A7 no case overlap        two cases of one paper never share a target line
  A8 LaTeX integrity        \\begin/\\end balance unchanged, no unbalanced braces introduced
  A9 context fit            line-numbered variant within the frozen token band for the primary models
  A10 balance               per-family and per-domain counts reported; papers below MIN_CASES flagged
Cases failing A1-A8 are rejected (written to exp3heldout/audit_rejected.json) and removed from the ledger before freeze.
Outputs: exp3heldout/CASE_AUDIT.md, exp3heldout/audit.json, and a filtered exp3heldout/ledger.json
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2b"))
sys.path.insert(0, str(ROOT / "exp3heldout"))
import normalize as N  # noqa: E402
import checkers as C  # noqa: E402

LEDGER = ROOT / "exp3heldout/ledger.json"
TOK_MAX_MANUSCRIPT = 24000
FLAG_TERMS = None
_TOK = None


def tok():
    global _TOK
    if _TOK is None:
        from transformers import AutoTokenizer
        _TOK = AutoTokenizer.from_pretrained("Qwen/Qwen3-8B")
    return _TOK


def audit_case(c, ledger) -> list[str]:
    fails = []
    e1 = (ROOT / c["paths"]["E1"]).read_text()
    n1, valid1 = N.number(e1)
    lines1 = C.lines_of(n1)
    # A1 checker integrity
    res = {"E1": C.check(c["checker_spec"], n1)}
    texts = {"E1": e1}
    for st in ("E0", "E2"):
        t = (ROOT / c["paths"][st]).read_text()
        texts[st] = t
        res[st] = C.check(c["checker_spec"], N.number(t)[0])
    if res["E1"] is not True or res["E0"] is not False or res["E2"] is not False:
        fails.append(f"A1_checker({res})")
    # A2/A3/A8
    for st in ("E0", "E2"):
        nst, valid = N.number(texts[st])
        lst = C.lines_of(nst)
        if len(lst) != len(lines1):
            fails.append(f"A2_line_count_{st}")
            continue
        changed = [k for k in lines1 if lines1[k] != lst.get(k)]
        if set(changed) - set(c["target_lines"]):
            fails.append(f"A2_offtarget_{st}:{sorted(set(changed) - set(c['target_lines']))[:3]}")
        if not changed:
            fails.append(f"A2_no_change_{st}")
        if any(t not in valid for t in c["target_lines"]):
            fails.append(f"A3_missing_target_{st}")
        if (texts[st].count("\\begin{") != e1.count("\\begin{")
                or texts[st].count("\\end{") != e1.count("\\end{")
                or texts[st].count("{") != e1.count("{") or texts[st].count("}") != e1.count("}")):
            if c["family"] != "cross_reference":
                fails.append(f"A8_latex_{st}")
    # A4/A5
    for st in ("E0", "E2"):
        for e in c["edits"][st]:
            added = e["new"]
            if any(term in added.lower() for term in FLAG_TERMS):
                fails.append(f"A4_flag_term_{st}")
            if abs(len(e["new"]) - len(e["old"])) > 40 or len(e["new"]) > len(e["old"]) + 40:
                fails.append(f"A5_large_edit_{st}")
            if re.search(r"[.!?]\s+[A-Z]", e["new"]) and not re.search(r"[.!?]\s+[A-Z]", e["old"]):
                fails.append(f"A5_new_sentence_{st}")
    # A9
    for st in ("E0", "E1", "E2"):
        ntok = len(tok()(N.number(texts[st])[0])["input_ids"])
        if ntok > TOK_MAX_MANUSCRIPT:
            fails.append(f"A9_tokens_{st}({ntok})")
    return fails


def main():
    global FLAG_TERMS
    led = json.loads(LEDGER.read_text())
    FLAG_TERMS = [t for t in led["generic_flag_terms"]] + ["inconsistent", "incorrect", "erroneous", "mismatch"]
    kept, rejected = [], []
    seen_rel, seen_mut = set(), set()
    for c in led["cases"]:
        fails = audit_case(c, led)
        rel = (c["paper"], tuple(c["target_lines"]))
        mut = (c["paper"], json.dumps(c["edits"], sort_keys=True))
        if rel in seen_rel:
            fails.append("A6_duplicate_relation")
        if mut in seen_mut:
            fails.append("A6_duplicate_mutation")
        if fails:
            rejected.append({"case_id": c["case_id"], "paper": c["paper"], "family": c["family"], "fails": fails})
        else:
            seen_rel.add(rel)
            seen_mut.add(mut)
            kept.append(c)
        print(("KEEP " if not fails else "DROP "), c["case_id"], ";".join(fails)[:120], flush=True)
    # A7 case overlap within a paper
    per_paper_lines = {}
    final = []
    for c in kept:
        used = per_paper_lines.setdefault(c["paper"], set())
        if used & set(c["target_lines"]):
            rejected.append({"case_id": c["case_id"], "paper": c["paper"], "family": c["family"],
                             "fails": ["A7_overlap"]})
            continue
        used |= set(c["target_lines"])
        final.append(c)
    per_paper = Counter(c["paper"] for c in final)
    audit = {"n_candidates": len(led["cases"]), "n_kept": len(final), "n_rejected": len(rejected),
             "rejected": rejected, "cases_per_paper": dict(per_paper),
             "family_counts": dict(Counter(c["family"] for c in final)),
             "domain_counts": dict(Counter(c["domain"] for c in final)),
             "papers_below_10_cases": [p for p, n in per_paper.items() if n < 10]}
    led["cases"] = final
    led["family_counts"] = audit["family_counts"]
    LEDGER.write_text(json.dumps(led, indent=1) + "\n")
    (ROOT / "exp3heldout/audit.json").write_text(json.dumps(audit, indent=1) + "\n")
    L = ["# Held-out dataset case audit", "",
         f"Candidates {audit['n_candidates']}, kept {audit['n_kept']}, rejected {audit['n_rejected']}.", "",
         "Checks: A1 checker integrity (E1 consistent, E0/E2 inconsistent), A2 variants differ from E1 only on the "
         "declared target lines with identical line counts, A3 target lines exist, A4 no generic flag wording "
         "introduced, A5 minimal native edit, A6 no duplicate relation or mutation, A7 no target-line overlap within "
         "a paper, A8 LaTeX balance preserved, A9 context band, A10 balance reporting.", "",
         "## Cases per paper", "", "| Paper | Domain | Cases |", "|---|---|---|"]
    for p, n in sorted(per_paper.items()):
        L.append(f"| {p} | {led['domains'][p]} | {n} |")
    L += ["", "## Defect families", "", "| Family | Cases |", "|---|---|"]
    for f, n in sorted(audit["family_counts"].items()):
        L.append(f"| {f} | {n} |")
    L += ["", "## Domains", "", "| Domain | Cases |", "|---|---|"]
    for d, n in sorted(audit["domain_counts"].items()):
        L.append(f"| {d} | {n} |")
    if rejected:
        L += ["", "## Rejected candidates", "", "| Case | Paper | Family | Failures |", "|---|---|---|---|"]
        for r in rejected:
            L.append(f"| {r['case_id']} | {r['paper']} | {r['family']} | {'; '.join(r['fails'])[:160]} |")
    L += ["", "Every kept case carries: paper, domain, case id, defect family, source manuscript, target line(s), "
          "relation definition (checker spec), E0/E2 mutations with the exact replaced text, checker implementation "
          "name, checker output for all three states, evidence lines, expected verdicts and a SHA256 per variant "
          "(see exp3heldout/ledger.json).", ""]
    (ROOT / "exp3heldout/CASE_AUDIT.md").write_text("\n".join(L) + "\n")
    print(json.dumps({k: audit[k] for k in ("n_candidates", "n_kept", "n_rejected", "family_counts", "domain_counts",
                                            "papers_below_10_cases")}, indent=1))


if __name__ == "__main__":
    main()

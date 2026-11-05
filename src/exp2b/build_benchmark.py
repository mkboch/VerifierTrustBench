#!/usr/bin/env python3
"""Build and validate the 2B native-edit benchmark.

    python exp2b/build_benchmark.py [--papers 2609.01018 ...]

For every paper module exp2b/cases/p<id>.py: applies each case's E0/E2 edits to exp2b/papers/<id>/E1.tex,
requires every edited `old` string to occur exactly once in its line, no line added or removed, only edited
lines changed, and the deterministic checker to return False/True/False for E0/E1/E2. Also requires blind tokens
to be present in the target lines, target lines to be non-empty, 12 cases per paper, 4 matrix cases with
rationales. Writes exp2b/benchmark/<paper>/<case>/{E0,E2}.tex, exp2b/ledger.json, exp2b/CASE_AUDIT.md,
exp2b/case_audit.csv. Writes nothing if any check fails.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "exp2b"
sys.path.insert(0, str(EXP / "cases"))

STATES = ("E0", "E1", "E2")
TRUTH = {"E0": "ISSUE_PRESENT", "E1": "NO_ISSUE", "E2": "ISSUE_PRESENT"}
ROLE = {"E0": "defective", "E1": "original/repaired", "E2": "reversed/alternate defective"}
FAMILIES = ("arithmetic", "numerical", "cross_reference", "statistical", "claim_evidence", "method_result")

# Carried from 2A-R2 (exp2ar2/cases_spec.py) with additions for LaTeX label references and table statistics.
FAMILY_TERMS = {
    "arithmetic": ["ratio", "fold", "divid", "product", "sum", "add up", "adds up", "total", "arithmetic", "calculat",
                   "comput", "multipl", "formula", "percent", "differen", "equal", "impl", "yield", "correspond",
                   "reduction", "decrease", "increase", "subtract"],
    "numerical": ["inconsisten", "mismatch", "differ", "contradict", "discrepan", "conflict", "not match", "elsewhere",
                  "whereas", "versus", " vs", "but ", "while", "reported as"],
    "cross_reference": ["table", "section", "appendix", "figure", "fig.", "equation", "eq.", "refer", "cite", "point",
                        "label", "numbering", "undefined", "does not exist", "nonexistent", "missing"],
    "statistical": ["interval", "percentile", "range", "bound", "exclude", "include", "outside", "contain", "maximum",
                    "minimum", "max", "min", "exceed", "median", "below", "above", "mean", "average", "standard deviation",
                    "p-value", "p =", "significan", "count", "pairs"],
    "claim_evidence": ["claim", "stat", "contradict", "inconsisten", "not support", "unsupported", "contrary", "opposite",
                       "yet", "but", "however", "actually", "shows", "whereas", "exclude", "include", "above", "below",
                       "less", "more", "best", "lowest", "highest", "monoton"],
    "method_result": ["method", "describ", "stated", "report", "inconsisten", "mismatch", "differ", "contradict",
                      "not match", "whereas", "but", "yet", "list", "generated", "grid", "outside", "only", "caption"],
}
GENERIC_FLAG_TERMS = ["out of place", "stray", "placeholder", "inserted", "injected", "unrelated", "appears odd",
                      "seems odd", "looks odd", "editing artifact", "copy-paste", "copy paste", "does not belong",
                      "suspicious edit", "tampered", "altered text", "edited"]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def as_lines(text: str) -> dict[int, str]:
    return {i + 1: t for i, t in enumerate(text.split("\n"))}


def apply(base: str, edits) -> str:
    rows = base.split("\n")
    for ln, old, new in edits:
        n = rows[ln - 1].count(old)
        if n != 1:
            raise ValueError(f"L{ln}: {old!r} occurs {n} times")
        if old == new:
            raise ValueError(f"L{ln}: no-op edit")
        rows[ln - 1] = rows[ln - 1].replace(old, new)
    return "\n".join(rows)


def load_papers(ids):
    mods = []
    for p in sorted((EXP / "cases").glob("p2*.py")):
        m = importlib.import_module(p.stem)
        if ids and m.PAPER not in ids:
            continue
        mods.append(m)
    return mods


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--papers", nargs="*")
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args()
    mods = load_papers(a.papers)
    errors, built, audit = [], {}, []
    ledger_cases, papers_meta = [], []
    for m in mods:
        pdir = EXP / "papers" / m.PAPER
        base = (pdir / "E1.tex").read_text(encoding="utf-8")
        src = json.loads((pdir / "SOURCE.json").read_text())
        if sha(base.encode()) != src["normalized_sha256"]:
            errors.append(f"{m.PAPER}: E1.tex differs from SOURCE.json hash")
        BL = as_lines(base)
        ids = [c["case_id"] for c in m.CASES]
        if len(ids) != len(set(ids)):
            errors.append(f"{m.PAPER}: duplicate case ids")
        if len(m.CASES) != 12:
            errors.append(f"{m.PAPER}: {len(m.CASES)} cases (expected 12)")
        if len(m.MATRIX) != 4 or any(x not in ids for x in m.MATRIX) or any(x not in m.RATIONALES for x in m.MATRIX):
            errors.append(f"{m.PAPER}: matrix cases/rationales incomplete")
        fam = {}
        for c in m.CASES:
            cid = c["case_id"]
            fam[c["family"]] = fam.get(c["family"], 0) + 1
            if c["family"] not in FAMILIES:
                errors.append(f"{cid}: unknown family")
            try:
                texts = {"E1": base, "E0": apply(base, c["edits"]["E0"]), "E2": apply(base, c["edits"]["E2"])}
            except ValueError as e:
                errors.append(f"{cid}: {e}")
                continue
            for st in ("E0", "E2"):
                SL = as_lines(texts[st])
                if len(SL) != len(BL):
                    errors.append(f"{cid} {st}: line count changed")
                changed = sorted(i for i in SL if SL[i] != BL[i])
                want = sorted({e[0] for e in c["edits"][st]})
                if changed != want:
                    errors.append(f"{cid} {st}: changed {changed} != edited {want}")
                for ln in want:
                    if ln not in c["target_lines"]:
                        errors.append(f"{cid} {st}: edited line {ln} not in target_lines")
            res = {}
            for st in STATES:
                try:
                    res[st] = bool(c["check"](as_lines(texts[st])))
                except Exception as e:
                    errors.append(f"{cid} {st}: checker error {e!r}")
                    res[st] = None
            if res != {"E0": False, "E1": True, "E2": False}:
                errors.append(f"{cid}: checker {res}")
            for ln in c["target_lines"]:
                if not BL.get(ln, "").strip():
                    errors.append(f"{cid}: target line {ln} empty")
            for st in ("E0", "E1"):
                region = "\n".join(as_lines(texts[st])[i] for i in c["target_lines"]).replace("\\%", "%")
                if not any(re.search(p, region, re.I) for p in c["blind_tokens"][st]):
                    errors.append(f"{cid}: no {st} blind token found in target lines")
            built[(m.PAPER, cid)] = texts
            for st in ("E0", "E2"):
                for ln, old, new in c["edits"][st]:
                    audit.append({"paper": m.PAPER, "case_id": cid, "family": c["family"], "state": st, "role": ROLE[st],
                                  "gold": TRUTH[st], "source_file": f"exp2b/papers/{m.PAPER}/E1.tex", "line": ln,
                                  "original_text": old, "mutated_text": new, "relation": c["title"],
                                  "target_lines": " ".join(f"L{t:05d}" for t in c["target_lines"]),
                                  "checker": c["check"].__name__, "checker_E0_E1_E2": f"{res.get('E0')}/{res.get('E1')}/{res.get('E2')}",
                                  "matrix": cid in m.MATRIX, "why_gold_valid": c["gold"]})
            ledger_cases.append({
                "paper": m.PAPER, "case_id": cid, "family": c["family"], "title": c["title"], "question": c["question"],
                "target_lines": c["target_lines"], "location_text": ", ".join(f"L{t:05d}" for t in sorted(c["target_lines"])),
                "edits": {st: [{"line": e[0], "old": e[1], "new": e[2]} for e in c["edits"][st]] for st in ("E0", "E2")},
                "paths": {"E1": f"exp2b/papers/{m.PAPER}/E1.tex", "E0": f"exp2b/benchmark/{m.PAPER}/{cid}/E0.tex",
                          "E2": f"exp2b/benchmark/{m.PAPER}/{cid}/E2.tex"},
                "sha256": {st: sha(texts[st].encode()) for st in STATES} if cid and (m.PAPER, cid) in built else None,
                "truth": TRUTH, "checker": c["check"].__name__, "gold_explanation": c["gold"],
                "blind_tokens": c["blind_tokens"], "matrix": cid in m.MATRIX, "rationales": m.RATIONALES.get(cid)})
        if len(fam) < 4:
            errors.append(f"{m.PAPER}: only {len(fam)} families")
        papers_meta.append({"paper": m.PAPER, "family_counts": fam, "matrix_cases": m.MATRIX, "source": src,
                            "module_sha256": sha((EXP / "cases" / f"p{m.PAPER.replace('.', '_')}.py").read_bytes())})
    if errors:
        print("BUILD FAILED:\n  " + "\n  ".join(errors))
        sys.exit(1)
    print(f"OK: {len(ledger_cases)} cases from {len(mods)} papers")
    for pm in papers_meta:
        print("  ", pm["paper"], pm["family_counts"])
    if a.check_only:
        return
    for (pid, cid), texts in built.items():
        d = EXP / "benchmark" / pid / cid
        d.mkdir(parents=True, exist_ok=True)
        for st in ("E0", "E2"):
            (d / f"{st}.tex").write_text(texts[st], encoding="utf-8")
    total_fam = {}
    for c in ledger_cases:
        total_fam[c["family"]] = total_fam.get(c["family"], 0) + 1
    ledger = {"benchmark": "2B native-edit cross-manuscript", "states": list(STATES), "truth": TRUTH, "roles": ROLE,
              "papers": papers_meta, "family_counts": total_fam, "family_terms": FAMILY_TERMS,
              "generic_flag_terms": GENERIC_FLAG_TERMS, "cases": ledger_cases}
    (EXP / "ledger.json").write_text(json.dumps(ledger, indent=1, ensure_ascii=False) + "\n")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(audit[0]))
    w.writeheader()
    w.writerows(audit)
    (EXP / "case_audit.csv").write_text(buf.getvalue())
    md = ["# Experiment 2B case audit", "",
          "Every case edits text that already exists in the standardised manuscript (`exp2b/papers/<id>/E1.tex`); no line is "
          "added or removed. E1 is the unmodified manuscript. The builder refuses to write the benchmark unless the "
          "deterministic checker returns inconsistent / consistent / inconsistent for E0 / E1 / E2.", "",
          "Family distribution: " + ", ".join(f"{k} {v}" for k, v in sorted(total_fam.items())) + ".", ""]
    for pm in papers_meta:
        md += [f"## Paper {pm['paper']}", "", "Families: " + ", ".join(f"{k} {v}" for k, v in pm["family_counts"].items())
               + f". Matrix cases: {', '.join(pm['matrix_cases'])}.", ""]
        for c in [x for x in ledger_cases if x["paper"] == pm["paper"]]:
            md += [f"### `{c['case_id']}` — {c['title']} ({c['family']})" + (" *(matrix)*" if c["matrix"] else ""), "",
                   f"*Question:* {c['question']}", "", f"*Target lines:* {c['location_text']}; *checker:* `{c['checker']}`", "",
                   "| State | Gold | Line | Original (E1) | Mutation |", "|---|---|---|---|---|"]
            for st in ("E0", "E2"):
                for e in c["edits"][st]:
                    md.append(f"| {st} | {TRUTH[st]} | L{e['line']:05d} | `{e['old'].replace('|', '/')}` | `{e['new'].replace('|', '/')}` |")
            md += ["| E1 | NO_ISSUE | — | unmodified | — |", "", f"*Why gold is mechanical:* {c['gold_explanation']}", ""]
    (EXP / "CASE_AUDIT.md").write_text("\n".join(md) + "\n")
    print("wrote benchmark, ledger.json, CASE_AUDIT.md, case_audit.csv")


if __name__ == "__main__":
    main()

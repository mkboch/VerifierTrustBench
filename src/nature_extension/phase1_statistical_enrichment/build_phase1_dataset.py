#!/usr/bin/env python3
"""Phase 1: build the frozen statistical-enrichment dataset (E0/E1/E2 + ledger).

Reuses the FROZEN Experiment 3 generators (question_for, rationales_for, blind_tokens_for, gold_explanation) and
the FROZEN checkers, so the enrichment cases are scored by exactly the same machinery as Experiment 3.
Experiment 3 artifacts are read-only; this writes only under nature_extension/phase1_statistical_enrichment/.
"""
from __future__ import annotations
import os
import json, shutil, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT / "exp3heldout")); sys.path.insert(0, str(ROOT / "exp2b"))
import build_dataset as B      # frozen generators
import mine_cases as M         # frozen validate()
import checkers as C           # frozen checkers
import normalize as N          # frozen numbering
import prepare_screen as PS    # frozen file reader

SRC = Path(os.environ.get("VTB_SOURCE_DIR", "sources/statistical_enrichment"))
PAPERS = HERE / "papers"
BENCH = HERE / "benchmark"
MINED = HERE / "mined/phase1_mined.json"


def main():
    mined = json.loads(MINED.read_text())["papers"]
    listing = {json.loads(l)["id"]: json.loads(l)
               for l in (HERE / "pool/listing.jsonl").read_text().splitlines() if l.strip()}
    PAPERS.mkdir(exist_ok=True); BENCH.mkdir(exist_ok=True)
    cases_out, papers, domains = [], [], {}
    for pid, rec in sorted(mined.items()):
        files = PS.read_files(SRC / pid)
        mains = [k for k, v in files.items() if "\\documentclass" in v]
        body = files[mains[0]]
        (PAPERS / pid).mkdir(exist_ok=True)
        (PAPERS / pid / "E1.tex").write_text(body)
        numbered, _ = N.number(body)
        lines = C.lines_of(numbered)
        domains[pid] = listing.get(pid, {}).get("domain", "unknown")
        for i, cand in enumerate(rec["cases"], start=1):
            cid = f"s{pid.replace('.', '')[-5:]}_stat_{i:02d}"
            d = BENCH / pid / cid
            d.mkdir(parents=True, exist_ok=True)
            variants = M.validate(cand, body)
            if variants is None:
                print("SKIP (no longer validates):", pid, cid); continue
            paths = {"E1": str((PAPERS / pid / "E1.tex").relative_to(ROOT))}
            shas = {"E1": B.sha(body)}
            for st in ("E0", "E2"):
                p = d / f"{st}.tex"; p.write_text(variants[st])
                paths[st] = str(p.relative_to(ROOT)); shas[st] = B.sha(variants[st])
            checks = {st: C.check(cand["spec"], N.number(variants[st] if st != "E1" else body)[0])
                      for st in ("E0", "E1", "E2")}
            if not (checks["E1"] is True and checks["E0"] is False and checks["E2"] is False):
                print("REJECT (checker integrity):", pid, cid, checks); continue
            cases_out.append({
                "paper": pid, "domain": domains[pid], "case_id": cid, "family": cand["family"],
                "title": f"statistical relation on {cand['anchor'][:60]}",
                "question": B.question_for(cand), "target_lines": cand["target_lines"],
                "location_text": ", ".join(f"L{n:05d}" for n in cand["target_lines"]),
                "edits": cand["edits"], "paths": paths, "sha256": shas,
                "truth": {"E0": "ISSUE_PRESENT", "E1": "NO_ISSUE", "E2": "ISSUE_PRESENT"},
                "checker": cand["spec"]["fn"], "checker_spec": cand["spec"], "checker_results": checks,
                "gold_explanation": B.gold_explanation(cand), "blind_tokens": B.blind_tokens_for(cand),
                "values": cand["values"], "anchor": cand["anchor"], "matrix": False,
                "rationales": B.rationales_for(cand, lines)})
        papers.append(pid)
    old = json.loads((ROOT / "exp2b/ledger.json").read_text())
    ledger = {"benchmark": "VerifierTrustBench Phase 1 statistical-consistency enrichment (follow-up experiment)",
              "note": "FOLLOW-UP. Independent of the frozen Experiment 3 corpus; scored by the same frozen scorers.",
              "states": ["E0", "E1", "E2"],
              "truth": {"E0": "ISSUE_PRESENT", "E1": "NO_ISSUE", "E2": "ISSUE_PRESENT"},
              "roles": {"E0": "defective native edit", "E1": "unmodified manuscript",
                        "E2": "alternate native edit"},
              "papers": papers, "domains": domains,
              "family_counts": dict(Counter(c["family"] for c in cases_out)),
              "checker_counts": dict(Counter(c["checker"] for c in cases_out)),
              "domain_counts": dict(Counter(c["domain"] for c in cases_out)),
              "family_terms": old["family_terms"], "generic_flag_terms": old["generic_flag_terms"],
              "cases": cases_out}
    (HERE / "ledger.json").write_text(json.dumps(ledger, indent=1) + "\n")
    print(json.dumps({"papers": len(papers), "cases": len(cases_out),
                      "by_checker": ledger["checker_counts"], "by_domain": ledger["domain_counts"]}, indent=1))


if __name__ == "__main__":
    main()

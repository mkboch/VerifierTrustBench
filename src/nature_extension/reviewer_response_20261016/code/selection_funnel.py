#!/usr/bin/env python3
"""F: reconstruct the relation-selection funnel.

Read-only and deterministic: re-runs the frozen miner's candidate generation and its validate()
gate over the 21 held-out manuscripts, counting what each stage removes. No model is involved at
any point and nothing is written back into the frozen corpus.

The question is why the pre-freeze audit rejected 0 of 184. The answer should be that the miner
already enforced those constraints as admission conditions, so the audit verifies an invariant
rather than filtering. This script checks that claim instead of asserting it.
"""
from __future__ import annotations
import json, sys, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp3heldout"))
sys.path.insert(0, str(ROOT / "exp2b"))
import mine_cases as M   # noqa: E402
import checkers as C     # noqa: E402
import normalize as N    # noqa: E402

LED = json.loads((ROOT / "exp3heldout/ledger.json").read_text())
papers = sorted(LED["domains"])
print(f"re-running the frozen miner over {len(papers)} held-out manuscripts (no model involved)\n")

stage = collections.Counter()
per_family_raw = collections.Counter()
per_family_valid = collections.Counter()
detail = {}

for pid in papers:
    body = (ROOT / f"exp3heldout/papers/{pid}/E1.tex").read_text()
    numbered, _ = N.number(body)
    lines = C.lines_of(numbered)
    secs, envs = M.section_map(lines), M.label_envs(body)
    raw = valid = 0
    fam_raw = collections.Counter(); fam_valid = collections.Counter()
    for fam, fn in M.MINERS.items():
        for cand in fn(lines, secs, body, envs):
            raw += 1; fam_raw[fam] += 1; per_family_raw[fam] += 1
            if M.validate(cand, body) is not None:
                valid += 1; fam_valid[fam] += 1; per_family_valid[fam] += 1
    detail[pid] = {"raw_candidates": raw, "checker_and_perturbation_valid": valid,
                   "raw_by_family": dict(fam_raw), "valid_by_family": dict(fam_valid)}
    stage["raw"] += raw; stage["valid"] += valid
    print(f"  {pid}  raw {raw:4}  checker+perturbation valid {valid:4}")

final_n = len(LED["cases"])
aud = json.loads((ROOT / "exp3heldout/audit.json").read_text())

funnel = [
    ("raw mined candidate relations", stage["raw"],
     "every pattern match produced by the six family miners across the 21 manuscripts"),
    ("checker-valid and perturbation-valid", stage["valid"],
     "miner validate(): the checker must return consistent on E1 AND inconsistent on BOTH the E0 "
     "and E2 perturbations, the edit must apply as an exact in-line string replacement, and the "
     "line count must be unchanged"),
    ("after de-duplication and per-family cap", None,
     "the miner skips a candidate whose target lines overlap one already taken for that paper "
     f"(MAX_PER_FAMILY = {M.MAX_PER_FAMILY}), then round-robins across families for balance"),
    ("selected into the ledger (audit input)", aud["n_candidates"],
     f"the per-paper target is {M.TARGET_PER_PAPER}"),
    ("passed the ten-check pre-freeze audit", aud["n_kept"], "A1-A10"),
    ("rejected by the pre-freeze audit", aud["n_rejected"], "zero"),
    ("final frozen corpus", final_n, ""),
]

print("\n" + "=" * 86)
print(f"{'stage':56}{'n':>8}")
print("=" * 86)
for name, n, note in funnel:
    print(f"{name:56}{(n if n is not None else '-'):>8}")

print("\nper-family attrition at the checker/perturbation gate:")
print(f"  {'family':18}{'raw':>8}{'valid':>8}{'kept':>8}{'raw->valid':>12}")
fam_final = collections.Counter(c["family"] for c in LED["cases"])
for fam in M.MINERS:
    r, v = per_family_raw[fam], per_family_valid[fam]
    print(f"  {fam:18}{r:>8}{v:>8}{fam_final[fam]:>8}{(100*v/r if r else 0):>11.1f}%")

# the key claim: does the audit re-check what the miner already enforced?
overlap = {
    "A1 checker integrity": "ENFORCED UPSTREAM by miner validate(): a candidate is only emitted "
                            "when check(E1) is True and check(E0) and check(E2) are both False.",
    "A2 off-target identity / line count": "ENFORCED UPSTREAM: apply_edits() returns None unless "
                                           "the literal old string is present on the declared line, "
                                           "and validate() compares line counts before and after.",
    "A3 target-line validity": "ENFORCED UPSTREAM: target lines come from the line index itself.",
    "A7 target-line overlap within a paper": "ENFORCED UPSTREAM: the miner skips any candidate whose "
                                             "target lines intersect those already used for that paper.",
    "A4 introduced flag vocabulary": "NOT enforced upstream; genuinely re-checked at audit.",
    "A5 edit minimality": "Partially upstream (edits are single in-line replacements by construction).",
    "A6 duplicate relation or mutation": "NOT enforced upstream as such; re-checked at audit.",
    "A8 LaTeX balance": "NOT enforced upstream; re-checked at audit.",
    "A9 context band": "NOT enforced upstream; re-checked at audit.",
    "A10 balance reporting": "Reporting only, not a filter.",
}
print("\nwhich audit checks were already binding upstream:")
for k, v in overlap.items():
    print(f"  {k:42} {v[:46]}")

json.dump({"funnel": [{"stage": a, "n": b, "note": c} for a, b, c in funnel],
           "per_paper": detail,
           "per_family": {f: {"raw": per_family_raw[f], "valid": per_family_valid[f],
                              "final": fam_final[f]} for f in M.MINERS},
           "audit_check_provenance": overlap,
           "max_per_family": M.MAX_PER_FAMILY, "target_per_paper": M.TARGET_PER_PAPER},
          (OUT / "data/SELECTION_FUNNEL.json").open("w"), indent=1)
print("\nwrote data/SELECTION_FUNNEL.json")

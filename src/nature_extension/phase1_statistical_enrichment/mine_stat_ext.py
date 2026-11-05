#!/usr/bin/env python3
"""Phase 1: statistical-consistency enrichment miner.

METHODOLOGICAL UPGRADE, NOT A NEW FAMILY. The Experiment 3 statistical miner already contains a
range-containment branch backed by the frozen checker `chk_range`, but its extraction requires the literal token
"range" adjacent to mean/median/average. It therefore never matched the dominant real form of the same relation,
a confidence interval in LaTeX math: `$0.82$ (95\\% CI $0.75$--$0.89$)`. That branch produced ZERO validated
cases in Experiment 3.

This miner extends the EXTRACTION for that same relation and the same frozen checker (`chk_range`, family
`statistical`). No checker is modified, no family is added, no gold rule is changed. Experiment 3 artifacts are
read-only.

Relation admitted: a reported point estimate must lie inside its own reported interval.
  E1 original   : estimate inside interval          -> chk_range True
  E0 defect     : estimate moved outside interval   -> chk_range False
  E2 alt defect : interval moved off the estimate   -> chk_range False   (distinct mutation, same relation)

Usage:  python mine_stat_ext.py [--limit N]
"""
from __future__ import annotations
import argparse, json, re, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "exp3heldout")); sys.path.insert(0, str(ROOT / "exp2b"))
import mine_cases as M      # noqa: E402  frozen helpers
import checkers as CK       # noqa: E402  frozen checkers
import normalize as N       # noqa: E402
OUT = Path(__file__).resolve().parent

NUM = r"\d+(?:\.\d+)?"
# LaTeX-tolerant CI / interval forms. Math delimiters, \%, ~, en-dash and -- are all permitted between tokens.
D = r"[\s$~{}]*"                      # optional LaTeX noise
SEP = r"(?:\s*(?:,|--|-|–|to|and)\s*)"
CI_PATTERNS = [
    # REQUIRE an explicit confidence-interval marker. A bare bracketed pair is NOT admitted: in LaTeX it matches
    # hyperparameter ranges and colour specs (e.g. \cellcolor{gray!8} ... $[1, 25]$), which are not statistical
    # relations. Precision is preferred over yield: an ambiguous statistical "error" must never be manufactured.
    rf"({NUM})[^.\n]{{0,25}}?\(\s*(?:9[05]{D}\\?%{D})?(?:CI|confidence\s+interval){D}[:=]?{D}\[?{D}"
    rf"({NUM}){D}{SEP}{D}({NUM}){D}\]?{D}\)",
    rf"(?:mean|median|average|estimate|accuracy|score)[^.\n]{{0,40}}?({NUM}){D}\(\s*(?:9[05]{D}\\?%{D})?"
    rf"(?:CI|confidence\s+interval){D}[:=]?{D}({NUM}){D}{SEP}{D}({NUM}){D}\)",
    # "95% CI: 0.75 to 0.89 for an estimate of 0.82" (interval stated before the estimate)
    rf"(?:9[05]{D}\\?%{D})?(?:CI|confidence\s+interval){D}[:=]?{D}({NUM}){D}{SEP}{D}({NUM})"
    rf"[^.\n]{{0,40}}?(?:estimate|mean|median|value)[^.\n]{{0,15}}?({NUM})",
]

# Lines carrying these markers are skipped: the numbers in them are layout or hyperparameter values.
SKIP_LINE = re.compile(r"\\cellcolor|\\rowcolor|\\includegraphics|\\hspace|\\vspace|hyper-?parameter|"
                       r"search\s+space|grid\s+search|learning\s+rate", re.I)

def mine_ci(lines) -> list[dict]:
    out = []
    for ln in sorted(lines):
        t = lines[ln]
        if t.count("&") > 3:                      # skip dense table rows: slot uniqueness is unreliable there
            continue
        if SKIP_LINE.search(t):
            continue
        # "CI" is also used for the Close-In propagation model; require a statistical cue on the line
        if not re.search(r"confidence\s+interval|bootstrap|mean|median|estimate|accuracy|interval", t, re.I):
            continue
        for pi, pat in enumerate(CI_PATTERNS):
            hit = False
            for m in re.finditer(pat, t, re.I):
                if pi == 2:
                    lo, hi, v = m.group(1), m.group(2), m.group(3)
                else:
                    v, lo, hi = m.group(1), m.group(2), m.group(3)
                if len(m.group(0)) > 160:          # a span this long has wandered across LaTeX markup
                    continue
                try:
                    fv, flo, fhi = float(v), float(lo), float(hi)
                except ValueError:
                    continue
                if len({v, lo, hi}) != 3 or flo >= fhi:
                    continue
                if not (flo <= fv <= fhi):        # E1 must be CONSISTENT
                    continue
                if (fhi - flo) <= 0:
                    continue
                # Slot regexes must be STABLE under our own edits. slot_regex anchors on surrounding literal
                # text, which for an adjacent triple embeds one slot's value in another slot's anchor: editing the
                # estimate then breaks the lower-bound extractor and the checker returns None. Anchor the interval
                # bounds on the CI marker and the separator instead, which no edit touches.
                rv = M.slot_regex(t, v)
                if rv is None:
                    continue
                mspan = m.group(0)
                ci_at = re.search(r"(?:CI|confidence\s+interval)", mspan, re.I)
                if ci_at is None:
                    continue
                rl = r"(?:CI|confidence\s+interval)[^0-9\n]{0,14}(\d+(?:\.\d+)?)"
                rh = (r"(?:CI|confidence\s+interval)[^0-9\n]{0,14}\d+(?:\.\d+)?"
                      r"[^0-9\n]{0,10}(\d+(?:\.\d+)?)")
                # both must resolve on the ORIGINAL line to the intended bounds
                m_lo, m_hi = re.search(rl, t, re.I), re.search(rh, t, re.I)
                if not (m_lo and m_hi and m_lo.group(1) == lo and m_hi.group(1) == hi):
                    continue
                # E0: move the estimate clearly outside the upper bound
                e0v = M.fmt_like(fhi + max((fhi - flo), abs(fhi) * 0.05 + 0.01), v)
                # E2: move the LOWER bound above the estimate (interval no longer contains it)
                e2v = M.fmt_like(fv + max((fhi - fv) * 0.5 + (fhi - flo) * 0.10, abs(fv) * 0.02 + 0.01), lo)
                if e0v == v or e2v == lo:
                    continue
                try:
                    if float(e2v) >= fhi or float(e2v) <= fv:
                        continue
                except ValueError:
                    continue
                e0 = M.uniq_edit(t, v, e0v)
                e2 = M.uniq_edit(t, lo, e2v)
                if not e0 or not e2:
                    continue
                out.append({"family": "statistical", "line": ln, "target_lines": [ln],
                            "spec": {"fn": "chk_range", "line_val": ln, "re_val": rv, "line_lo": ln, "re_lo": rl,
                                     "line_hi": ln, "re_hi": rh, "tol": 0.0},
                            "edits": {"E0": [{"line": ln, **e0}], "E2": [{"line": ln, **e2}]},
                            "values": {"value": v, "low": lo, "high": hi, "kind": "range_containment",
                                       "e0_value": e0v, "e2_low": e2v},
                            "anchor": M.anchor(t, [v, lo, hi])})
                hit = True
                break
            if hit:
                break
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0); a = ap.parse_args()
    papers = sorted(p.parent.name for p in (ROOT / "exp3heldout/papers").glob("*/E1.tex"))
    if a.limit:
        papers = papers[:a.limit]
    sel = {s["id"] for s in json.loads((ROOT / "exp3heldout/selection.json").read_text())["selected"]}
    found, stats = {}, Counter()
    for pid in papers:
        body = (ROOT / f"exp3heldout/papers/{pid}/E1.tex").read_text()
        numbered, _ = N.number(body)
        lines = CK.lines_of(numbered)
        cands = mine_ci(lines)
        stats["candidates"] += len(cands)
        keep = []
        used_lines = set()
        for c in cands:
            if set(c["target_lines"]) & used_lines:
                continue
            try:
                variants = M.validate(c, body)
            except Exception:
                stats["validate_error"] += 1; continue
            if variants is None:
                stats["validate_failed"] += 1; continue
            used_lines |= set(c["target_lines"])
            keep.append(c); stats["validated"] += 1
        if keep:
            found[pid] = {"in_exp3_cohort": pid in sel, "n": len(keep), "cases": keep}
            stats["papers_with_cases"] += 1
    total = sum(v["n"] for v in found.values())
    summary = {"papers_scanned": len(papers), "papers_with_validated_cases": len(found),
               "validated_statistical_cases": total,
               "from_exp3_cohort_papers": sum(v["n"] for v in found.values() if v["in_exp3_cohort"]),
               "from_new_papers": sum(v["n"] for v in found.values() if not v["in_exp3_cohort"]),
               "counters": dict(stats)}
    (OUT / "MINED_STAT_EXT.json").write_text(json.dumps({"summary": summary, "papers": found}, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

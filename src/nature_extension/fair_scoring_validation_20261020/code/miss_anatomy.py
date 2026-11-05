#!/usr/bin/env python3
"""Section 5: relation-targeted E0 miss anatomy, from existing frozen data.

Every relation-targeted E0 case that the frozen strict scorer did not call TRUE_DETECTION is
classified mechanically into one of four categories, using only the frozen scorer's own
feature flags. No LLM is used as a judge anywhere.

  A_NO_FINDINGS        the response was valid and returned an empty finding list
  B_OFF_TARGET         findings were returned, none of which touched the tested relation
                       either by line (L) or by contradiction-token-and-family text (V and R)
  C_NEAR_MISS          a finding did point at the tested relation, but failed at least one
                       of the strict matcher's three requirements. These are the cases where
                       scorer strictness could plausibly be costing the system credit, so
                       they are exactly the cases routed to human review.
  D_INVALID            the request failed or the response did not satisfy the schema

C is subdivided only to describe which requirement failed; the subdivision is descriptive and
is NOT used to decide anything. Human reviewers, not this script, decide whether a C case
should have counted.
"""
from __future__ import annotations
import csv, json, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fairlib as F  # noqa: E402

OUT = Path(__file__).resolve().parents[1]
RUNG = "RELATION_TARGETED_FINDING_LIST"


def classify(cell):
    """Return (category, subtype) from the frozen scorer's labels and features."""
    if cell.get("e0_status") != "OK":
        return "D_INVALID", cell.get("e0_status") or "MISSING"
    lab = cell.get("e0_label")
    if lab == "TRUE_DETECTION":
        return None, None
    feats = cell.get("e0_feats") or []
    if lab in ("AMBIGUOUS_REVIEW", "PARTIAL_DETECTION"):
        # describe which of L / V / R the best finding was missing
        best = max(feats, key=lambda x: (x["L"], x["V"], x["R"]), default=None)
        if best is None:
            return "C_NEAR_MISS", "unknown"
        missing = [k for k in ("L", "V", "R") if not best[k]]
        return "C_NEAR_MISS", ("cited_relation_but_no_contradiction_token"
                               if missing == ["V"] else
                               "cited_relation_but_wrong_family_vocabulary"
                               if missing == ["R"] else
                               "described_relation_but_cited_no_target_line"
                               if missing == ["L"] else
                               "missing_" + "_and_".join(missing))
    if not feats:
        return "A_NO_FINDINGS", "empty_finding_list"
    return "B_OFF_TARGET", f"{len(feats)}_findings_none_on_target"


def main() -> int:
    f = F.Fair()
    rows = []
    for s in F.OPENWEIGHT + [F.FRONTIER]:
        for c in f.rows(s, RUNG):
            cat, sub = classify(c)
            if cat is None:
                continue
            rows.append({"system": s, "case_id": c["case_id"], "paper": c["paper"],
                         "family": c["family"], "domain": c["domain"],
                         "label": c.get("e0_label"), "category": cat, "subtype": sub,
                         "n_findings": c.get("e0_n_findings", 0)})

    (OUT / "data").mkdir(exist_ok=True)
    with (OUT / "data/RELATION_TARGETED_MISS_ANATOMY.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    def tally(sel, label):
        rs = [r for r in rows if sel(r)]
        n_tot = sum(1 for s in (F.OPENWEIGHT if label == "pooled_openweight" else [F.FRONTIER])
                    for _ in f.rows(s, RUNG))
        c = Counter(r["category"] for r in rs)
        out = {"scope": label, "n_cells": n_tot, "n_misses": len(rs),
               "categories": {k: c.get(k, 0) for k in
                              ("A_NO_FINDINGS", "B_OFF_TARGET", "C_NEAR_MISS", "D_INVALID")},
               "subtypes": dict(Counter(r["subtype"] for r in rs if r["category"] == "C_NEAR_MISS"))}
        out["pct_of_misses"] = {k: (round(100 * v / len(rs), 1) if rs else None)
                                for k, v in out["categories"].items()}
        return out

    summary = {
        "label": "RELATION_TARGETED_E0_MISS_ANATOMY",
        "source": "existing frozen data only; no new inference",
        "scorer": "exp2b.scoring.label_defective, unchanged",
        "llm_judge_used": False,
        "pooled_openweight": tally(lambda r: r["system"] in F.OPENWEIGHT, "pooled_openweight"),
        "gpt_5_2": tally(lambda r: r["system"] == F.FRONTIER, "gpt-5.2"),
        "by_system": {s: dict(Counter(r["category"] for r in rows if r["system"] == s))
                      for s in F.OPENWEIGHT + [F.FRONTIER]},
        "human_review_required": {
            "category": "C_NEAR_MISS",
            "reason": "the response engaged the tested relation but failed a strict matcher "
                      "requirement; only a human can say whether it should have counted",
            "n_pooled_openweight": sum(1 for r in rows if r["category"] == "C_NEAR_MISS"
                                       and r["system"] in F.OPENWEIGHT),
            "n_gpt_5_2": sum(1 for r in rows if r["category"] == "C_NEAR_MISS"
                             and r["system"] == F.FRONTIER),
        },
    }
    (OUT / "data/MISS_ANATOMY.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({k: v for k, v in summary.items()
                      if k in ("pooled_openweight", "gpt_5_2", "human_review_required")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

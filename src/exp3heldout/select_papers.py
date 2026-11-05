#!/usr/bin/env python3
"""Deterministic held-out cohort selection (no model involvement anywhere).

    python exp3heldout/select_papers.py --seed 20260917

Frozen procedure, declared before the selection was run:
  1. eligibility (data-only):
       E1 screen pass (exp3heldout/prepare_screen.py: source, context band, quantitative content, valid LaTeX)
       E2 first posted in the window: v1 date between 2026-06-25 and 2026-09-15 inclusive. The window's intent is
          "announced in the 2026-07..2026-09 listings"; papers submitted in the last days of June and announced in the
          July listing are kept, which is why the lower bound is 2026-06-25 rather than 2026-07-01.
       E3 the miner yields >= MIN_CASES mechanically validated native cases spanning >= MIN_FAMILIES defect families.
          MIN_CASES was set to 8 (not 12) together with a hard per-family cap of 3 in the miner: with a cap of 5 the
          cohort would have been ~45% cross-reference cases, and the cap-3 rule trades a slightly smaller per-paper
          yield for a materially better balance across the six defect families. Both numbers were fixed from the
          mined candidate counts alone, before paper selection and before any verifier inference.
       E4 not an Experiment 2B / ELVAE paper and not a duplicate arXiv id
  2. author independence: candidates are visited in seeded random order; a candidate is skipped if its first author
     or any author already appears in an accepted paper (documented if the rule has to be relaxed to fill a stratum)
  3. stratified sampling: TARGET_PER_DOMAIN papers per domain, drawn in the seeded random order above
  4. if a domain cannot supply its quota, the shortfall is filled round-robin from the domains with the most
     remaining eligible papers, and the deviation is recorded
  5. case-count top-up (declared before any inference): if the stratified cohort holds fewer than MIN_TOTAL_CASES
     mechanically validated cases, further eligible papers are accepted one at a time in the same seeded order,
     preferring the domain with the most remaining eligible papers and capping any domain at MAX_PER_DOMAIN, until the
     corpus reaches MIN_TOTAL_CASES. This adds manuscripts (the generalisation axis) rather than relaxing any quality
     criterion.
No step uses verifier behaviour; the miner never sees a model.
Outputs: exp3heldout/selection.json, exp3heldout/PAPER_CANDIDATE_POOL.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "exp3heldout/pool"
MINED = ROOT / "exp3heldout/mined"
MIN_CASES = 8
MIN_FAMILIES = 3
TARGET_PER_DOMAIN = 4
TARGET_TOTAL = 20
MIN_TOTAL_CASES = 180
MAX_PER_DOMAIN = 6
WINDOW = ("2026-06-25", "2026-09-15")
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
                                      "Dec"], start=1)}


def iso(v1: str | None) -> str | None:
    if not v1:
        return None
    parts = v1.split()
    if len(parts) != 3 or parts[1] not in MONTHS:
        return None
    return f"{parts[2]}-{MONTHS[parts[1]]:02d}-{int(parts[0]):02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260917)
    a = ap.parse_args()
    screen = {json.loads(l)["id"]: json.loads(l) for l in (POOL / "screen.jsonl").read_text().splitlines()}
    rows = []
    for pid, s in screen.items():
        mined_path = MINED / f"{pid}.json"
        mined = json.loads(mined_path.read_text()) if mined_path.exists() else None
        d = iso(s.get("v1_date"))
        reasons = []
        if not s["eligible"]:
            reasons.append(s["reason"])
        if d is None or not (WINDOW[0] <= d <= WINDOW[1]):
            reasons.append(f"outside_window({d})")
        if mined is None:
            reasons.append("not_mined")
        else:
            if mined["n_cases"] < MIN_CASES:
                reasons.append(f"cases={mined['n_cases']}")
            if len(mined["by_family"]) < MIN_FAMILIES:
                reasons.append(f"families={len(mined['by_family'])}")
        rows.append({"id": pid, "domain": s["domain"], "primary": s["primary"], "title": s.get("title"),
                     "v1_date": d, "authors": "; ".join(s.get("authors") or [])[:300],
                     "first_author": (s.get("authors") or [None])[0], "subjects": s.get("subjects"),
                     "source_kind": s.get("source_kind"), "tokens_qwen3_8b": s.get("tokens_qwen3_8b"),
                     "lines": s.get("lines"), "numeric_tabulars": s.get("numeric_tabulars"),
                     "decimals": s.get("decimals"), "percentages": s.get("percentages"), "pvalues": s.get("pvalues"),
                     "resolvable_refs": s.get("resolvable_refs"),
                     "mined_cases": (mined or {}).get("n_cases", 0),
                     "mined_families": len((mined or {}).get("by_family", {})),
                     "mined_by_family": json.dumps((mined or {}).get("by_family", {})),
                     "eligible": not reasons, "exclusion_reason": ";".join(reasons) or ""})
    with (ROOT / "exp3heldout/PAPER_CANDIDATE_POOL.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["domain"], r["id"])))

    eligible = sorted([r for r in rows if r["eligible"]], key=lambda r: r["id"])
    rng = random.Random(a.seed)
    order = list(eligible)
    rng.shuffle(order)
    picked, used_authors, log = [], set(), []
    by_domain = {}
    for r in order:
        dom = r["domain"]
        if len(by_domain.get(dom, [])) >= TARGET_PER_DOMAIN:
            continue
        auth = {x.strip() for x in (r["authors"] or "").split(";") if x.strip()}
        if auth & used_authors:
            log.append({"id": r["id"], "skipped": "author_overlap"})
            continue
        by_domain.setdefault(dom, []).append(r["id"])
        picked.append(r)
        used_authors |= auth
    # shortfall fill (documented deviation)
    if len(picked) < TARGET_TOTAL:
        for r in order:
            if len(picked) >= TARGET_TOTAL:
                break
            if r["id"] in {p["id"] for p in picked}:
                continue
            auth = {x.strip() for x in (r["authors"] or "").split(";") if x.strip()}
            if auth & used_authors:
                continue
            by_domain.setdefault(r["domain"], []).append(r["id"])
            picked.append(r)
            used_authors |= auth
            log.append({"id": r["id"], "added": "shortfall_fill", "domain": r["domain"]})
    # rule 5: case-count top-up
    topup = []
    while sum(r["mined_cases"] for r in picked) < MIN_TOTAL_CASES:
        remaining = {}
        for r in order:
            if r["id"] in {p["id"] for p in picked}:
                continue
            auth = {x.strip() for x in (r["authors"] or "").split(";") if x.strip()}
            if auth & used_authors or len(by_domain.get(r["domain"], [])) >= MAX_PER_DOMAIN:
                continue
            remaining.setdefault(r["domain"], []).append(r)
        if not remaining:
            break
        dom = max(remaining, key=lambda d: (len(remaining[d]), -len(by_domain.get(d, []))))
        r = remaining[dom][0]
        by_domain.setdefault(dom, []).append(r["id"])
        picked.append(r)
        used_authors |= {x.strip() for x in (r["authors"] or "").split(";") if x.strip()}
        topup.append({"id": r["id"], "domain": dom, "cases": r["mined_cases"], "rule": "case_count_topup"})
    log += topup
    sel = {"seed": a.seed, "min_total_cases": MIN_TOTAL_CASES, "max_per_domain": MAX_PER_DOMAIN,
           "topup": topup, "window": WINDOW, "min_cases": MIN_CASES, "min_families": MIN_FAMILIES,
           "target_per_domain": TARGET_PER_DOMAIN, "target_total": TARGET_TOTAL,
           "n_screened": len(rows), "n_eligible": len(eligible),
           "eligible_by_domain": {d: sum(1 for r in eligible if r["domain"] == d)
                                  for d in sorted({r["domain"] for r in eligible})},
           "selected": [{"id": r["id"], "domain": r["domain"], "primary": r["primary"], "title": r["title"],
                         "v1_date": r["v1_date"], "first_author": r["first_author"],
                         "tokens": r["tokens_qwen3_8b"], "cases": r["mined_cases"],
                         "by_family": json.loads(r["mined_by_family"])} for r in
                        sorted(picked, key=lambda r: (r["domain"], r["id"]))],
           "selected_by_domain": {d: sorted(v) for d, v in sorted(by_domain.items())}, "log": log}
    (ROOT / "exp3heldout/selection.json").write_text(json.dumps(sel, indent=1) + "\n")
    print(json.dumps({k: sel[k] for k in ("n_screened", "n_eligible", "eligible_by_domain", "selected_by_domain")},
                     indent=1))
    print("total selected", len(picked), "total cases", sum(r["mined_cases"] for r in picked))


if __name__ == "__main__":
    main()

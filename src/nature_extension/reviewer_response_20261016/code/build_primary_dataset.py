#!/usr/bin/env python3
"""A1b: the same item-level profile dataset for the 5 primary systems over all 184 relations.

The 12-system table has breadth (12 systems) but only 60 relations; this one has depth (184
relations) but only 5 systems. The manuscript's headline numbers and the reviewer's focal
Qwen3.6-vs-Qwen3.8 example both live here, so both tables are analysed.
"""
from __future__ import annotations
import csv, json, sys, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
for p in ("exp3heldout", "exp2b", "exp2br", "exp2bbroad"):
    sys.path.insert(0, str(ROOT / p))
import design_heldout as D, evaluate as EV, scoring as S  # noqa: E402

RUN = ROOT / "runs/exp3heldout_20260918_014959"
plan = D.Plan(); ledger = plan.ledger
cases = {c["case_id"]: c for c in plan.cases}
ev, _ = EV.load(RUN / "evidence_trials.jsonl")
bl, _ = EV.load(RUN / "blind_trials.jsonl")

rows, skipped = [], []
for m in D.PRIMARY:
    for cid, c in cases.items():
        meta = {"system": m, "case_id": cid, "paper": c["paper"], "domain": c["domain"],
                "family": c["family"], "is_primary": 1}
        r = bl.get(f"blind::{m}::{cid}::E0")
        if EV.ok(r):
            _, valid = plan.paper_text(c, "E0")
            lab, _f = S.label_defective(r["result"]["parsed"]["findings"], c, ledger, valid)
            rows.append({**meta, "axis": "blind_E0", "correct": int(lab == "TRUE_DETECTION"), "detail": lab})
        else:
            skipped.append((m, cid, "blind_E0", (r or {}).get("result", {}).get("status", "NOT_RUN")))
        for state, axis in (("E0", "localized_E0"), ("E1", "localized_E1"), ("E2", "localized_E2")):
            r = ev.get(f"evidence::{m}::{cid}::{state}")
            if not EV.ok(r):
                skipped.append((m, cid, axis, (r or {}).get("result", {}).get("status", "NOT_RUN")))
                continue
            parsed = r["result"]["parsed"]
            truth = r.get("truth") or ("NO_ISSUE" if state == "E1" else "ISSUE_PRESENT")
            corr = int(parsed["verdict"] == truth)
            rows.append({**meta, "axis": axis, "correct": corr, "detail": parsed["verdict"]})
            if state == "E0":
                _, valid = plan.paper_text(c, "E0")
                pv = S.provenance(parsed.get("evidence_line_ids") or [],
                                  parsed.get("evidence_line_ids_malformed") or [], valid, c["target_lines"])
                sup = pv.get("target_support") in ("SUPPORTED", "SUPPORTED_ADJACENT")
                rows.append({**meta, "axis": "supported_E0", "correct": int(corr and sup),
                             "detail": f"{parsed['verdict']}|{pv.get('target_support')}"})

path = OUT / "data/PROFILE_5SYSTEM_184_ITEMLEVEL.csv"
with path.open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["system", "case_id", "paper", "domain", "family",
                                       "is_primary", "axis", "correct", "detail"])
    w.writeheader(); w.writerows(rows)

den = collections.Counter((r["system"], r["axis"]) for r in rows)
num = collections.Counter((r["system"], r["axis"]) for r in rows if r["correct"])
AX = ["blind_E0", "localized_E0", "localized_E1", "localized_E2", "supported_E0"]
print(f"wrote {path.name}: {len(rows)} observations, 5 systems, {len(cases)} relations, {len(skipped)} skipped")
print(f"\n{'system':14}" + "".join(f"{a:>16}" for a in AX))
for m in D.PRIMARY:
    line = f"{m:14}"
    for a in AX:
        line += f"{num[(m,a)]:>7}/{den[(m,a)]:<8}"
    print(line)
print(f"\n{'system':14}" + "".join(f"{a:>16}" for a in AX))
for m in D.PRIMARY:
    line = f"{m:14}"
    for a in AX:
        line += f"{100*num[(m,a)]/den[(m,a)]:>14.1f}% " if den[(m, a)] else f"{'na':>15} "
    print(line)
json.dump({"n_observations": len(rows), "n_skipped": len(skipped),
           "skipped_reasons": dict(collections.Counter(s[3] for s in skipped))},
          (OUT / "data/PROFILE_5SYSTEM_184_MANIFEST.json").open("w"), indent=1)

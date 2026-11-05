#!/usr/bin/env python3
"""A1: build the 12-system item-level verification-profile dataset.

Reads ONLY frozen artifacts and reuses the frozen scorers (exp2b/scoring.py via the Experiment 3
evaluator's own imports). Writes one row per system x relation x axis observation.

Axes (chosen to be directly observed and NOT deterministic derivatives of one another):

  blind_E0        strict blind discovery of the perturbed relation (TRUE_DETECTION)
  localized_E0    relation-localized verdict correct on the defective state
  localized_E1    relation-localized verdict correct on the unmodified valid state (specificity)
  localized_E2    relation-localized verdict correct on the independent alternate perturbation
  supported_E0    localized E0 verdict correct AND the citation supports the tested relation

Deliberately excluded as axes: the three-state trajectory (a deterministic AND of the three
localized axes) and the false-alarm rate (1 - localized_E1). Both are reported descriptively
elsewhere but cannot be independent inputs to a model-fit comparison.
"""
from __future__ import annotations
import csv, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp3heldout"))
sys.path.insert(0, str(ROOT / "exp2b"))
sys.path.insert(0, str(ROOT / "exp2br"))
sys.path.insert(0, str(ROOT / "exp2bbroad"))

import design_heldout as D       # noqa: E402
import evaluate as EV            # noqa: E402
import scoring as S              # noqa: E402

RUN = ROOT / "runs/exp3heldout_20260918_014959"
AXES = ["blind_E0", "localized_E0", "localized_E1", "localized_E2", "supported_E0"]


def main() -> int:
    plan = D.Plan()
    ledger = plan.ledger
    cases = {c["case_id"]: c for c in plan.cases}

    ev, _ = EV.load(RUN / "evidence_trials.jsonl")     # 5 primary, 184 cases, E0/E1/E2 targeted
    bl, _ = EV.load(RUN / "blind_trials.jsonl")        # 5 primary, blind
    bf, _ = EV.load(RUN / "broad_family_trials.jsonl") # 7 broad-only, 60-case subset

    # the frozen 60-relation broad replication subset
    subset = sorted({k.split("::")[2] for k in bf})
    assert len(subset) == 60, f"expected the frozen 60-relation subset, got {len(subset)}"

    primary = list(D.PRIMARY)
    broad_only = [m for m in D.BROAD if m not in primary]
    systems = primary + broad_only

    rows, skipped = [], []

    def targeted_record(m, cid, state):
        """The targeted neutral-exposure record, from whichever frozen store holds it."""
        if m in primary:
            return ev.get(f"evidence::{m}::{cid}::{state}")
        return bf.get(f"broad_family::{m}::{cid}::{state}")

    def blind_record(m, cid):
        if m in primary:
            return bl.get(f"blind::{m}::{cid}::E0")
        return bf.get(f"broad_blind::{m}::{cid}::E0") or bf.get(f"broad_family::{m}::{cid}::E0_blind")

    # discover the actual blind key shape used in the broad store
    broad_blind_keys = [k for k in bf if "blind" in k]
    if broad_blind_keys:
        print(f"broad blind key example: {broad_blind_keys[0]}")

    for m in systems:
        for cid in subset:
            c = cases[cid]
            meta = {"system": m, "case_id": cid, "paper": c["paper"], "domain": c["domain"],
                    "family": c["family"],
                    "is_primary": int(m in primary)}

            # ---- blind discovery of E0
            r = blind_record(m, cid)
            if EV.ok(r):
                _, valid = plan.paper_text(c, "E0")
                fnd = r["result"]["parsed"]["findings"]
                lab, _f = S.label_defective(fnd, c, ledger, valid)
                rows.append({**meta, "axis": "blind_E0", "correct": int(lab == "TRUE_DETECTION"),
                             "detail": lab})
            else:
                skipped.append((m, cid, "blind_E0", (r or {}).get("result", {}).get("status", "NOT_RUN")))

            # ---- relation-localized verdicts in each evidence state
            for state, axis in (("E0", "localized_E0"), ("E1", "localized_E1"), ("E2", "localized_E2")):
                r = targeted_record(m, cid, state)
                if not EV.ok(r):
                    skipped.append((m, cid, axis, (r or {}).get("result", {}).get("status", "NOT_RUN")))
                    continue
                parsed = r["result"]["parsed"]
                truth = r.get("truth") or ("NO_ISSUE" if state == "E1" else "ISSUE_PRESENT")
                corr = int(parsed["verdict"] == truth)
                rows.append({**meta, "axis": axis, "correct": corr, "detail": parsed["verdict"]})

                # ---- evidence-supported correctness, defective state only
                if state == "E0":
                    _, valid = plan.paper_text(c, "E0")
                    pv = S.provenance(parsed.get("evidence_line_ids") or [],
                                      parsed.get("evidence_line_ids_malformed") or [],
                                      valid, c["target_lines"])
                    sup = pv.get("target_support") in ("SUPPORTED", "SUPPORTED_ADJACENT")
                    rows.append({**meta, "axis": "supported_E0", "correct": int(corr and sup),
                                 "detail": f"{parsed['verdict']}|{pv.get('target_support')}"})

    path = OUT / "data/PROFILE_12SYSTEM_ITEMLEVEL.csv"
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["system", "case_id", "paper", "domain", "family",
                                           "is_primary", "axis", "correct", "detail"])
        w.writeheader()
        w.writerows(rows)

    # denominators
    import collections
    den = collections.Counter((r["system"], r["axis"]) for r in rows)
    print(f"\nwrote {path.name}: {len(rows)} observations, {len(systems)} systems, {len(subset)} relations")
    print(f"skipped (technically invalid or absent): {len(skipped)}")
    if skipped:
        c = collections.Counter(s[3] for s in skipped)
        print("  reasons:", dict(c))
        c2 = collections.Counter((s[0], s[2]) for s in skipped)
        for k, v in sorted(c2.items())[:15]:
            print(f"   {k[0]:16} {k[1]:14} {v}")

    print("\nper-system denominators by axis:")
    hdr = f"{'system':16}" + "".join(f"{a:>14}" for a in AXES)
    print(hdr)
    for m in systems:
        line = f"{m:16}"
        for a in AXES:
            n = den[(m, a)]
            k = sum(r["correct"] for r in rows if r["system"] == m and r["axis"] == a)
            line += f"{k:>6}/{n:<7}"
        print(line)

    json.dump({"systems": systems, "primary": primary, "broad_only": broad_only,
               "subset_case_ids": subset, "axes": AXES,
               "n_observations": len(rows), "n_skipped": len(skipped),
               "skipped": [{"system": s, "case_id": c, "axis": a, "status": st} for s, c, a, st in skipped]},
              (OUT / "data/PROFILE_12SYSTEM_MANIFEST.json").open("w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""CLI: compute the Verification Evidence Profile from a run directory of trial records.

    python run_profile.py --run-dir runs/exp3heldout_20260918_014959 --out-dir <dir> [--models ...]

Emits profile.json (machine-readable) plus CSV tables. Reads only; never writes into the run directory.
"""
from __future__ import annotations
import argparse, json, sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
for sub in ("exp2b", "exp2br", "exp2bbroad", "exp3heldout"):
    sys.path.insert(0, str(ROOT / sub))

import profile_core as P            # noqa: E402
import design_heldout as D          # noqa: E402
import evaluate as EV               # noqa: E402

KS = (1, 2, 3, 5)                   # schema caps findings at maxItems 5; k=10 is NOT recoverable


def load(p: Path) -> dict:
    out = {}
    if p.exists():
        for line in p.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return out


def ok(r):
    return r is not None and r["result"]["status"] == "OK"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--models", nargs="*")
    a = ap.parse_args()
    rd = Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir
    od = Path(a.out_dir) if Path(a.out_dir).is_absolute() else ROOT / a.out_dir
    od.mkdir(parents=True, exist_ok=True)

    plan = D.Plan()
    ledger = plan.ledger
    cases = {c["case_id"]: c for c in plan.cases}
    ev, bl = load(rd / "evidence_trials.jsonl"), load(rd / "blind_trials.jsonl")
    models = a.models or D.PRIMARY

    out = {"run_dir": str(rd), "models": models, "ks_feasible": list(KS),
           "ks_note": "blind schema caps findings at maxItems 5; Recall/Precision@10 are NOT recoverable "
                      "and are not reported", "by_model": {}}
    disc_rows, vp_rows, resp_rows, prov_rows = [], [], [], []

    for m in models:
        # ---------------- discovery curves (blind E0)
        curves, ranks, nfind, fp_burden = [], [], [], []
        for cid, c in cases.items():
            r = bl.get(f"blind::{m}::{cid}::E0")
            if not ok(r):
                continue
            _, valid = plan.paper_text(c, "E0")
            cur = P.discovery_curve(r["result"]["parsed"]["findings"], c, ledger, valid, KS)
            curves.append(cur)
            nfind.append(cur["n_findings"])
            fp_burden.append(cur["n_findings"] - cur["n_correct_findings"])
            if cur["rank_first_correct"]:
                ranks.append(cur["rank_first_correct"])
            disc_rows.append({"model": m, "case_id": cid, "family": c["family"], "domain": c["domain"],
                              **{k: cur[k] for k in cur if k != "hit_vector"}})
        n = len(curves)
        disc = {"n_cases_scored": n,
                "recall_at": {k: EV.rate(sum(x[f"recall_at_{k}"] for x in curves), n) for k in KS},
                "precision_at": {k: (sum(x[f"precision_at_{k}"] for x in curves) / n if n else None) for k in KS},
                "rank_distribution": dict(Counter(ranks)),
                "median_rank_when_found": (sorted(ranks)[len(ranks) // 2] if ranks else None),
                "findings_per_manuscript": {"mean": (sum(nfind) / n if n else None),
                                            "distribution": dict(Counter(nfind))},
                "false_positive_findings": {"total": sum(fp_burden),
                                            "per_case_mean": (sum(fp_burden) / n if n else None)}}

        # ---------------- responsiveness + false alarms + verdict x provenance
        vp = Counter(); resp = Counter(); e1_ok = e1_n = 0
        cit_prec, spans = [], []
        prov_cls = Counter()
        for cid, c in cases.items():
            v = {}
            for st in P.STATES:
                r = ev.get(f"evidence::{m}::{cid}::{st}")
                if not ok(r):
                    continue
                par = r["result"]["parsed"]
                v[st] = par["verdict"]
                _, valid = plan.paper_text(c, st)
                pd = P.provenance_detail(par.get("evidence_line_ids"), par.get("evidence_line_ids_malformed"),
                                         valid, c["target_lines"])
                prov_cls[pd["status"] if pd["status"] in P.PROV_CLASSES else pd["status"]] += 1
                if pd["citation_precision"] is not None:
                    cit_prec.append(pd["citation_precision"]); spans.append(pd["citation_span"])
                correct = (par["verdict"] == c["truth"][st])
                vp[P.verdict_provenance_cell(correct, pd["status"])] += 1
                if st == "E1":
                    e1_n += 1; e1_ok += int(correct)
                prov_rows.append({"model": m, "case_id": cid, "state": st, "family": c["family"],
                                  "verdict": par["verdict"], "correct": correct, "prov_status": pd["status"],
                                  "n_cited": pd["n_cited"], "n_on_target": pd["n_on_target"],
                                  "citation_precision": pd["citation_precision"], "citation_span": pd["citation_span"]})
            rr = P.responsiveness(v)
            resp[rr["pattern"]] += 1
            for flag in ("MISS_DEFECT", "FALSE_ALARM_ON_REPAIR", "MISS_REVERSAL"):
                resp[flag] += int(rr[flag])
            resp["trajectory"] += int(rr["trajectory"])
            resp["complete"] += int(rr["complete"])
            resp_rows.append({"model": m, "case_id": cid, "family": c["family"], "domain": c["domain"],
                              **{k: rr[k] for k in rr if k != "pattern"}, "pattern": rr["pattern"]})

        tot_vp = sum(vp.values())
        for cell in P.VP_CELLS:
            vp_rows.append({"model": m, "cell": cell, "n": vp[cell],
                            "share": (vp[cell] / tot_vp if tot_vp else None)})

        # ---------------- paired discovery vs localized (same cases)
        a_ok, b_ok = [], []
        for cid, c in cases.items():
            tr = ev.get(f"evidence::{m}::{cid}::E0"); br = bl.get(f"blind::{m}::{cid}::E0")
            if not (ok(tr) and ok(br)):
                continue
            _, valid = plan.paper_text(c, "E0")
            lab, _ = P.S.label_defective(br["result"]["parsed"]["findings"], c, ledger, valid)
            a_ok.append(tr["result"]["parsed"]["verdict"] == c["truth"]["E0"])
            b_ok.append(lab == "TRUE_DETECTION")

        out["by_model"][m] = {
            "information_paths_present": sorted({P.information_path(r) for r in list(ev.values())[:1]} |
                                                {P.BLIND_DISCOVERY}),
            "discovery": disc,
            "responsiveness": {k: resp[k] for k in sorted(resp)},
            "false_alarm_rate": P.false_alarm_rate(e1_ok, e1_n),
            "verdict_x_provenance": {c: vp[c] for c in P.VP_CELLS},
            "provenance_classes": dict(prov_cls),
            "citation_precision_mean": (sum(cit_prec) / len(cit_prec) if cit_prec else None),
            "citation_span_mean": (sum(spans) / len(spans) if spans else None),
            "paired_localized_vs_blind": P.paired(a_ok, b_ok),
        }

    (od / "profile.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
    EV.to_csv(od / "discovery_by_case.csv", disc_rows)
    EV.to_csv(od / "verdict_x_provenance.csv", vp_rows)
    EV.to_csv(od / "responsiveness_by_case.csv", resp_rows)
    EV.to_csv(od / "provenance_by_trial.csv", prov_rows)
    print(json.dumps({m: {"recall@1": out["by_model"][m]["discovery"]["recall_at"][1]["rate"],
                          "recall@5": out["by_model"][m]["discovery"]["recall_at"][5]["rate"],
                          "false_alarm": out["by_model"][m]["false_alarm_rate"]["rate"],
                          "paired_diff": out["by_model"][m]["paired_localized_vs_blind"]["diff"]}
                      for m in models}, indent=1))
    print(f"\nwrote {od}/profile.json and 4 CSVs")


if __name__ == "__main__":
    main()

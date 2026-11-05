#!/usr/bin/env python3
"""Experiment 2B-R evaluator (frozen before repaired blind inference).

    python exp2br/evaluate_br.py --run-dir runs/exp2br_<ts>

Primary blind data: <run_dir>/blind_trials.jsonl (2B-R, bounded schema). Everything else is read, never modified, from the
immutable Experiment 2B run runs/exp2b_20260914_142911: targeted-neutral E0 verdicts (H1 pairing), evidence validity (paper
usability), targeted-text leakage, and the frozen H2/H3 decision outcomes. Blind scoring uses exp2b/scoring.py through the
frozen 2B evaluator (exp2b/evaluate.py) without modification. The original 2B blind results are recomputed only as a
sensitivity comparison.

Decision rules (frozen in exp2br/FROZEN_DESIGN.md):
  R1 blind integrity   every model x paper blind cell (12 defective + 1 clean audit) >= 95% valid, i.e. 13/13;
                       0 unplanned records; every request_sha256 equals the frozen reconstruction.
  R2 usable papers     2B principle: per model, 2B evidence validity >= 95% of 36 trials, 2B-R blind validity >= 95% of the
                       12 E0 audits, and <= 2 clean-control FALSE_POSITIVE relations (2B-R); >= 4 of 5 papers.
  R3 no leakage        2B-R generic foreign-text objections on target lines <= 10% of valid E0 audits; 2B targeted E0-E1
                       vocabulary difference <= 5 points.
  R4 H1                2B rule with 2B-R blind: pooled targeted-only > blind-only, p < 0.05; >= 4 of 5 papers in that
                       direction; every leave-one-paper-out p < 0.05 and in direction; every leave-one-family-out in direction.
  R5 H2, R6 H3         frozen 2B outcomes (H2 holds; H3 POSITIVE), not recomputed.
  READY_FOR_MANUSCRIPT R1-R6 hold.
  PIVOT                R1-R3 hold, R4 fails, R5 or R6 holds.
  STOP                 R1-R3 hold, R4 fails, R5 and R6 fail.
  REVISE_2B            otherwise.
  Sensitivity only (never the decision): pragmatic R1' allowing at most 1 invalid audit per model x paper cell.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2br"))
import protocol_br as PB  # noqa: E402
import client as C  # noqa: E402
import evaluate as EV  # noqa: E402  (frozen 2B evaluator)
import models as M  # noqa: E402
import run_exp2br as RB  # noqa: E402
import scoring as S  # noqa: E402

RUN_2B = ROOT / "runs/exp2b_20260914_142911"


def blind_behaviour(E):
    out = {}
    for m in E.models:
        counts, notes_len, dup, total, generic_any, trunc, n = Counter(), [], 0, 0, 0, 0, 0
        for k, r in E.bl.items():
            if r["model"] != m:
                continue
            n += 1
            if r["result"]["status"] == "TRUNCATED":
                trunc += 1
            if not EV.ok(r):
                continue
            f = r["result"]["parsed"]["findings"]
            counts[len(f)] += 1
            notes_len.append(len(r["result"]["parsed"]["audit_notes"] or ""))
            al = [x["allegation"].strip().lower() for x in f]
            dup += len(al) - len(set(al))
            total += len(al)
            generic_any += sum(any(t in S.normalize_text(x["allegation"]) for t in E.ledger["generic_flag_terms"]) for x in f)
        v = sum(counts.values())
        out[m] = {"audits": n, "valid": v, "truncated": trunc, "zero_findings": EV.rate(counts[0], v),
                  "finding_count_distribution": dict(sorted(counts.items())), "max_findings": max(counts) if counts else None,
                  "mean_findings": round(sum(k * c for k, c in counts.items()) / v, 3) if v else None,
                  "duplicate_allegation_rate": EV.rate(dup, total), "generic_flag_finding_rate": EV.rate(generic_any, total),
                  "audit_notes_chars_max": max(notes_len) if notes_len else None,
                  "audit_notes_at_bound": sum(1 for x in notes_len if x >= PB.BOUNDS["audit_notes"])}
    return out


def build_eval(run_dir: Path, blind_path: Path):
    E = EV.Eval(RUN_2B)                       # loads immutable 2B evidence/matrix/pairs
    E.bl, E.bl_all = EV.load(blind_path)      # replace blind data only
    E.rd = run_dir                            # outputs go to the given directory, never into the 2B run
    return E


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args()
    rd = Path(a.run_dir)
    rd = rd if rd.is_absolute() else ROOT / rd
    meta = json.loads((rd / "RUN_META.json").read_text())
    scope = meta["scope"]
    plan_items = RB.items(scope)
    E = build_eval(rd, rd / "blind_trials.jsonl")
    if scope == "validation":
        ids = set(RB.VALIDATION_IDS)
        E.cases = [c for c in E.cases if f"{c['case_id']}::E0" in ids]
        E.cid = {c["case_id"]: c for c in E.cases}
        E.plan.blind_items = lambda: plan_items  # noqa: E731
    # ---------------- integrity
    planned = {f"blind::{m}::{it['id']}": (m, it) for m in E.models for it in plan_items}
    unplanned = [k for k in E.bl if k not in planned]
    req_mismatch, cells, fails = [], {}, Counter()
    for key, (m, it) in planned.items():
        r = E.bl.get(key)
        cell = cells.setdefault((m, it["paper"]), {"n": 0, "valid": 0, "e0_n": 0, "e0_valid": 0})
        cell["n"] += 1
        cell["e0_n"] += it["kind"] == "defective"
        if r is None:
            fails["NOT_RUN"] += 1
            continue
        want = C.sha256_text(C.canonical(PB.build_blind_br(M.MODELS[m], it["text"], it["seed"])[0]))
        if r["provenance"] and r["provenance"]["request_sha256"] != want:
            req_mismatch.append(key)
        if r["result"]["status"] == "OK":
            cell["valid"] += 1
            cell["e0_valid"] += it["kind"] == "defective"
        else:
            fails[r["result"]["status"]] += 1
    att = Counter(x["status"] for r in E.bl_all for x in r["result"].get("attempts") or [])
    r1_cells = {f"{m}|{p}": c for (m, p), c in cells.items()}
    r1 = all(c["valid"] >= 0.95 * c["n"] for c in cells.values()) and not unplanned and not req_mismatch
    r1_prag = all(c["n"] - c["valid"] <= 1 for c in cells.values())
    # ---------------- blind + H1 via frozen 2B evaluator code
    E.blind()
    E.h1()
    E.leakage()
    behaviour = blind_behaviour(E)
    out = {"run_dir": str(rd), "scope": scope, "design_manifest_sha256": meta["design_manifest_sha256"],
           "integrity": {"requested": len(planned), "valid": sum(c["valid"] for c in cells.values()), "failures": dict(fails),
                         "http_attempts": sum(att.values()), "attempt_statuses": dict(att), "unplanned": unplanned,
                         "request_hash_mismatches": req_mismatch, "cells": r1_cells},
           "blind": E.out["blind"], "h1": E.out["h1"], "behaviour": behaviour}
    # ---------------- sensitivity: original 2B blind
    if scope == "full":
        O = build_eval(rd / "_2b_sensitivity", RUN_2B / "blind_trials.jsonl")
        (rd / "_2b_sensitivity").mkdir(exist_ok=True)
        O.blind(); O.h1()
        out["original_2b"] = {"blind": O.out["blind"], "h1_pooled": O.out["h1"]["by_model"]["POOLED"],
                              "h1_by_model": {m: O.out["h1"]["by_model"][m] for m in O.models}, "behaviour": blind_behaviour(O)}
        # agreement of labels between 2B and 2B-R per (model, case)
        agree = Counter()
        for key, e in E.blind_scored.items():
            o = O.blind_scored.get(key)
            if o and o.get("label") and e.get("label"):
                agree[(o["label"] == "TRUE_DETECTION", e["label"] == "TRUE_DETECTION")] += 1
        out["true_detection_2b_vs_2br"] = {f"2B {a}|2B-R {b}": v for (a, b), v in agree.items()}
    # ---------------- decision
    if scope == "full":
        dec2b = json.loads((RUN_2B / "decision.json").read_text())
        usable, detail = [], {}
        for p in E.papers:
            pc = [c for c in E.cases if c["paper"] == p]
            ev_ok = all(sum(1 for c in pc for s in ("E0", "E1", "E2") if EV.ok(E.ev.get(f"evidence::{m}::{c['case_id']}::{s}"))) >= 0.95 * 36 for m in E.models)
            bl_ok = all(cells[(m, p)]["e0_valid"] >= 0.95 * cells[(m, p)]["e0_n"] for m in E.models)
            fp_ok = all(E.out["blind"][m]["clean_false_positives"].get(p, 0) <= 2 for m in E.models)
            detail[p] = {"evidence_valid_2b": ev_ok, "blind_valid_2br": bl_ok, "clean_fp_ok_2br": fp_ok}
            if ev_ok and bl_ok and fp_ok:
                usable.append(p)
        r2 = len(usable) >= 4
        gx = sum(E.out["blind"][m]["generic_on_target"]["x"] for m in E.models)
        gn = sum(E.out["blind"][m]["generic_on_target"]["n"] for m in E.models)
        r3 = gn > 0 and gx / gn <= 0.10 and dec2b["T3_no_leakage"]["targeted_E0_minus_E1_term_rate"] <= 0.05
        h1 = E.out["h1"]
        pool = h1["by_model"]["POOLED"]
        pooled_ok = pool["first_only"] > pool["second_only"] and pool["mcnemar_p"] < 0.05
        papers_dir = [p for p in E.papers if h1["by_model_paper"][f"POOLED|{p}"]["first_only"] > h1["by_model_paper"][f"POOLED|{p}"]["second_only"]]
        lopo = all(h1["lopo"][f"POOLED|without {p}"]["mcnemar_p"] < 0.05 and h1["lopo"][f"POOLED|without {p}"]["first_only"] > h1["lopo"][f"POOLED|without {p}"]["second_only"] for p in E.papers)
        lofo = all(h1["lofo"][f"POOLED|without {f}"]["first_only"] > h1["lofo"][f"POOLED|without {f}"]["second_only"] for f in E.families)
        r4 = pooled_ok and len(papers_dir) >= 4 and lopo and lofo
        r5 = dec2b["H2"]["holds"]
        r6 = dec2b["H3"] == "POSITIVE"
        if r1 and r2 and r3 and r4 and r5 and r6:
            status = "READY_FOR_MANUSCRIPT"
        elif r1 and r2 and r3 and not r4 and (r5 or r6):
            status = "PIVOT"
        elif r1 and r2 and r3 and not r4 and not r5 and not r6:
            status = "STOP"
        else:
            status = "REVISE_2B"
        out["decision"] = {"status": status, "R1_blind_integrity": r1, "R1_pragmatic_sensitivity": r1_prag,
                           "R2_usable_papers": {"holds": r2, "usable": usable, "detail": detail},
                           "R3_no_leakage": {"holds": r3, "blind_generic_on_target_rate": round(gx / gn, 4) if gn else None},
                           "R4_H1": {"holds": r4, "pooled": pooled_ok, "papers_with_direction": papers_dir, "lopo": lopo, "lofo": lofo},
                           "R5_H2_from_2B": r5, "R6_H3_from_2B": dec2b["H3"]}
        (rd / "decision.json").write_text(json.dumps(out["decision"], indent=1) + "\n")
    (rd / "analysis.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
    rows = [{"model": m, "paper": p, **c} for (m, p), c in cells.items()]
    EV.to_csv(rd / "blind_integrity_cells.csv", rows)
    EV.to_csv(rd / "blind_behaviour.csv", [{"model": m, **{k: (v["rate"] if isinstance(v, dict) and "rate" in v else v) for k, v in b.items()}} for m, b in behaviour.items()])
    write_reports(rd, out, E)
    print("status:", out.get("decision", {}).get("status", "validation scope (no decision)"))


def write_reports(rd, o, E):
    pct = EV.pct
    L = ["# Experiment 2B-R — blind-audit integrity repair: evaluator report", "",
         f"Run `{rd.name}`, scope `{o['scope']}`, design manifest `{o['design_manifest_sha256']}`.",
         "Blind data: this run (bounded schema). Targeted-neutral E0 verdicts, evidence validity, H2 and H3: immutable Experiment 2B "
         "run `runs/exp2b_20260914_142911`. Scorer: frozen `exp2b/scoring.py` via frozen `exp2b/evaluate.py`.", "",
         "## Integrity", "", f"Requested {o['integrity']['requested']}, valid {o['integrity']['valid']}; failures {o['integrity']['failures'] or 'none'}; "
         f"HTTP attempts {o['integrity']['http_attempts']}; unplanned {len(o['integrity']['unplanned'])}; request-hash mismatches {len(o['integrity']['request_hash_mismatches'])}.", "",
         "| Model x paper | Audits | Valid | E0 valid |", "|---|---|---|---|"]
    for k, c in sorted(o["integrity"]["cells"].items()):
        L.append(f"| {k} | {c['n']} | {c['valid']} | {c['e0_valid']}/{c['e0_n']} |")
    L += ["", "## Blind output behaviour", "", "| Model | Valid/audits | Truncated | Zero findings | Count distribution | Max | Mean | Duplicate allegations | Generic-term findings | audit_notes max chars | at bound |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m, b in o["behaviour"].items():
        L.append(f"| {m} | {b['valid']}/{b['audits']} | {b['truncated']} | {pct(b['zero_findings'])} | {b['finding_count_distribution']} | {b['max_findings']} | {b['mean_findings']} | {pct(b['duplicate_allegation_rate'])} | {pct(b['generic_flag_finding_rate'])} | {b['audit_notes_chars_max']} | {b['audit_notes_at_bound']} |")
    L += ["", "## Blind discovery (strict scorer)", "", "| Model | Valid E0 | TRUE | PARTIAL | AMBIGUOUS | MISSED | TRUE sensitivity | TRUE adjacent | Generic on target | Clean FP by paper |", "|---|---|---|---|---|---|---|---|---|---|"]
    for m, b in o["blind"].items():
        lab = b["labels"]
        L.append(f"| {m} | {b['n_valid']} | {pct(b['true_rate'])} | {lab.get('PARTIAL_DETECTION', 0)} | {lab.get('AMBIGUOUS_REVIEW', 0)} | {lab.get('MISSED', 0)} | {pct(b['true_rate_sensitivity'])} | {pct(b['true_rate_adjacent'])} | {pct(b['generic_on_target'])} | {b['clean_false_positives']} |")
    L += ["", "Blind TRUE by paper (labels per model):", ""]
    for m, b in o["blind"].items():
        L.append(f"- {m}: " + "; ".join(f"{p} {v.get('TRUE_DETECTION', 0)}/{sum(v.values())}" for p, v in sorted(b["by_paper"].items())))
    L += ["", "Blind TRUE by family (labels per model):", ""]
    for m, b in o["blind"].items():
        L.append(f"- {m}: " + "; ".join(f"{f} {v.get('TRUE_DETECTION', 0)}/{sum(v.values())}" for f, v in sorted(b["by_family"].items())))
    h1 = o["h1"]
    L += ["", "## H1 — repaired blind vs immutable 2B targeted-neutral E0", "", "| Slice | n | Targeted | Blind TRUE | Targeted only | Blind only | Diff [95% CI] | p |", "|---|---|---|---|---|---|---|---|"]
    for group in ("by_model", "by_model_paper", "by_family", "lopo", "lofo"):
        for k, t in h1[group].items():
            if group != "by_model" and not k.startswith("POOLED"):
                continue
            L.append(f"| {group}:{k} | {t['n']} | {pct(t['targeted_rate'])} | {pct(t['blind_rate'])} | {t['first_only']} | {t['second_only']} | {t['diff']} [{t['ci95'][0]}, {t['ci95'][1]}] | {t['mcnemar_p']} |")
    if "original_2b" in o:
        ob, op = o["original_2b"], o["original_2b"]["h1_pooled"]
        L += ["", "## Sensitivity: original Experiment 2B blind results (unbounded schema)", "",
              f"Pooled H1 in 2B: n={op['n']}, targeted-only {op['first_only']}, blind-only {op['second_only']}, diff {op['diff']} [{op['ci95'][0]}, {op['ci95'][1]}].", "",
              "| Model | 2B blind TRUE | 2B-R blind TRUE | 2B zero-finding | 2B-R zero-finding | 2B clean FP | 2B-R clean FP |", "|---|---|---|---|---|---|---|"]
        for m in o["blind"]:
            L.append(f"| {m} | {pct(ob['blind'][m]['true_rate'])} | {pct(o['blind'][m]['true_rate'])} | {pct(ob['behaviour'][m]['zero_findings'])} | {pct(o['behaviour'][m]['zero_findings'])} | "
                     f"{sum(ob['blind'][m]['clean_false_positives'].values())} | {sum(o['blind'][m]['clean_false_positives'].values())} |")
        L += ["", f"TRUE_DETECTION agreement per (model, case), 2B vs 2B-R: {o['true_detection_2b_vs_2br']}"]
    if "decision" in o:
        L += ["", "## Mechanical decision (frozen 2B-R rules)", "", f"**{o['decision']['status']}**", "", "```json", json.dumps(o["decision"], indent=1), "```"]
    (rd / "REPORT.md").write_text("\n".join(L) + "\n")
    I = ["# Experiment 2B-R integrity report", "", f"Run `{rd.name}`.", "",
         f"- Requested blind audits: {o['integrity']['requested']}", f"- Valid: {o['integrity']['valid']}",
         f"- Failures: {o['integrity']['failures'] or 'none'}", f"- HTTP attempts: {o['integrity']['http_attempts']} ({o['integrity']['attempt_statuses']})",
         f"- Unplanned records: {len(o['integrity']['unplanned'])}", f"- Request-hash mismatches against the frozen reconstruction: {len(o['integrity']['request_hash_mismatches'])}",
         f"- Every model x paper cell >= 95% (13/13): {all(c['valid'] >= 0.95 * c['n'] for c in o['integrity']['cells'].values())}", "",
         "| Model x paper | Audits | Valid | E0 valid |", "|---|---|---|---|"]
    I += [f"| {k} | {c['n']} | {c['valid']} | {c['e0_valid']}/{c['e0_n']} |" for k, c in sorted(o["integrity"]["cells"].items())]
    (rd / "INTEGRITY_REPORT.md").write_text("\n".join(I) + "\n")


if __name__ == "__main__":
    main()

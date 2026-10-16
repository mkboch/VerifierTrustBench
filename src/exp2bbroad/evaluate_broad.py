#!/usr/bin/env python3
"""Experiment 2B-broad evaluator.

    python exp2bbroad/evaluate_broad.py --run-dir runs/exp2bbroad_<ts>

Records: this run's evidence/blind/matrix trials for the newly characterized models, plus the immutable 2B (evidence, matrix)
and 2B-R (blind) records for the four 2B primaries, which are reused and never rerun. All statistics use the frozen scorer
(`exp2b/scoring.py`), the frozen provenance classifier (`exp2br/provenance_audit.classify`) and the helpers of the frozen 2B
evaluator (`exp2b/evaluate.py`). Nothing here reclassifies any model as a competent primary verifier: `competence_class`
comes from the frozen eligibility bakeoff of Experiment 2B-family.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2bbroad"))
import models_broad as MB  # noqa: E402
sys.path.insert(0, str(ROOT / "exp2br"))
import design as D  # noqa: E402
import evaluate as EV  # noqa: E402
import protocol as P  # noqa: E402
import provenance_audit as PA  # noqa: E402
import scoring as S  # noqa: E402

RUN_2B = ROOT / "runs/exp2b_20260914_142911"
RUN_2BR = ROOT / "runs/exp2br_20260914_214259"
STATES = D.STATES
rate, pct, paired_table, to_csv, ok = EV.rate, EV.pct, EV.paired_table, EV.to_csv, EV.ok


def verdict(rec):
    if not rec or rec["result"]["status"] != "OK":
        return None
    return rec["result"]["parsed"]["verdict"]


class BroadEval:
    def __init__(self, rd: Path):
        self.rd = rd
        self.plan = D.Plan("full")
        self.ledger = self.plan.ledger
        self.cases = self.plan.cases()
        self.cid = {c["case_id"]: c for c in self.cases}
        self.papers = sorted({c["paper"] for c in self.cases})
        self.case_families = sorted({c["family"] for c in self.cases})
        new = {k: EV.load(rd / f"{k}_trials.jsonl") for k in ("evidence", "blind", "matrix")}
        old_ev, _ = EV.load(RUN_2B / "evidence_trials.jsonl")
        old_mx, _ = EV.load(RUN_2B / "matrix_trials.jsonl")
        old_bl, _ = EV.load(RUN_2BR / "blind_trials.jsonl")
        self.ev = {**old_ev, **new["evidence"][0]}
        self.mx = {**old_mx, **new["matrix"][0]}
        self.bl = {**old_bl, **new["blind"][0]}
        self.all_new = {k: v[1] for k, v in new.items()}
        self.models = [m for m in MB.ALL_MODELS if any(k.startswith(f"evidence::{m}::") for k in self.ev)]
        self.out = {"run_dir": str(rd), "models": self.models,
                    "model_meta": {m: {"family": MB.MODELS[m]["family"], "params_b": MB.MODELS[m]["params_b"],
                                       "quantization": MB.MODELS[m]["quantization"], "reasoning_mode": MB.MODELS[m]["reasoning_mode"],
                                       "competence_class": MB.COMPETENCE_CLASS[m],
                                       "records": "reused (2B/2B-R, immutable)" if m not in MB.RUN_HERE else "this run"}
                                   for m in self.models},
                    "papers": self.papers}

    # ------------------------------------------------------------------ integrity
    def integrity(self):
        rows, per_paper = [], []
        planned = {"evidence": [f"evidence::{{m}}::{c['case_id']}::{s}" for c in self.cases for s in STATES],
                   "blind": [f"blind::{{m}}::{it['id']}" for it in self.plan.blind_items()],
                   "matrix": [f"matrix::{{m}}::{c['case_id']}::{s}::{a}" for c in self.plan.matrix_cases()
                              for s in ("E0", "E1") for a in P.MATRIX_ARMS]}
        store = {"evidence": self.ev, "blind": self.bl, "matrix": self.mx}
        for m in self.models:
            for phase, keys in planned.items():
                st = Counter()
                for k in keys:
                    r = store[phase].get(k.format(m=m))
                    st[r["result"]["status"] if r else "NOT_RUN"] += 1
                n, v = len(keys), st.get("OK", 0)
                att = Counter(a["status"] for r in self.all_new.get(phase, []) if r.get("model") == m
                              for a in r["result"].get("attempts") or [])
                rows.append({"model": m, "family": MB.MODELS[m]["family"], "phase": phase, "requested": n, "valid": v,
                             "valid_rate": round(v / n, 4), **{f: st.get(f, 0) for f in EV.FAILS},
                             "http_attempts": sum(att.values()) or None,
                             "source": self.out["model_meta"][m]["records"]})
            for p in self.papers:
                pc = [c for c in self.cases if c["paper"] == p]
                evn = sum(ok(self.ev.get(f"evidence::{m}::{c['case_id']}::{s}")) for c in pc for s in STATES)
                bln = sum(ok(self.bl.get(f"blind::{m}::{c['case_id']}::E0")) for c in pc) + ok(self.bl.get(f"blind::{m}::{p}::clean"))
                per_paper.append({"model": m, "paper": p, "evidence_valid": f"{evn}/{3 * len(pc)}",
                                  "blind_valid": f"{bln}/{len(pc) + 1}"})
        self.out["integrity"] = {"cells": rows, "per_paper": per_paper}
        to_csv(self.rd / "integrity.csv", rows)
        to_csv(self.rd / "integrity_by_paper.csv", per_paper)

    # ------------------------------------------------------------------ evidence / H2
    def _ev_verdicts(self, m, c):
        return {s: verdict(self.ev.get(f"evidence::{m}::{c['case_id']}::{s}")) for s in STATES}

    @staticmethod
    def pattern(v):
        if any(v[s] is None for s in STATES):
            return "INCOMPLETE"
        if v["E0"] == "ISSUE_PRESENT" and v["E1"] == "NO_ISSUE" and v["E2"] == "ISSUE_PRESENT":
            return "PASS"
        if all(v[s] == "ISSUE_PRESENT" for s in STATES):
            return "ALWAYS_ISSUE"
        if all(v[s] == "NO_ISSUE" for s in STATES):
            return "ALWAYS_NO_ISSUE"
        if any(v[s] == "UNRESOLVED" for s in STATES):
            return "UNRESOLVED_PRESENT"
        if v["E0"] == "ISSUE_PRESENT" and v["E1"] != "NO_ISSUE":
            return "DETECTS_E0_FAILS_CLEAR_E1"
        if v["E0"] == "ISSUE_PRESENT" and v["E1"] == "NO_ISSUE":
            return "CLEARS_E1_MISSES_E2"
        return "MISSES_E0"

    def evidence_rates(self, models, cases):
        cnt = {s: [0, 0] for s in STATES}
        traj = [0, 0]
        unres = [0, 0]
        fails = [0, 0]
        pats = Counter()
        for m in models:
            for c in cases:
                v = self._ev_verdicts(m, c)
                for s in STATES:
                    fails[1] += 1
                    if v[s] is None:
                        fails[0] += 1
                        continue
                    cnt[s][1] += 1
                    cnt[s][0] += v[s] == c["truth"][s]
                    unres[1] += 1
                    unres[0] += v[s] == "UNRESOLVED"
                p = self.pattern(v)
                pats[p] += 1
                if p != "INCOMPLETE":
                    traj[1] += 1
                    traj[0] += p == "PASS"
        return {"E0_detection": rate(*cnt["E0"]), "E1_clearance": rate(*cnt["E1"]), "E2_detection": rate(*cnt["E2"]),
                "trajectory": rate(*traj), "unresolved_rate": rate(*unres), "failure_rate": rate(*fails), "patterns": dict(pats)}

    def h2(self):
        res = {"by_model": {}, "by_model_paper": {}, "by_model_case_family": {}, "by_family": {}, "by_competence_class": {},
               "by_reasoning_mode": {}}
        rows, traj_rows = [], []
        for m in self.models:
            res["by_model"][m] = self.evidence_rates([m], self.cases)
            for p in self.papers:
                res["by_model_paper"][f"{m}|{p}"] = self.evidence_rates([m], [c for c in self.cases if c["paper"] == p])
            for f in self.case_families:
                res["by_model_case_family"][f"{m}|{f}"] = self.evidence_rates([m], [c for c in self.cases if c["family"] == f])
            v = res["by_model"][m]
            meta = self.out["model_meta"][m]
            rows.append({"model": m, **{k: meta[k] for k in ("family", "params_b", "reasoning_mode", "competence_class")},
                         **{k: v[k]["rate"] for k in ("E0_detection", "E1_clearance", "E2_detection", "trajectory",
                                                      "unresolved_rate", "failure_rate")},
                         "trajectory_ci": v["trajectory"]["ci95"], "patterns": v["patterns"]})
            for c in self.cases:
                vv = self._ev_verdicts(m, c)
                traj_rows.append({"model": m, "family": meta["family"], "paper": c["paper"], "case_id": c["case_id"],
                                  "case_family": c["family"], **vv, "pattern": self.pattern(vv)})
        for key, group in (("by_family", "family"), ("by_competence_class", "competence_class"), ("by_reasoning_mode", "reasoning_mode")):
            buckets = defaultdict(list)
            for m in self.models:
                buckets[self.out["model_meta"][m][group]].append(m)
            for k, ms in buckets.items():
                res[key][k] = {"models": ms, **self.evidence_rates(ms, self.cases)}
        self.out["h2"] = res
        to_csv(self.rd / "h2_by_model.csv", rows)
        to_csv(self.rd / "trajectories.csv", traj_rows)

    # ------------------------------------------------------------------ blind
    def blind(self):
        summary, scored, rows = {}, [], []
        for m in self.models:
            per = {"labels": Counter(), "n": 0, "clean_fp": Counter(), "clean_touched": Counter(), "clean_findings": {},
                   "counts": Counter(), "generic_on_target": 0, "by_paper": defaultdict(Counter), "by_case_family": defaultdict(Counter),
                   "true_cases": []}
            for it in self.plan.blind_items():
                r = self.bl.get(f"blind::{m}::{it['id']}")
                if it["kind"] == "clean":
                    if ok(r):
                        fnd = r["result"]["parsed"]["findings"]
                        per["clean_findings"][it["paper"]] = len(fnd)
                        for c in [x for x in self.cases if x["paper"] == it["paper"]]:
                            lab, _ = S.label_clean(fnd, c, self.ledger, it["valid"])
                            per["clean_fp"][it["paper"]] += lab == "FALSE_POSITIVE"
                            per["clean_touched"][it["paper"]] += lab == "TARGET_TOUCHED"
                    continue
                c = self.cid[it["case_id"]]
                entry = {"model": m, "family": MB.MODELS[m]["family"], "paper": c["paper"], "case_id": c["case_id"],
                         "case_family": c["family"]}
                if ok(r):
                    fnd = r["result"]["parsed"]["findings"]
                    lab, feats = S.label_defective(fnd, c, self.ledger, it["valid"])
                    lab_s, feats_s = S.label_defective(fnd, c, self.ledger, it["valid"], S.SENSITIVITY_TEXT_FIELDS)
                    per["n"] += 1
                    per["labels"][lab] += 1
                    per["counts"][len(fnd)] += 1
                    per["by_paper"][c["paper"]][lab] += 1
                    per["by_case_family"][c["family"]][lab] += 1
                    per["generic_on_target"] += any(x["L"] and x["G"] for x in feats_s)
                    if lab == "TRUE_DETECTION":
                        per["true_cases"].append(c["case_id"])
                    entry.update({"status": "OK", "label": lab, "label_sensitivity": lab_s, "n_findings": len(fnd)})
                else:
                    entry.update({"status": r["result"]["status"] if r else "NOT_RUN", "label": None})
                scored.append(entry)
                rows.append(entry)
            summary[m] = {"n_valid": per["n"], "labels": dict(per["labels"]),
                          "true_rate": rate(per["labels"]["TRUE_DETECTION"], per["n"]),
                          "partial_rate": rate(per["labels"]["PARTIAL_DETECTION"], per["n"]),
                          "missed": per["labels"]["MISSED"], "zero_finding_rate": rate(per["counts"][0], per["n"]),
                          "finding_counts": dict(sorted(per["counts"].items())),
                          "generic_on_target": rate(per["generic_on_target"], per["n"]),
                          "clean_false_positives": dict(per["clean_fp"]), "clean_target_touched": dict(per["clean_touched"]),
                          "clean_findings": per["clean_findings"], "true_cases": per["true_cases"],
                          "by_paper": {p: dict(v) for p, v in per["by_paper"].items()},
                          "by_case_family": {f: dict(v) for f, v in per["by_case_family"].items()}}
        self.out["blind"] = summary
        self.blind_scored = {(e["model"], e["case_id"]): e for e in scored}
        (self.rd / "blind_scored.json").write_text(json.dumps(scored, indent=1) + "\n")
        to_csv(self.rd / "blind_scores.csv", rows)

    # ------------------------------------------------------------------ H1
    def h1_table(self, models, cases):
        pairs = []
        for m in models:
            for c in cases:
                e = self.blind_scored.get((m, c["case_id"]))
                v0 = verdict(self.ev.get(f"evidence::{m}::{c['case_id']}::E0"))
                if not e or e.get("label") is None or v0 is None:
                    continue
                pairs.append((v0 == "ISSUE_PRESENT", e["label"] == "TRUE_DETECTION"))
        t = paired_table(pairs)
        t["targeted_rate"] = rate(t["both"] + t["first_only"], t["n"])
        t["blind_rate"] = rate(t["both"] + t["second_only"], t["n"])
        return t

    def h1(self):
        res = {"by_model": {}, "by_family": {}, "by_competence_class": {}, "by_reasoning_mode": {}, "lopo_by_model": {}}
        rows = []
        for m in self.models:
            t = res["by_model"][m] = self.h1_table([m], self.cases)
            for p in self.papers:
                res["lopo_by_model"][f"{m}|without {p}"] = self.h1_table([m], [c for c in self.cases if c["paper"] != p])
            meta = self.out["model_meta"][m]
            rows.append({"model": m, **{k: meta[k] for k in ("family", "params_b", "reasoning_mode", "competence_class")},
                         "n": t["n"], "targeted_rate": t["targeted_rate"]["rate"], "blind_rate": t["blind_rate"]["rate"],
                         "both": t["both"], "targeted_only": t["first_only"], "blind_only": t["second_only"], "neither": t["neither"],
                         "diff": t["diff"], "ci_lo": t["ci95"][0], "ci_hi": t["ci95"][1], "mcnemar_p": t["mcnemar_p"],
                         "qualitative_H1": t["first_only"] > t["second_only"] and t["mcnemar_p"] < 0.05})
        for key, group in (("by_family", "family"), ("by_competence_class", "competence_class"), ("by_reasoning_mode", "reasoning_mode")):
            buckets = defaultdict(list)
            for m in self.models:
                buckets[self.out["model_meta"][m][group]].append(m)
            for k, ms in buckets.items():
                res[key][k] = {"models": ms, **self.h1_table(ms, self.cases)}
        self.out["h1"] = res
        to_csv(self.rd / "h1_by_model.csv", rows)

    # ------------------------------------------------------------------ matrix: H3 and false priors
    def blocks(self, models, cases=None, states=("E0", "E1")):
        cases = cases if cases is not None else self.plan.matrix_cases()
        for m in models:
            for c in cases:
                for st in states:
                    yield m, c, st, c["truth"][st], {a: self.mx.get(f"matrix::{m}::{c['case_id']}::{st}::{a}") for a in P.MATRIX_ARMS}

    def compare(self, models, arm_a, arm_b, **kw):
        pairs, adopt = [], [0, 0]
        for m, c, st, truth, arms in self.blocks(models, **kw):
            va, vb = verdict(arms[arm_a]), verdict(arms[arm_b])
            if va is None or vb is None:
                continue
            pairs.append((vb == truth, va == truth))
            pv = (arms[arm_b] or {}).get("prior_verdict")
            vn = verdict(arms["neutral"])
            if pv and vn is not None and vn != pv:
                adopt[1] += 1
                adopt[0] += vb == pv
        t = paired_table(pairs)
        t.update({"a": arm_a, "b": arm_b, "helpful": t["first_only"], "harmful": t["second_only"],
                  "unchanged": t["both"] + t["neither"], "adoption_when_neutral_disagreed": rate(*adopt)})
        return t

    def arm_accuracy(self, models, arm):
        x = n = 0
        for m, c, st, truth, arms in self.blocks(models):
            v = verdict(arms[arm])
            if v is not None:
                n += 1
                x += v == truth
        return rate(x, n)

    def matrix(self):
        res = {"by_model": {}, "by_family": {}, "by_competence_class": {}, "by_reasoning_mode": {}}
        rows = []
        def suite(ms):
            return {"neutral_acc": self.arm_accuracy(ms, "neutral"), "location_acc": self.arm_accuracy(ms, "location"),
                    "cv_acc": self.arm_accuracy(ms, "correct_verdict"), "cr_acc": self.arm_accuracy(ms, "correct_rationale"),
                    "fv_acc": self.arm_accuracy(ms, "false_verdict"), "fr_acc": self.arm_accuracy(ms, "false_rationale"),
                    "h3_correct_rationale_vs_correct_verdict": self.compare(ms, "correct_verdict", "correct_rationale"),
                    "correct_verdict_vs_neutral": self.compare(ms, "neutral", "correct_verdict"),
                    "false_verdict_vs_neutral": self.compare(ms, "neutral", "false_verdict"),
                    "false_rationale_vs_false_verdict": self.compare(ms, "false_verdict", "false_rationale"),
                    "false_rationale_vs_neutral": self.compare(ms, "neutral", "false_rationale"),
                    "location_vs_neutral": self.compare(ms, "neutral", "location")}
        for m in self.models:
            res["by_model"][m] = suite([m])
            v = res["by_model"][m]
            meta = self.out["model_meta"][m]
            h3, fv, fr = v["h3_correct_rationale_vs_correct_verdict"], v["false_verdict_vs_neutral"], v["false_rationale_vs_false_verdict"]
            rows.append({"model": m, **{k: meta[k] for k in ("family", "params_b", "reasoning_mode", "competence_class")},
                         "neutral_acc": v["neutral_acc"]["rate"], "cv_acc": v["cv_acc"]["rate"], "cr_acc": v["cr_acc"]["rate"],
                         "fv_acc": v["fv_acc"]["rate"], "fr_acc": v["fr_acc"]["rate"],
                         "h3_helped": h3["helpful"], "h3_harmed": h3["harmful"], "h3_diff": h3["diff"],
                         "h3_ci_lo": h3["ci95"][0], "h3_ci_hi": h3["ci95"][1], "h3_p": h3["mcnemar_p"],
                         "h3_blocks": h3["n"], "false_verdict_harmed": fv["harmful"], "false_verdict_helped": fv["helpful"],
                         "false_verdict_p": fv["mcnemar_p"], "false_verdict_adoption": fv["adoption_when_neutral_disagreed"]["rate"],
                         "false_rationale_vs_fv_harmed": fr["harmful"], "false_rationale_vs_fv_helped": fr["helpful"],
                         "false_rationale_adoption": v["false_rationale_vs_neutral"]["adoption_when_neutral_disagreed"]["rate"]})
        for key, group in (("by_family", "family"), ("by_competence_class", "competence_class"), ("by_reasoning_mode", "reasoning_mode")):
            buckets = defaultdict(list)
            for m in self.models:
                buckets[self.out["model_meta"][m][group]].append(m)
            for k, ms in buckets.items():
                res[key][k] = {"models": ms, **suite(ms)}
        # noise floor: matrix neutral arm replicates the evidence request byte-for-byte
        agree = same = n = 0
        for m, c, st, truth, arms in self.blocks(self.models):
            e = self.ev.get(f"evidence::{m}::{c['case_id']}::{st}")
            if ok(e) and ok(arms["neutral"]):
                n += 1
                agree += verdict(e) == verdict(arms["neutral"])
                same += e["result"]["content"] == arms["neutral"]["result"]["content"]
        res["noise_floor"] = {"verdict_agreement": rate(agree, n), "byte_identical": rate(same, n)}
        res["noise_floor_by_model"] = {}
        for m in self.models:
            a2 = s2 = n2 = 0
            for mm, c, st, truth, arms in self.blocks([m]):
                e = self.ev.get(f"evidence::{m}::{c['case_id']}::{st}")
                if ok(e) and ok(arms["neutral"]):
                    n2 += 1
                    a2 += verdict(e) == verdict(arms["neutral"])
                    s2 += e["result"]["content"] == arms["neutral"]["result"]["content"]
            res["noise_floor_by_model"][m] = {"verdict_agreement": rate(a2, n2), "byte_identical": rate(s2, n2)}
        self.out["matrix"] = res
        to_csv(self.rd / "matrix_by_model.csv", rows)

    # ------------------------------------------------------------------ provenance
    def provenance(self):
        res, rows = {}, []
        for m in self.models:
            trial, by_correct = Counter(), defaultdict(Counter)
            n = corr = corr_grounded = 0
            for c in self.cases:
                for st in STATES:
                    r = self.ev.get(f"evidence::{m}::{c['case_id']}::{st}")
                    if not ok(r):
                        continue
                    p = r["result"]["parsed"]
                    cats, t = PA.classify(p["evidence_line_ids"], p["evidence_line_ids_malformed"], self.plan.paper(c, st)[1], c["target_lines"])
                    n += 1
                    trial[t] += 1
                    good = p["verdict"] == c["truth"][st]
                    by_correct["correct" if good else "incorrect"][t] += 1
                    if good:
                        corr += 1
                        corr_grounded += t in ("GROUNDED", "GROUNDED_VIA_ADJACENT")
            res[m] = {"trials": n, "classes": dict(trial), "by_verdict_correctness": {k: dict(v) for k, v in by_correct.items()},
                      "grounded_rate": rate(trial["GROUNDED"], n), "adjacent_rate": rate(trial["GROUNDED_VIA_ADJACENT"], n),
                      "unrelated_only_rate": rate(trial["UNGROUNDED_VALID_LINES"], n),
                      "invalid_rate": rate(trial["INVALID_ONLY"], n), "no_citation_rate": rate(trial["NO_CITATION"], n),
                      "correct_with_relation_support": rate(corr_grounded, corr)}
            meta = self.out["model_meta"][m]
            rows.append({"model": m, **{k: meta[k] for k in ("family", "competence_class")}, "trials": n,
                         **{k: trial.get(k, 0) for k in ("GROUNDED", "GROUNDED_VIA_ADJACENT", "UNGROUNDED_VALID_LINES", "INVALID_ONLY", "NO_CITATION")},
                         "grounded_rate": res[m]["grounded_rate"]["rate"], "unrelated_only_rate": res[m]["unrelated_only_rate"]["rate"],
                         "correct_with_relation_support": res[m]["correct_with_relation_support"]["rate"]})
        self.out["provenance"] = res
        to_csv(self.rd / "provenance_by_model.csv", rows)

    # ------------------------------------------------------------------ error taxonomy
    def taxonomy(self):
        res, rows = {}, []
        for m in self.models:
            t = Counter()
            n_cases = 0
            for c in self.cases:
                v = self._ev_verdicts(m, c)
                n_cases += 1
                if v["E0"] != "ISSUE_PRESENT":
                    t["MISS_DEFECT"] += 1
                if v["E1"] == "ISSUE_PRESENT":
                    t["FALSE_ALARM_ON_REPAIR"] += 1
                if v["E2"] != "ISSUE_PRESENT":
                    t["MISS_REVERSAL"] += 1
                if all(v[s] == "NO_ISSUE" for s in STATES):
                    t["ALWAYS_NO_ISSUE"] += 1
                if all(v[s] == "ISSUE_PRESENT" for s in STATES):
                    t["ALWAYS_ISSUE"] += 1
            pv = self.out["provenance"][m]
            bl = self.out["blind"][m]
            h2 = self.out["h2"]["by_model"][m]
            shares = {
                "MISS_DEFECT": rate(t["MISS_DEFECT"], n_cases), "FALSE_ALARM_ON_REPAIR": rate(t["FALSE_ALARM_ON_REPAIR"], n_cases),
                "MISS_REVERSAL": rate(t["MISS_REVERSAL"], n_cases), "ALWAYS_NO_ISSUE": rate(t["ALWAYS_NO_ISSUE"], n_cases),
                "ALWAYS_ISSUE": rate(t["ALWAYS_ISSUE"], n_cases), "EXCESS_UNRESOLVED": h2["unresolved_rate"],
                "WRONG_EVIDENCE_BINDING": pv["unrelated_only_rate"], "INVALID_PROVENANCE": pv["invalid_rate"],
                "BLIND_DISCOVERY_FAILURE": rate(bl["n_valid"] - bl["labels"].get("TRUE_DETECTION", 0), bl["n_valid"]),
            }
            dominant = max(("MISS_DEFECT", "FALSE_ALARM_ON_REPAIR", "MISS_REVERSAL", "ALWAYS_NO_ISSUE", "ALWAYS_ISSUE",
                            "EXCESS_UNRESOLVED", "WRONG_EVIDENCE_BINDING", "INVALID_PROVENANCE"),
                           key=lambda k: shares[k]["rate"] or 0)
            res[m] = {"counts": dict(t), "shares": shares, "dominant_error_mode": dominant,
                      "blind_discovery_failure_rate": shares["BLIND_DISCOVERY_FAILURE"]}
            meta = self.out["model_meta"][m]
            rows.append({"model": m, **{k: meta[k] for k in ("family", "competence_class", "reasoning_mode")},
                         **{k: (v["rate"] if isinstance(v, dict) else v) for k, v in shares.items()},
                         "dominant_error_mode": dominant})
        # family-level distribution of dominant modes
        fam = defaultdict(Counter)
        for m in self.models:
            fam[MB.MODELS[m]["family"]][res[m]["dominant_error_mode"]] += 1
        self.out["error_taxonomy"] = {"by_model": res, "dominant_by_family": {k: dict(v) for k, v in fam.items()}}
        to_csv(self.rd / "error_taxonomy.csv", rows)

    def run(self):
        self.integrity()
        self.h2()
        self.blind()
        self.h1()
        self.matrix()
        self.provenance()
        self.taxonomy()
        (self.rd / "analysis.json").write_text(json.dumps(self.out, indent=1, default=str) + "\n")
        return self.out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args()
    rd = Path(a.run_dir)
    rd = rd if rd.is_absolute() else ROOT / rd
    E = BroadEval(rd)
    E.run()
    import report_broad
    report_broad.write(E)
    print(json.dumps({m: {"E0": E.out["h2"]["by_model"][m]["E0_detection"]["rate"],
                          "traj": E.out["h2"]["by_model"][m]["trajectory"]["rate"],
                          "blind_true": E.out["blind"][m]["true_rate"]["rate"],
                          "h1_p": E.out["h1"]["by_model"][m]["mcnemar_p"]} for m in E.models}, indent=1))


if __name__ == "__main__":
    main()

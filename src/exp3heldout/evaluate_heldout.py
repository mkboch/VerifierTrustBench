#!/usr/bin/env python3
"""Experiment 3 held-out evaluator.

    python exp3heldout/evaluate_heldout.py --run-dir runs/exp3heldout_<ts>

Uses the frozen scorers only: exp2b/scoring.py (targeted gold comparison, strict blind labels, provenance classes),
exp2br/provenance_audit.classify and the statistical helpers of exp2b/evaluate.py (Wilson, Newcombe paired CI, exact
McNemar). Hierarchical analysis: GEE logistic regression clustered by manuscript plus a Bayesian mixed GLM with
random intercepts for manuscript and case.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp3heldout"))
import design_heldout as D  # noqa: E402
import models_broad as MB  # noqa: E402
import evaluate as EV  # noqa: E402
import protocol as P  # noqa: E402
import provenance_audit as PA  # noqa: E402
import scoring as S  # noqa: E402

rate, pct, paired_table, to_csv, ok = EV.rate, EV.pct, EV.paired_table, EV.to_csv, EV.ok


def verdict(rec):
    if not rec or rec["result"]["status"] != "OK":
        return None
    return rec["result"]["parsed"]["verdict"]


class HeldoutEval:
    def __init__(self, rd: Path):
        self.rd = rd
        self.plan = D.Plan()
        self.ledger = self.plan.ledger
        self.cases = self.plan.cases
        self.cid = {c["case_id"]: c for c in self.cases}
        self.papers = self.plan.papers
        self.domains = self.plan.domains
        self.dom_list = sorted(set(self.domains.values()))
        self.families = self.plan.families
        self.ev, _ = EV.load(rd / "evidence_trials.jsonl")
        self.bl, _ = EV.load(rd / "blind_trials.jsonl")
        self.mx, _ = EV.load(rd / "matrix_trials.jsonl")
        self.bf, _ = EV.load(rd / "broad_family_trials.jsonl")
        self.models = [m for m in D.PRIMARY if any(k.startswith(f"evidence::{m}::") for k in self.ev)]
        self.broad_models = [m for m in D.BROAD
                             if any(k.startswith(f"broad_family::{m}::") for k in self.bf) or m in self.models]
        self.out = {"run_dir": str(rd), "papers": self.papers, "domains": self.domains,
                    "n_cases": len(self.cases), "primary_models": self.models, "broad_models": self.broad_models,
                    "model_meta": {m: {"family": MB.MODELS[m]["family"], "params_b": MB.MODELS[m]["params_b"],
                                       "competence_class": MB.COMPETENCE_CLASS[m],
                                       "reasoning_mode": MB.MODELS[m]["reasoning_mode"]}
                                   for m in set(self.models) | set(self.broad_models)},
                    "family_counts": self.ledger["family_counts"],
                    "domain_counts": {d: sum(1 for c in self.cases if c["domain"] == d) for d in self.dom_list}}

    # ------------------------------------------------------------------ integrity
    def integrity(self):
        rows, per_paper = [], []
        planned = {
            "evidence": [f"evidence::{{m}}::{c['case_id']}::{s}" for c in self.cases for s in D.STATES],
            "blind": [f"blind::{{m}}::{it['id']}" for it in self.plan.blind_items()],
            "matrix": [f"matrix::{{m}}::{c['case_id']}::{s}::{a}" for c in self.plan.matrix_subset()
                       for s in ("E0", "E1") for a in P.MATRIX_ARMS],
        }
        store = {"evidence": self.ev, "blind": self.bl, "matrix": self.mx}
        for m in self.models:
            for phase, keys in planned.items():
                st = Counter((store[phase][k.format(m=m)]["result"]["status"]
                              if k.format(m=m) in store[phase] else "NOT_RUN") for k in keys)
                n, v = len(keys), st.get("OK", 0)
                rows.append({"model": m, "phase": phase, "requested": n, "valid": v, "valid_rate": round(v / n, 4),
                             **{f: st.get(f, 0) for f in EV.FAILS}})
            for pid in self.papers:
                pc = [c for c in self.cases if c["paper"] == pid]
                evn = sum(ok(self.ev.get(f"evidence::{m}::{c['case_id']}::{s}")) for c in pc for s in D.STATES)
                bln = sum(ok(self.bl.get(f"blind::{m}::{c['case_id']}::E0")) for c in pc)
                cln = sum(ok(self.bl.get(f"blind::{m}::{pid}::clean{k}")) for k in (1, 2))
                per_paper.append({"model": m, "paper": pid, "domain": self.domains[pid],
                                  "evidence_valid": f"{evn}/{3 * len(pc)}", "blind_valid": f"{bln}/{len(pc)}",
                                  "clean_valid": f"{cln}/2"})
        bfkeys = [f"broad_family::{{m}}::{c['case_id']}::{s}" for c in self.plan.broad_subset() for s in D.STATES]
        for m in self.broad_models:
            src = self.bf if m not in self.models else self.ev
            pref = "broad_family" if m not in self.models else "evidence"
            st = Counter()
            for k in bfkeys:
                kk = k.format(m=m).replace("broad_family::", f"{pref}::")
                st[src[kk]["result"]["status"] if kk in src else "NOT_RUN"] += 1
            blsrc = self.bf if m not in self.models else self.bl
            blpref = "broad_blind" if m not in self.models else "blind"   # amendment A3: distinct from targeted keys
            for c in self.plan.broad_subset():
                kk = f"{blpref}::{m}::{c['case_id']}::E0"
                st[blsrc[kk]["result"]["status"] if kk in blsrc else "NOT_RUN"] += 1
            n = len(bfkeys) + len(self.plan.broad_subset())
            rows.append({"model": m, "phase": "broad_family", "requested": n, "valid": st.get("OK", 0),
                         "valid_rate": round(st.get("OK", 0) / n, 4), **{f: st.get(f, 0) for f in EV.FAILS}})
        self.out["integrity"] = {"cells": rows, "per_paper": per_paper}
        to_csv(self.rd / "integrity.csv", rows)
        to_csv(self.rd / "integrity_by_paper.csv", per_paper)

    # ------------------------------------------------------------------ H2 evidence responsiveness
    def _verdicts(self, m, c, store=None):
        src, pref = (self.ev, "evidence") if store is None else (self.bf, "broad_family")
        return {s: verdict(src.get(f"{pref}::{m}::{c['case_id']}::{s}")) for s in D.STATES}

    @staticmethod
    def pattern(v):
        if any(v[s] is None for s in D.STATES):
            return "INCOMPLETE"
        if v["E0"] == "ISSUE_PRESENT" and v["E1"] == "NO_ISSUE" and v["E2"] == "ISSUE_PRESENT":
            return "PASS"
        if all(v[s] == "ISSUE_PRESENT" for s in D.STATES):
            return "ALWAYS_ISSUE"
        if all(v[s] == "NO_ISSUE" for s in D.STATES):
            return "ALWAYS_NO_ISSUE"
        if any(v[s] == "UNRESOLVED" for s in D.STATES):
            return "UNRESOLVED_PRESENT"
        if v["E0"] == "ISSUE_PRESENT" and v["E1"] != "NO_ISSUE":
            return "DETECTS_E0_FAILS_CLEAR_E1"
        if v["E0"] == "ISSUE_PRESENT" and v["E1"] == "NO_ISSUE":
            return "CLEARS_E1_MISSES_E2"
        return "MISSES_E0"

    def rates(self, models, cases, store=None):
        cnt = {s: [0, 0] for s in D.STATES}
        traj, unres, fails, pats = [0, 0], [0, 0], [0, 0], Counter()
        for m in models:
            for c in cases:
                v = self._verdicts(m, c, store)
                for s in D.STATES:
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
                "trajectory": rate(*traj), "unresolved_rate": rate(*unres), "failure_rate": rate(*fails),
                "patterns": dict(pats)}

    def h2(self):
        res = {"by_model": {}, "pooled": self.rates(self.models, self.cases), "by_domain": {}, "by_family": {},
               "by_paper": {}, "by_model_domain": {}}
        rows, traj_rows = [], []
        for m in self.models:
            res["by_model"][m] = self.rates([m], self.cases)
            for d in self.dom_list:
                res["by_model_domain"][f"{m}|{d}"] = self.rates([m], [c for c in self.cases if c["domain"] == d])
            v = res["by_model"][m]
            rows.append({"model": m, **{k: self.out["model_meta"][m][k] for k in ("family", "competence_class")},
                         **{k: v[k]["rate"] for k in ("E0_detection", "E1_clearance", "E2_detection", "trajectory",
                                                      "unresolved_rate", "failure_rate")},
                         "traj_ci": v["trajectory"]["ci95"], "patterns": v["patterns"]})
            for c in self.cases:
                vv = self._verdicts(m, c)
                traj_rows.append({"model": m, "paper": c["paper"], "domain": c["domain"], "case_id": c["case_id"],
                                  "case_family": c["family"], **vv, "pattern": self.pattern(vv)})
        for d in self.dom_list:
            res["by_domain"][d] = self.rates(self.models, [c for c in self.cases if c["domain"] == d])
        for f in self.families:
            res["by_family"][f] = self.rates(self.models, [c for c in self.cases if c["family"] == f])
        for pid in self.papers:
            res["by_paper"][pid] = self.rates(self.models, [c for c in self.cases if c["paper"] == pid])
        self.out["h2"] = res
        to_csv(self.rd / "h2_by_model.csv", rows)
        to_csv(self.rd / "trajectories.csv", traj_rows)

    # ------------------------------------------------------------------ blind discovery
    def blind(self, store="blind", models=None, cases=None, key="blind"):
        models = models or self.models
        cases = cases or self.cases
        src = self.bl if store == "blind" else self.bf
        summary, scored, rows = {}, [], []
        for m in models:
            per = {"labels": Counter(), "n": 0, "counts": Counter(), "clean_fp": Counter(), "clean_touch": Counter(),
                   "generic": 0, "by_domain": defaultdict(Counter), "by_family": defaultdict(Counter),
                   "clean_findings": {}}
            for c in cases:
                r = src.get(f"{key}::{m}::{c['case_id']}::E0")   # amendment A3: `key` distinguishes blind records

                entry = {"model": m, "paper": c["paper"], "domain": c["domain"], "case_id": c["case_id"],
                         "case_family": c["family"], "kind": "defective"}
                if ok(r):
                    _, valid = self.plan.paper_text(c, "E0")
                    fnd = r["result"]["parsed"]["findings"]
                    lab, feats = S.label_defective(fnd, c, self.ledger, valid)
                    lab_s, feats_s = S.label_defective(fnd, c, self.ledger, valid, S.SENSITIVITY_TEXT_FIELDS)
                    per["n"] += 1
                    per["labels"][lab] += 1
                    per["counts"][len(fnd)] += 1
                    per["by_domain"][c["domain"]][lab] += 1
                    per["by_family"][c["family"]][lab] += 1
                    per["generic"] += any(x["L"] and x["G"] for x in feats_s)
                    entry.update({"status": "OK", "label": lab, "label_sensitivity": lab_s, "n_findings": len(fnd)})
                else:
                    entry.update({"status": r["result"]["status"] if r else "NOT_RUN", "label": None})
                scored.append(entry)
                rows.append(entry)
            if store == "blind":
                for pid in self.papers:
                    for k in (1, 2):
                        r = src.get(f"blind::{m}::{pid}::clean{k}")
                        if not ok(r):
                            continue
                        _, valid = self.plan.clean_text(pid)
                        fnd = r["result"]["parsed"]["findings"]
                        per["clean_findings"][f"{pid}#{k}"] = len(fnd)
                        for c in [x for x in self.cases if x["paper"] == pid]:
                            lab, _ = S.label_clean(fnd, c, self.ledger, valid)
                            per["clean_fp"][pid] += lab == "FALSE_POSITIVE"
                            per["clean_touch"][pid] += lab == "TARGET_TOUCHED"
            summary[m] = {"n_valid": per["n"], "labels": dict(per["labels"]),
                          "true_rate": rate(per["labels"]["TRUE_DETECTION"], per["n"]),
                          "partial": per["labels"]["PARTIAL_DETECTION"], "missed": per["labels"]["MISSED"],
                          "zero_finding_rate": rate(per["counts"][0], per["n"]),
                          "finding_counts": dict(sorted(per["counts"].items())),
                          "generic_on_target": rate(per["generic"], per["n"]),
                          "clean_false_positive_relations": dict(per["clean_fp"]),
                          "clean_target_touched": dict(per["clean_touch"]), "clean_findings": per["clean_findings"],
                          "by_domain": {d: dict(v) for d, v in per["by_domain"].items()},
                          "by_family": {f: dict(v) for f, v in per["by_family"].items()}}
        self.out[key] = summary
        d = {(e["model"], e["case_id"]): e for e in scored}
        if store == "blind":
            self.blind_scored = d
            (self.rd / "blind_scored.json").write_text(json.dumps(scored, indent=1) + "\n")
            to_csv(self.rd / "blind_scores.csv", rows)
        else:
            self.broad_blind_scored = d
        return d

    # ------------------------------------------------------------------ H1
    def h1_table(self, models, cases, blind_scored=None, ev_store=None):
        bs = blind_scored if blind_scored is not None else self.blind_scored
        pairs = []
        for m in models:
            for c in cases:
                e = bs.get((m, c["case_id"]))
                v0 = verdict((self.ev if ev_store is None else self.bf).get(
                    f"{'evidence' if ev_store is None else 'broad_family'}::{m}::{c['case_id']}::E0"))
                if not e or e.get("label") is None or v0 is None:
                    continue
                pairs.append((v0 == "ISSUE_PRESENT", e["label"] == "TRUE_DETECTION"))
        t = paired_table(pairs)
        t["targeted_rate"] = rate(t["both"] + t["first_only"], t["n"])
        t["blind_rate"] = rate(t["both"] + t["second_only"], t["n"])
        return t

    def h1(self):
        res = {"pooled": self.h1_table(self.models, self.cases), "by_model": {}, "by_paper": {}, "by_domain": {},
               "by_family": {}, "lopo": {}, "lodo": {}, "lofo": {}, "by_model_domain": {}}
        rows = []
        for m in self.models:
            res["by_model"][m] = self.h1_table([m], self.cases)
            for d in self.dom_list:
                res["by_model_domain"][f"{m}|{d}"] = self.h1_table([m], [c for c in self.cases if c["domain"] == d])
        for pid in self.papers:
            res["by_paper"][pid] = self.h1_table(self.models, [c for c in self.cases if c["paper"] == pid])
            res["lopo"][pid] = self.h1_table(self.models, [c for c in self.cases if c["paper"] != pid])
        for d in self.dom_list:
            res["by_domain"][d] = self.h1_table(self.models, [c for c in self.cases if c["domain"] == d])
            res["lodo"][d] = self.h1_table(self.models, [c for c in self.cases if c["domain"] != d])
        for f in self.families:
            res["by_family"][f] = self.h1_table(self.models, [c for c in self.cases if c["family"] == f])
            res["lofo"][f] = self.h1_table(self.models, [c for c in self.cases if c["family"] != f])
        for group in ("by_model", "by_paper", "by_domain", "by_family", "lopo", "lodo", "lofo"):
            for k, t in res[group].items():
                rows.append({"group": group, "slice": k, "n": t["n"], "targeted": t["targeted_rate"]["rate"],
                             "blind": t["blind_rate"]["rate"], "both": t["both"], "targeted_only": t["first_only"],
                             "blind_only": t["second_only"], "neither": t["neither"], "diff": t["diff"],
                             "ci_lo": t["ci95"][0], "ci_hi": t["ci95"][1], "mcnemar_p": t["mcnemar_p"]})
        t = res["pooled"]
        rows.append({"group": "pooled", "slice": "ALL", "n": t["n"], "targeted": t["targeted_rate"]["rate"],
                     "blind": t["blind_rate"]["rate"], "both": t["both"], "targeted_only": t["first_only"],
                     "blind_only": t["second_only"], "neither": t["neither"], "diff": t["diff"],
                     "ci_lo": t["ci95"][0], "ci_hi": t["ci95"][1], "mcnemar_p": t["mcnemar_p"]})
        self.out["h1"] = res
        to_csv(self.rd / "h1_slices.csv", rows)

    # ------------------------------------------------------------------ matrix: H3 and false priors
    def blocks(self, models, cases=None, states=("E0", "E1")):
        cases = cases if cases is not None else self.plan.matrix_subset()
        for m in models:
            for c in cases:
                for st in states:
                    yield m, c, st, c["truth"][st], {a: self.mx.get(f"matrix::{m}::{c['case_id']}::{st}::{a}")
                                                     for a in P.MATRIX_ARMS}

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

    def arm_acc(self, models, arm, **kw):
        x = n = 0
        for m, c, st, truth, arms in self.blocks(models, **kw):
            v = verdict(arms[arm])
            if v is not None:
                n += 1
                x += v == truth
        return rate(x, n)

    def matrix(self):
        sub = self.plan.matrix_subset()
        doms = sorted({c["domain"] for c in sub})
        fams = sorted({c["family"] for c in sub})

        def suite(models, **kw):
            return {"neutral_acc": self.arm_acc(models, "neutral", **kw),
                    "location_acc": self.arm_acc(models, "location", **kw),
                    "cv_acc": self.arm_acc(models, "correct_verdict", **kw),
                    "cr_acc": self.arm_acc(models, "correct_rationale", **kw),
                    "fv_acc": self.arm_acc(models, "false_verdict", **kw),
                    "fr_acc": self.arm_acc(models, "false_rationale", **kw),
                    "h3": self.compare(models, "correct_verdict", "correct_rationale", **kw),
                    "cv_vs_neutral": self.compare(models, "neutral", "correct_verdict", **kw),
                    "false_verdict_vs_neutral": self.compare(models, "neutral", "false_verdict", **kw),
                    "false_rationale_vs_false_verdict": self.compare(models, "false_verdict", "false_rationale", **kw),
                    "false_rationale_vs_neutral": self.compare(models, "neutral", "false_rationale", **kw),
                    "location_vs_neutral": self.compare(models, "neutral", "location", **kw)}

        res = {"pooled": suite(self.models), "by_model": {m: suite([m]) for m in self.models},
               "by_domain": {d: suite(self.models, cases=[c for c in sub if c["domain"] == d]) for d in doms},
               "by_family": {f: suite(self.models, cases=[c for c in sub if c["family"] == f]) for f in fams},
               "lopo_h3": {pid: self.compare(self.models, "correct_verdict", "correct_rationale",
                                             cases=[c for c in sub if c["paper"] != pid]) for pid in self.papers},
               "subset_cases": [c["case_id"] for c in sub],
               "subset_family_counts": dict(Counter(c["family"] for c in sub)),
               "subset_domain_counts": dict(Counter(c["domain"] for c in sub))}
        agree = same = n = 0
        for m, c, st, truth, arms in self.blocks(self.models):
            e = self.ev.get(f"evidence::{m}::{c['case_id']}::{st}")
            if ok(e) and ok(arms["neutral"]):
                n += 1
                agree += verdict(e) == verdict(arms["neutral"])
                same += e["result"]["content"] == arms["neutral"]["result"]["content"]
        res["noise_floor"] = {"verdict_agreement": rate(agree, n), "byte_identical": rate(same, n)}
        rows = []
        for m in self.models:
            v = res["by_model"][m]
            h3, fv, fr = v["h3"], v["false_verdict_vs_neutral"], v["false_rationale_vs_false_verdict"]
            rows.append({"model": m, "competence_class": self.out["model_meta"][m]["competence_class"],
                         "neutral_acc": v["neutral_acc"]["rate"], "cv_acc": v["cv_acc"]["rate"],
                         "cr_acc": v["cr_acc"]["rate"], "fv_acc": v["fv_acc"]["rate"], "fr_acc": v["fr_acc"]["rate"],
                         "h3_helped": h3["helpful"], "h3_harmed": h3["harmful"], "h3_diff": h3["diff"],
                         "h3_ci_lo": h3["ci95"][0], "h3_ci_hi": h3["ci95"][1], "h3_p": h3["mcnemar_p"],
                         "h3_blocks": h3["n"], "fv_harmed": fv["harmful"], "fv_helped": fv["helpful"],
                         "fv_p": fv["mcnemar_p"], "fv_adoption": fv["adoption_when_neutral_disagreed"]["rate"],
                         "fr_vs_fv_harmed": fr["harmful"], "fr_vs_fv_helped": fr["helpful"],
                         "fr_adoption": v["false_rationale_vs_neutral"]["adoption_when_neutral_disagreed"]["rate"]})
        self.out["matrix"] = res
        to_csv(self.rd / "matrix_by_model.csv", rows)

    # ------------------------------------------------------------------ provenance and taxonomy
    def provenance(self):
        res, rows = {}, []
        for m in self.models:
            trial, by_corr = Counter(), defaultdict(Counter)
            n = corr = corr_g = 0
            for c in self.cases:
                for st in D.STATES:
                    r = self.ev.get(f"evidence::{m}::{c['case_id']}::{st}")
                    if not ok(r):
                        continue
                    p = r["result"]["parsed"]
                    _, valid = self.plan.paper_text(c, st)
                    _, t = PA.classify(p["evidence_line_ids"], p["evidence_line_ids_malformed"], valid,
                                       c["target_lines"])
                    n += 1
                    trial[t] += 1
                    good = p["verdict"] == c["truth"][st]
                    by_corr["correct" if good else "incorrect"][t] += 1
                    if good:
                        corr += 1
                        corr_g += t in ("GROUNDED", "GROUNDED_VIA_ADJACENT")
            res[m] = {"trials": n, "classes": dict(trial),
                      "by_verdict_correctness": {k: dict(v) for k, v in by_corr.items()},
                      "grounded_rate": rate(trial["GROUNDED"], n),
                      "adjacent_rate": rate(trial["GROUNDED_VIA_ADJACENT"], n),
                      "unrelated_only_rate": rate(trial["UNGROUNDED_VALID_LINES"], n),
                      "invalid_rate": rate(trial["INVALID_ONLY"], n), "no_citation_rate": rate(trial["NO_CITATION"], n),
                      "correct_with_relation_support": rate(corr_g, corr)}
            rows.append({"model": m, "trials": n,
                         **{k: trial.get(k, 0) for k in ("GROUNDED", "GROUNDED_VIA_ADJACENT",
                                                          "UNGROUNDED_VALID_LINES", "INVALID_ONLY", "NO_CITATION")},
                         "grounded_rate": res[m]["grounded_rate"]["rate"],
                         "unrelated_only_rate": res[m]["unrelated_only_rate"]["rate"],
                         "correct_with_relation_support": res[m]["correct_with_relation_support"]["rate"]})
        self.out["provenance"] = res
        to_csv(self.rd / "provenance_by_model.csv", rows)

    def taxonomy(self):
        res, rows = {}, []
        for m in self.models:
            t, n_cases = Counter(), 0
            for c in self.cases:
                v = self._verdicts(m, c)
                n_cases += 1
                if v["E0"] != "ISSUE_PRESENT":
                    t["MISS_DEFECT"] += 1
                if v["E1"] == "ISSUE_PRESENT":
                    t["FALSE_ALARM_ON_REPAIR"] += 1
                if v["E2"] != "ISSUE_PRESENT":
                    t["MISS_REVERSAL"] += 1
                if all(v[s] == "NO_ISSUE" for s in D.STATES):
                    t["ALWAYS_NO_ISSUE"] += 1
                if all(v[s] == "ISSUE_PRESENT" for s in D.STATES):
                    t["ALWAYS_ISSUE"] += 1
            pv, bl, h2 = self.out["provenance"][m], self.out["blind"][m], self.out["h2"]["by_model"][m]
            shares = {"MISS_DEFECT": rate(t["MISS_DEFECT"], n_cases),
                      "FALSE_ALARM_ON_REPAIR": rate(t["FALSE_ALARM_ON_REPAIR"], n_cases),
                      "MISS_REVERSAL": rate(t["MISS_REVERSAL"], n_cases),
                      "ALWAYS_NO_ISSUE": rate(t["ALWAYS_NO_ISSUE"], n_cases),
                      "ALWAYS_ISSUE": rate(t["ALWAYS_ISSUE"], n_cases),
                      "EXCESS_UNRESOLVED": h2["unresolved_rate"],
                      "WRONG_EVIDENCE_BINDING": pv["unrelated_only_rate"], "INVALID_PROVENANCE": pv["invalid_rate"],
                      "BLIND_DISCOVERY_FAILURE": rate(bl["n_valid"] - bl["labels"].get("TRUE_DETECTION", 0),
                                                      bl["n_valid"])}
            dominant = max(("MISS_DEFECT", "FALSE_ALARM_ON_REPAIR", "MISS_REVERSAL", "ALWAYS_NO_ISSUE",
                            "ALWAYS_ISSUE", "EXCESS_UNRESOLVED", "WRONG_EVIDENCE_BINDING", "INVALID_PROVENANCE"),
                           key=lambda k: shares[k]["rate"] or 0)
            res[m] = {"counts": dict(t), "shares": shares, "dominant_error_mode": dominant}
            rows.append({"model": m, **{k: (v["rate"] if isinstance(v, dict) else v) for k, v in shares.items()},
                         "dominant_error_mode": dominant})
        by_dom = {}
        for d in self.dom_list:
            cs = [c for c in self.cases if c["domain"] == d]
            miss_rev = sum(1 for m in self.models for c in cs if self._verdicts(m, c)["E2"] != "ISSUE_PRESENT")
            by_dom[d] = rate(miss_rev, len(cs) * len(self.models))
        self.out["error_taxonomy"] = {"by_model": res, "miss_reversal_by_domain": by_dom}
        to_csv(self.rd / "error_taxonomy.csv", rows)

    # ------------------------------------------------------------------ hierarchical analysis
    def hierarchical(self):
        import numpy as np
        import pandas as pd
        import statsmodels.api as sm
        import statsmodels.formula.api as smf
        recs = []
        for m in self.models:
            for c in self.cases:
                e = self.blind_scored.get((m, c["case_id"]))
                v0 = verdict(self.ev.get(f"evidence::{m}::{c['case_id']}::E0"))
                if not e or e.get("label") is None or v0 is None:
                    continue
                for cond, y in (("targeted", int(v0 == "ISSUE_PRESENT")),
                                ("blind", int(e["label"] == "TRUE_DETECTION"))):
                    recs.append({"y": y, "blind": int(cond == "blind"), "model": m, "paper": c["paper"],
                                 "domain": c["domain"], "family": c["family"], "case": c["case_id"],
                                 "competence": self.out["model_meta"][m]["competence_class"]})
        df = pd.DataFrame(recs)
        df.to_csv(self.rd / "hierarchical_data.csv", index=False)
        out = {"n_observations": int(len(df)), "n_cases": int(df["case"].nunique()),
               "n_papers": int(df["paper"].nunique()), "n_models": int(df["model"].nunique())}
        try:  # GEE logistic, exchangeable working correlation, clustered by manuscript
            gee = smf.gee("y ~ blind + C(model) + C(family) + C(domain)", groups="paper", data=df,
                          family=sm.families.Binomial(), cov_struct=sm.cov_struct.Exchangeable()).fit()
            out["gee_cluster_paper"] = {
                "formula": "y ~ blind + C(model) + C(family) + C(domain), groups=paper, exchangeable",
                "blind_coef": float(gee.params["blind"]), "blind_se": float(gee.bse["blind"]),
                "blind_z": float(gee.tvalues["blind"]), "blind_p": float(gee.pvalues["blind"]),
                "blind_odds_ratio": float(np.exp(gee.params["blind"])),
                "blind_or_ci95": [float(np.exp(gee.conf_int().loc["blind", 0])),
                                  float(np.exp(gee.conf_int().loc["blind", 1]))],
                "n_clusters": int(df["paper"].nunique())}
        except Exception as e:  # noqa: BLE001
            out["gee_cluster_paper"] = {"error": repr(e)[:300]}
        try:  # Bayesian mixed GLM: random intercepts for manuscript and case-within-manuscript
            vc = {"paper": "0 + C(paper)", "case": "0 + C(case)"}
            mod = sm.BinomialBayesMixedGLM.from_formula("y ~ blind + C(model)", vc, df)
            fit = mod.fit_vb(verbose=False)
            names = list(fit.model.exog_names)
            i = names.index("blind")
            out["bayes_mixed_glm"] = {
                "formula": "y ~ blind + C(model), random intercepts: paper, case",
                "blind_posterior_mean": float(fit.fe_mean[i]), "blind_posterior_sd": float(fit.fe_sd[i]),
                "blind_odds_ratio": float(np.exp(fit.fe_mean[i])),
                "blind_or_ci95": [float(np.exp(fit.fe_mean[i] - 1.96 * fit.fe_sd[i])),
                                  float(np.exp(fit.fe_mean[i] + 1.96 * fit.fe_sd[i]))],
                "random_effect_sd": {k: float(v) for k, v in zip(vc, fit.vcp_mean)}}
        except Exception as e:  # noqa: BLE001
            out["bayes_mixed_glm"] = {"error": repr(e)[:300]}
        try:  # H3 hierarchical: correct rationale vs correct verdict on the matrix subset
            rec3 = []
            for m, c, st, truth, arms in self.blocks(self.models):
                for arm in ("correct_verdict", "correct_rationale"):
                    v = verdict(arms[arm])
                    if v is None:
                        continue
                    rec3.append({"y": int(v == truth), "rationale": int(arm == "correct_rationale"), "model": m,
                                 "paper": c["paper"], "case": c["case_id"], "state": st})
            d3 = pd.DataFrame(rec3)
            d3.to_csv(self.rd / "hierarchical_h3_data.csv", index=False)
            g3 = smf.gee("y ~ rationale + C(model)", groups="paper", data=d3, family=sm.families.Binomial(),
                         cov_struct=sm.cov_struct.Exchangeable()).fit()
            out["h3_gee_cluster_paper"] = {"rationale_coef": float(g3.params["rationale"]),
                                           "rationale_se": float(g3.bse["rationale"]),
                                           "rationale_p": float(g3.pvalues["rationale"]),
                                           "rationale_odds_ratio": float(np.exp(g3.params["rationale"])),
                                           "n_observations": int(len(d3))}
        except Exception as e:  # noqa: BLE001
            out["h3_gee_cluster_paper"] = {"error": repr(e)[:300]}
        self.out["hierarchical"] = out

    # ------------------------------------------------------------------ broad-family held-out subset
    def broad_family(self):
        sub = self.plan.broad_subset()
        ids = {c["case_id"] for c in sub}
        cases = [c for c in self.cases if c["case_id"] in ids]
        bs = self.blind(store="broad_family", models=[m for m in self.broad_models if m not in self.models],
                        cases=cases, key="broad_blind")
        merged = dict(bs)
        for m in self.models:                      # primary models already have these audits in the main blind phase
            for c in cases:
                if (m, c["case_id"]) in self.blind_scored:
                    merged[(m, c["case_id"])] = self.blind_scored[(m, c["case_id"])]
        res, rows = {}, []
        for m in self.broad_models:
            store = None if m in self.models else "broad_family"
            h2 = self.rates([m], cases, store=store)
            h1 = self.h1_table([m], cases, blind_scored=merged, ev_store=None if m in self.models else "broad")
            blind_sum = (self.out["blind"] if m in self.models else self.out["broad_blind"]).get(m, {})
            trial = Counter()
            corr = corr_g = 0
            for c in cases:
                for st in D.STATES:
                    src = self.ev if m in self.models else self.bf
                    pref = "evidence" if m in self.models else "broad_family"
                    r = src.get(f"{pref}::{m}::{c['case_id']}::{st}")
                    if not ok(r):
                        continue
                    p = r["result"]["parsed"]
                    _, valid = self.plan.paper_text(c, st)
                    _, tcl = PA.classify(p["evidence_line_ids"], p["evidence_line_ids_malformed"], valid,
                                         c["target_lines"])
                    trial[tcl] += 1
                    if p["verdict"] == c["truth"][st]:
                        corr += 1
                        corr_g += tcl in ("GROUNDED", "GROUNDED_VIA_ADJACENT")
            miss_rev = sum(1 for c in cases if self._verdicts(m, c, store)["E2"] != "ISSUE_PRESENT")
            res[m] = {"h2": h2, "h1": h1, "blind_true_rate": blind_sum.get("true_rate"),
                      "provenance_classes": dict(trial),
                      "correct_with_relation_support": rate(corr_g, corr),
                      "miss_reversal_rate": rate(miss_rev, len(cases))}
            meta = self.out["model_meta"][m]
            rows.append({"model": m, "family": meta["family"], "params_b": meta["params_b"],
                         "competence_class": meta["competence_class"], "reasoning_mode": meta["reasoning_mode"],
                         "E0": h2["E0_detection"]["rate"], "E1": h2["E1_clearance"]["rate"],
                         "E2": h2["E2_detection"]["rate"], "trajectory": h2["trajectory"]["rate"],
                         "blind_true": (blind_sum.get("true_rate") or {}).get("rate"),
                         "h1_targeted_only": h1["first_only"], "h1_blind_only": h1["second_only"],
                         "h1_diff": h1["diff"], "h1_p": h1["mcnemar_p"],
                         "correct_with_relation_support": res[m]["correct_with_relation_support"]["rate"],
                         "miss_reversal_rate": res[m]["miss_reversal_rate"]["rate"]})
        self.out["broad_family"] = {"subset_cases": sorted(ids), "n_cases": len(cases), "by_model": res,
                                    "subset_family_counts": dict(Counter(c["family"] for c in cases)),
                                    "subset_domain_counts": dict(Counter(c["domain"] for c in cases))}
        to_csv(self.rd / "broad_family_by_model.csv", rows)

    # ------------------------------------------------------------------ leakage audit
    def leakage(self):
        terms = self.ledger["generic_flag_terms"]
        cnt = defaultdict(lambda: [0, 0])
        for r in self.ev.values():
            if not ok(r):
                continue
            p = r["result"]["parsed"]
            txt = " ".join(str(p.get(x) or "") for x in ("analysis", "brief_reason", "evidence_summary")).lower()
            k = (r["model"], r["state"])
            cnt[k][1] += 1
            cnt[k][0] += any(w in txt for w in terms)
        gx = sum(self.out["blind"][m]["generic_on_target"]["x"] for m in self.models)
        gn = sum(self.out["blind"][m]["generic_on_target"]["n"] for m in self.models)
        self.out["leakage"] = {"targeted_generic_terms": {f"{m}|{s}": rate(*v) for (m, s), v in cnt.items()},
                               "blind_generic_on_target": rate(gx, gn)}

    def run(self):
        self.integrity()
        self.h2()
        self.blind()
        self.h1()
        self.matrix()
        self.provenance()
        self.taxonomy()
        self.broad_family()
        self.leakage()
        self.hierarchical()
        (self.rd / "analysis.json").write_text(json.dumps(self.out, indent=1, default=str) + "\n")
        return self.out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args()
    rd = Path(a.run_dir)
    rd = rd if rd.is_absolute() else ROOT / rd
    E = HeldoutEval(rd)
    E.run()
    import report_heldout
    report_heldout.write(E)
    t = E.out["h1"]["pooled"]
    print(json.dumps({"H1_pooled": {"targeted_only": t["first_only"], "blind_only": t["second_only"],
                                    "diff": t["diff"], "p": t["mcnemar_p"]},
                      "H2_pooled_trajectory": E.out["h2"]["pooled"]["trajectory"]["rate"]}, indent=1))


if __name__ == "__main__":
    main()

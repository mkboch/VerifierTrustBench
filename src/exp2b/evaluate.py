#!/usr/bin/env python3
"""Experiment 2B pre-registered evaluator.

    python exp2b/evaluate.py --run-dir runs/exp2b_<ts>

Reads *_trials.jsonl (latest record per key; every attempt for integrity), applies exp2b/scoring.py and the frozen
decision rules (DECISION in exp2b/decision_rules.py), and writes REPORT.md, INTEGRITY_REPORT.md, analysis.json,
decision.json, blind_scored.json, ambiguous_review.jsonl and CSV tables. Primary statistics use the five new papers
only; the ELVAE anchor is reported separately.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "exp2b"
sys.path.insert(0, str(EXP))
import decision_rules as DR  # noqa: E402
import design as D  # noqa: E402
import normalize as N  # noqa: E402
import protocol as P  # noqa: E402
import scoring as S  # noqa: E402

ORD = {"ISSUE_PRESENT": 2, "UNRESOLVED": 1, "NO_ISSUE": 0}
FAILS = ("HTTP_FAILED", "EMPTY_CONTENT", "TRUNCATED", "PARSE_FAILED", "INVALID_SCHEMA", "SOURCE_FAILED", "NOT_RUN")


# --------------------------------------------------------------------------- statistics

def binom_two_sided(k: int, n: int) -> float:
    if n == 0:
        return 1.0
    k = min(k, n - k)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def wilson(x: int, n: int, z: float = 1.959964):
    if n == 0:
        return None, None
    p = x / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(c - h, 4), round(c + h, 4)


def rate(x: int, n: int) -> dict:
    lo, hi = wilson(x, n)
    return {"x": x, "n": n, "rate": round(x / n, 4) if n else None, "ci95": [lo, hi]}


def paired_diff_ci(a: int, b: int, c: int, d: int, z: float = 1.959964):
    """Newcombe (1998, method 10) 95% CI for p1 - p2 from a paired 2x2 table.
    a = both positive, b = first only, c = second only, d = neither. Returns (diff, lo, hi)."""
    n = a + b + c + d
    if n == 0:
        return None, None, None
    p1, p2 = (a + b) / n, (a + c) / n
    l1, u1 = wilson(a + b, n, z)
    l2, u2 = wilson(a + c, n, z)
    phi = 0.0
    denom = math.sqrt((a + b) * (c + d) * (a + c) * (b + d))
    if denom > 0:
        num = a * d - b * c
        if num > 0:
            num = max(num - n / 2, 0.0)
        phi = num / denom
    diff = p1 - p2
    dl = math.sqrt(max(0.0, (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2))
    du = math.sqrt(max(0.0, (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2))
    return round(diff, 4), round(diff - dl, 4), round(diff + du, 4)


def pct(r: dict) -> str:
    if not r or not r["n"]:
        return "n/a"
    return f"{100 * r['rate']:.1f}% ({r['x']}/{r['n']})"


def to_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys)
    w.writeheader()
    for r in rows:
        w.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()})
    path.write_text(buf.getvalue())


def load(path: Path):
    latest, allrecs = {}, []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                allrecs.append(r)
                latest[r["key"]] = r
    return latest, allrecs


def verdict(rec):
    if not rec or rec["result"]["status"] != "OK":
        return None
    return rec["result"]["parsed"]["verdict"]


def ok(rec):
    return bool(rec) and rec["result"]["status"] == "OK"


def paired_table(pairs):
    """pairs: iterable of (x: bool, y: bool). Returns counts and test/CI for P(x) - P(y)."""
    a = b = c = d = 0
    for x, y in pairs:
        a += x and y
        b += x and not y
        c += y and not x
        d += (not x) and (not y)
    diff, lo, hi = paired_diff_ci(a, b, c, d)
    return {"n": a + b + c + d, "both": a, "first_only": b, "second_only": c, "neither": d,
            "mcnemar_p": round(binom_two_sided(c, b + c), 6), "diff": diff, "ci95": [lo, hi]}


# --------------------------------------------------------------------------- evaluator

class Eval:
    def __init__(self, rd: Path):
        self.rd = rd
        meta = json.loads((rd / "RUN_META.json").read_text())
        self.scope = meta["scope"]
        self.plan = D.Plan(self.scope)
        self.ledger = self.plan.ledger
        self.models = list(D.PRIMARY)
        self.cases = self.plan.cases()
        self.cid = {c["case_id"]: c for c in self.cases}
        self.papers = sorted({c["paper"] for c in self.cases})
        self.families = sorted({c["family"] for c in self.cases})
        self.ev, self.ev_all = load(rd / "evidence_trials.jsonl")
        self.mx, self.mx_all = load(rd / "matrix_trials.jsonl")
        self.pr, self.pr_all = load(rd / "pair_trials.jsonl")
        self.bl, self.bl_all = load(rd / "blind_trials.jsonl")
        self.an, self.an_all = load(rd / "anchor_trials.jsonl")
        self.dev = json.loads((EXP / "dev/capability_groups.json").read_text())
        self.out: dict = {"run_dir": str(rd), "scope": self.scope, "design_manifest_sha256": meta["design_manifest_sha256"],
                          "primary_models": self.models, "papers": self.papers, "capability_groups": self.dev}

    # ---------------- plan & integrity
    def planned(self):
        plan = {k: defaultdict(set) for k in ("evidence", "matrix", "blind", "pair", "anchor")}
        for m in self.models:
            for c in self.cases:
                for st in D.STATES:
                    plan["evidence"][m].add(f"evidence::{m}::{c['case_id']}::{st}")
            for c in self.plan.matrix_cases():
                for st in ("E0", "E1"):
                    for arm in P.MATRIX_ARMS:
                        plan["matrix"][m].add(f"matrix::{m}::{c['case_id']}::{st}::{arm}")
            for it in self.plan.blind_items():
                plan["blind"][m].add(f"blind::{m}::{it['id']}")
            for c in self.plan.anchor_cases():
                for st in D.STATES:
                    plan["anchor"][m].add(f"anchor::{m}::{c['case_id']}::{st}")
                plan["anchor"][m].add(f"anchorblind::{m}::{c['case_id']}::E0")
        for ph in D.PAIRS:
            for src, tgt, cat in self.plan.pairs(ph):
                for c in self.plan.pair_cases():
                    for st in ("E0", "E1"):
                        for arm in P.PAIR_ARMS:
                            plan["pair"][tgt].add(f"pair::{src}->{tgt}::{c['case_id']}::{st}::{arm}")
        return plan

    def integrity(self):
        plan = self.planned()
        files = {"evidence": (self.ev, self.ev_all), "matrix": (self.mx, self.mx_all), "blind": (self.bl, self.bl_all),
                 "pair": (self.pr, self.pr_all), "anchor": (self.an, self.an_all)}
        rows, unplanned = [], []
        for exp, (latest, allrecs) in files.items():
            allplanned = set().union(*plan[exp].values()) if plan[exp] else set()
            unplanned += [k for k in latest if k not in allplanned]
            for m in self.models:
                keys = plan[exp].get(m, set())
                if not keys:
                    continue
                st = Counter()
                prov = Counter()
                support = Counter()
                warn = Counter()
                for k in keys:
                    r = latest.get(k)
                    if r is None:
                        st["NOT_RUN"] += 1
                        continue
                    s = r["result"]["status"]
                    st[s] += 1
                    if s != "OK":
                        continue
                    pc = r["result"].get("provenance_check")
                    if isinstance(pc, dict):
                        prov[pc["status"]] += 1
                        if "target_support" in pc:
                            support[pc["target_support"]] += 1
                    elif isinstance(pc, list):
                        for x in pc:
                            prov["finding_" + x["status"]] += 1
                    for w in r["result"].get("schema_warnings") or []:
                        warn[w.split(":")[0]] += 1
                att = Counter(a["status"] for r in allrecs if r["key"] in keys for a in r["result"].get("attempts") or [])
                n, v = len(keys), st.get("OK", 0)
                rows.append({"experiment": exp, "model": m, "requested": n, "valid": v, "failed": n - v,
                             "valid_rate": round(v / n, 4), **{f: st.get(f, 0) for f in FAILS},
                             "provenance": dict(prov), "target_support": dict(support), "warnings": dict(warn),
                             "attempts": dict(att), "http_attempts": sum(att.values())})
        self.out["integrity"] = {"cells": rows, "unplanned_records": unplanned, "fingerprint_mismatches": self.fingerprints()}
        to_csv(self.rd / "integrity.csv", rows)

    def fingerprints(self):
        bad = []
        for m in self.models:
            for c in self.plan.matrix_cases():
                for st in ("E0", "E1"):
                    fps = set()
                    for a in P.MATRIX_ARMS:
                        r = self.mx.get(f"matrix::{m}::{c['case_id']}::{st}::{a}")
                        if r and r["provenance"]:
                            fps.add(r["provenance"]["block_fingerprint"])
                    ev = self.ev.get(f"evidence::{m}::{c['case_id']}::{st}")
                    if ev and ev["provenance"]:
                        fps.add(ev["provenance"]["block_fingerprint"])
                        nk = self.mx.get(f"matrix::{m}::{c['case_id']}::{st}::neutral")
                        if nk and nk["provenance"]["request_sha256"] != ev["provenance"]["request_sha256"]:
                            bad.append(f"neutral != evidence request {m} {c['case_id']} {st}")
                    if len(fps) > 1:
                        bad.append(f"matrix block {m} {c['case_id']} {st}: {len(fps)} fingerprints")
        for k, r in self.pr.items():
            twin = self.ev.get(r["neutral_twin_key"])
            if r["provenance"] and twin and twin["provenance"] and twin["provenance"]["block_fingerprint"] != r["provenance"]["block_fingerprint"]:
                bad.append(f"pair {k}: fingerprint differs from twin")
        return bad

    # ---------------- provenance summary
    def provenance(self):
        rows = []
        for exp, recs in (("evidence", self.ev), ("matrix", self.mx), ("pair", self.pr)):
            for m in self.models:
                st, sup, off_line = Counter(), Counter(), 0
                n = 0
                for r in recs.values():
                    if r.get("model") != m or not ok(r):
                        continue
                    pc = r["result"].get("provenance_check")
                    if not pc:
                        continue
                    n += 1
                    st[pc["status"]] += 1
                    sup[pc.get("target_support")] += 1
                    off_line += pc["counts"]["ADJACENT_BLANK"]
                if n:
                    rows.append({"experiment": exp, "model": m, "valid_trials": n, **{f"status_{k}": st.get(k, 0) for k in ("VALID", "OFF_BY_ONE", "INVALID", "EMPTY")},
                                 **{f"support_{k}": sup.get(k, 0) for k in ("SUPPORTED", "SUPPORTED_ADJACENT", "UNSUPPORTED")},
                                 "adjacent_blank_ids": off_line})
        # provenance by verdict correctness (evidence, E0/E2 correct vs incorrect)
        by_correct = defaultdict(Counter)
        for r in self.ev.values():
            if ok(r):
                pc = r["result"]["provenance_check"]
                by_correct[(r["model"], verdict(r) == r["truth"])][pc.get("target_support")] += 1
        self.out["provenance"] = {"by_model": rows, "support_by_verdict_correctness":
                                  {f"{m}|{'correct' if c else 'incorrect'}": dict(v) for (m, c), v in by_correct.items()}}
        to_csv(self.rd / "provenance.csv", rows)

    # ---------------- H2
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

    def evidence_rates(self, models, cases):
        cnt = {s: [0, 0] for s in D.STATES}
        traj = [0, 0]
        pats = Counter()
        for m in models:
            for c in cases:
                v = {s: verdict(self.ev.get(f"evidence::{m}::{c['case_id']}::{s}")) for s in D.STATES}
                for s in D.STATES:
                    if v[s] is not None:
                        cnt[s][1] += 1
                        cnt[s][0] += v[s] == c["truth"][s]
                p = self.pattern(v)
                pats[p] += 1
                if p != "INCOMPLETE":
                    traj[1] += 1
                    traj[0] += p == "PASS"
        return {"E0_detection": rate(*cnt["E0"]), "E1_clearance": rate(*cnt["E1"]), "E2_detection": rate(*cnt["E2"]),
                "trajectory": rate(*traj), "patterns": dict(pats)}

    def h2(self):
        res = {"by_model": {}, "by_paper": {}, "by_family": {}, "by_model_paper": {}, "lopo": {}}
        rows = []
        for m in self.models + ["POOLED"]:
            ms = self.models if m == "POOLED" else [m]
            res["by_model"][m] = self.evidence_rates(ms, self.cases)
            for p in self.papers:
                res["by_model_paper"][f"{m}|{p}"] = self.evidence_rates(ms, [c for c in self.cases if c["paper"] == p])
                res["lopo"][f"{m}|without {p}"] = self.evidence_rates(ms, [c for c in self.cases if c["paper"] != p])
            for fam in self.families:
                res["by_family"][f"{m}|{fam}"] = self.evidence_rates(ms, [c for c in self.cases if c["family"] == fam])
        for k, v in list(res["by_model"].items()) + list(res["by_model_paper"].items()) + list(res["by_family"].items()):
            rows.append({"slice": k, **{x: v[x]["rate"] for x in ("E0_detection", "E1_clearance", "E2_detection", "trajectory")},
                         "n_cases": v["trajectory"]["n"], **{f"pattern_{p}": n for p, n in v["patterns"].items()}})
        self.out["h2"] = res
        to_csv(self.rd / "h2_evidence_trajectory.csv", rows)
        traj_rows = []
        for m in self.models:
            for c in self.cases:
                v = {s: verdict(self.ev.get(f"evidence::{m}::{c['case_id']}::{s}")) for s in D.STATES}
                traj_rows.append({"model": m, "paper": c["paper"], "case_id": c["case_id"], "family": c["family"], **v,
                                  "pattern": self.pattern(v)})
        to_csv(self.rd / "trajectories.csv", traj_rows)

    # ---------------- blind
    def blind(self):
        scored, amb, rows = [], [], []
        summary = {}
        for m in self.models:
            per = {"labels": Counter(), "labels_sensitivity": Counter(), "labels_adjacent": Counter(), "n": 0,
                   "clean_fp": Counter(), "clean_touched": Counter(), "clean_findings": {}, "generic_on_target": 0,
                   "finding_counts_E0": Counter(), "by_paper": defaultdict(Counter), "by_family": defaultdict(Counter)}
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
                            scored.append({"model": m, "paper": it["paper"], "case_id": c["case_id"], "kind": "clean", "label": lab})
                    continue
                c = self.cid[it["case_id"]]
                entry = {"model": m, "paper": c["paper"], "case_id": c["case_id"], "family": c["family"], "kind": "defective"}
                if ok(r):
                    fnd = r["result"]["parsed"]["findings"]
                    lab, feats = S.label_defective(fnd, c, self.ledger, it["valid"])
                    lab_s, feats_s = S.label_defective(fnd, c, self.ledger, it["valid"], S.SENSITIVITY_TEXT_FIELDS)
                    lab_a, _ = S.label_defective(fnd, c, self.ledger, it["valid"], allow_adjacent=True)
                    per["n"] += 1
                    per["labels"][lab] += 1
                    per["labels_sensitivity"][lab_s] += 1
                    per["labels_adjacent"][lab_a] += 1
                    per["by_paper"][c["paper"]][lab] += 1
                    per["by_family"][c["family"]][lab] += 1
                    per["finding_counts_E0"][len(fnd)] += 1
                    g = any(x["L"] and x["G"] for x in feats_s)
                    per["generic_on_target"] += g
                    entry.update({"status": "OK", "label": lab, "label_sensitivity": lab_s, "label_adjacent": lab_a,
                                  "n_findings": len(fnd), "generic_on_target": g, "features": feats})
                    if lab == "AMBIGUOUS_REVIEW" or lab_s != lab or lab_a != lab:
                        amb.append({"model": m, "case_id": c["case_id"], "label": lab, "label_sensitivity": lab_s,
                                    "label_adjacent": lab_a, "target_lines": c["target_lines"],
                                    "tokens": c["blind_tokens"]["E0"], "findings": fnd})
                else:
                    entry.update({"status": r["result"]["status"] if r else "NOT_RUN", "label": None})
                scored.append(entry)
                rows.append({k: entry.get(k) for k in ("model", "paper", "case_id", "family", "status", "label",
                                                        "label_sensitivity", "label_adjacent", "n_findings", "generic_on_target")})
            summary[m] = {"n_valid": per["n"], "labels": dict(per["labels"]),
                          "true_rate": rate(per["labels"]["TRUE_DETECTION"], per["n"]),
                          "true_rate_sensitivity": rate(per["labels_sensitivity"]["TRUE_DETECTION"], per["n"]),
                          "true_rate_adjacent": rate(per["labels_adjacent"]["TRUE_DETECTION"], per["n"]),
                          "generic_on_target": rate(per["generic_on_target"], per["n"]),
                          "finding_counts_E0": dict(sorted(per["finding_counts_E0"].items())),
                          "clean_false_positives": dict(per["clean_fp"]), "clean_target_touched": dict(per["clean_touched"]),
                          "clean_findings": per["clean_findings"],
                          "by_paper": {p: dict(v) for p, v in per["by_paper"].items()},
                          "by_family": {f: dict(v) for f, v in per["by_family"].items()}}
        self.out["blind"] = summary
        self.blind_scored = {(e["model"], e["case_id"]): e for e in scored if e["kind"] == "defective"}
        (self.rd / "blind_scored.json").write_text(json.dumps(scored, indent=1) + "\n")
        with (self.rd / "ambiguous_review.jsonl").open("w") as fh:
            for a in amb:
                fh.write(json.dumps(a, ensure_ascii=False) + "\n")
        to_csv(self.rd / "blind_scores.csv", rows)

    # ---------------- H1
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
        res = {"by_model": {}, "by_paper": {}, "by_family": {}, "lopo": {}, "lofo": {}, "by_model_paper": {}}
        rows = []
        for m in self.models + ["POOLED"]:
            ms = self.models if m == "POOLED" else [m]
            res["by_model"][m] = self.h1_table(ms, self.cases)
            for p in self.papers:
                res["by_model_paper"][f"{m}|{p}"] = self.h1_table(ms, [c for c in self.cases if c["paper"] == p])
                res["lopo"][f"{m}|without {p}"] = self.h1_table(ms, [c for c in self.cases if c["paper"] != p])
            for fam in self.families:
                res["by_family"][f"{m}|{fam}"] = self.h1_table(ms, [c for c in self.cases if c["family"] == fam])
                res["lofo"][f"{m}|without {fam}"] = self.h1_table(ms, [c for c in self.cases if c["family"] != fam])
        for group in ("by_model", "by_model_paper", "by_family", "lopo", "lofo"):
            for k, t in res[group].items():
                rows.append({"group": group, "slice": k, "n": t["n"], "targeted_rate": t["targeted_rate"]["rate"],
                             "blind_rate": t["blind_rate"]["rate"], "both": t["both"], "targeted_only": t["first_only"],
                             "blind_only": t["second_only"], "neither": t["neither"], "diff": t["diff"],
                             "ci_lo": t["ci95"][0], "ci_hi": t["ci95"][1], "mcnemar_p": t["mcnemar_p"]})
        self.out["h1"] = res
        to_csv(self.rd / "h1_discovery_vs_targeted.csv", rows)

    # ---------------- matrix (H3, S1, location)
    def blocks(self, models=None, cases=None, states=("E0", "E1")):
        cases = cases if cases is not None else self.plan.matrix_cases()
        for m in models or self.models:
            for c in cases:
                for st in states:
                    yield m, c, st, c["truth"][st], {a: self.mx.get(f"matrix::{m}::{c['case_id']}::{st}::{a}") for a in P.MATRIX_ARMS}

    def compare(self, arm_a, arm_b, **kw):
        """Paired correctness of arm_b vs arm_a: first = arm_b correct, second = arm_a correct."""
        pairs, adopt = [], [0, 0]
        for m, c, st, truth, arms in self.blocks(**kw):
            va, vb = verdict(arms[arm_a]), verdict(arms[arm_b])
            if va is None or vb is None:
                continue
            pairs.append((vb == truth, va == truth))
            pv = arms[arm_b].get("prior_verdict") if arms[arm_b] else None
            vn = verdict(arms["neutral"])
            if pv and vn is not None and vn != pv:
                adopt[1] += 1
                adopt[0] += vb == pv
        t = paired_table(pairs)
        t.update({"a": arm_a, "b": arm_b, "helpful": t["first_only"], "harmful": t["second_only"],
                  "unchanged": t["both"] + t["neither"], "b_adoption_given_neutral_disagreed": rate(*adopt)})
        return t

    def direction(self, arms, **kw):
        down = up = n = 0
        for m, c, st, truth, a in self.blocks(**kw):
            vn = verdict(a["neutral"])
            for arm in arms:
                va = verdict(a[arm])
                if vn is None or va is None:
                    continue
                n += 1
                d = ORD[va] - ORD[vn]
                down += d < 0
                up += d > 0
        return {"n": n, "toward_clearance": down, "toward_issue": up, "sign_test_p": round(binom_two_sided(up, up + down), 6)}

    def matrix(self):
        mc = self.plan.matrix_cases()
        mpapers = sorted({c["paper"] for c in mc})
        mfams = sorted({c["family"] for c in mc})
        weak = [m for m in self.models if self.dev.get(m) == "weak"]
        strong = [m for m in self.models if self.dev.get(m) == "strong"]

        def suite(fn):
            out = {"pooled": fn(), "by_model": {m: fn(models=[m]) for m in self.models},
                   "by_paper": {p: fn(cases=[c for c in mc if c["paper"] == p]) for p in mpapers},
                   "by_family": {f: fn(cases=[c for c in mc if c["family"] == f]) for f in mfams},
                   "lopo": {p: fn(cases=[c for c in mc if c["paper"] != p]) for p in mpapers},
                   "lofo": {f: fn(cases=[c for c in mc if c["family"] != f]) for f in mfams},
                   "by_state": {s: fn(states=(s,)) for s in ("E0", "E1")}}
            if weak:
                out["weak_models"] = fn(models=weak)
            if strong:
                out["strong_models"] = fn(models=strong)
            return out

        res = {"h3_correct_rationale_vs_correct_verdict": suite(lambda **k: self.compare("correct_verdict", "correct_rationale", **k)),
               "s1_false_verdict_vs_neutral": suite(lambda **k: self.compare("neutral", "false_verdict", **k)),
               "s1_false_rationale_vs_false_verdict": suite(lambda **k: self.compare("false_verdict", "false_rationale", **k)),
               "s1_false_rationale_vs_neutral": suite(lambda **k: self.compare("neutral", "false_rationale", **k)),
               "correct_verdict_vs_neutral": {"pooled": self.compare("neutral", "correct_verdict")},
               "correct_rationale_vs_neutral": {"pooled": self.compare("neutral", "correct_rationale")},
               "location_vs_neutral": {"accuracy": self.compare("neutral", "location"), "direction": self.direction(["location"]),
                                       "direction_by_state": {s: self.direction(["location"], states=(s,)) for s in ("E0", "E1")}},
               "balanced_prior_direction": self.direction(["correct_verdict", "false_verdict", "correct_rationale", "false_rationale"])}
        agree = same = n = 0
        for m, c, st, truth, arms in self.blocks():
            ev = self.ev.get(f"evidence::{m}::{c['case_id']}::{st}")
            if ok(ev) and ok(arms["neutral"]):
                n += 1
                agree += verdict(ev) == verdict(arms["neutral"])
                same += ev["result"]["content"] == arms["neutral"]["result"]["content"]
        res["noise_floor"] = {"verdict_agreement": rate(agree, n), "byte_identical": rate(same, n)}
        self.out["matrix"] = res
        rows = []
        for name in ("h3_correct_rationale_vs_correct_verdict", "s1_false_verdict_vs_neutral",
                     "s1_false_rationale_vs_false_verdict", "s1_false_rationale_vs_neutral"):
            for group, val in res[name].items():
                items = val.items() if isinstance(val, dict) and "n" not in val else [("", val)]
                for k, t in items:
                    rows.append({"comparison": name, "group": group, "slice": k, "n": t["n"], "helpful": t["helpful"],
                                 "harmful": t["harmful"], "unchanged": t["unchanged"], "acc_diff": t["diff"],
                                 "ci_lo": t["ci95"][0], "ci_hi": t["ci95"][1], "mcnemar_p": t["mcnemar_p"],
                                 "adoption_rate": t["b_adoption_given_neutral_disagreed"]["rate"],
                                 "adoption_n": t["b_adoption_given_neutral_disagreed"]["n"]})
        to_csv(self.rd / "matrix_comparisons.csv", rows)

    # ---------------- pairs
    def pairs(self):
        units = defaultdict(dict)
        for k, r in self.pr.items():
            units[(r["source_model"], r["target_model"], r["case_id"], r["state"])][r["arm"]] = r
        res, rows = {}, []
        for cls in ("CORRECT", "DECISIVELY_WRONG", "UNRESOLVED", "FAILED"):
            for arm in P.PAIR_ARMS:
                cat, adopt, cases, failed, n_units = Counter(), [0, 0], set(), 0, 0
                for (src, tgt, cid, st), arms in units.items():
                    r = arms.get(arm)
                    if not r or r["source_class"] != cls:
                        continue
                    if cls == "FAILED":
                        failed += 1
                        continue
                    tw = self.ev.get(r["neutral_twin_key"])
                    va, vn, sv, truth = verdict(r), verdict(tw), r["source_verdict"], r["truth"]
                    if va is None or vn is None:
                        cat["TRIAL_FAILED"] += 1
                        continue
                    n_units += 1
                    cases.add(cid)
                    if vn == sv:
                        k = "ALREADY_AGREED"
                    elif va == sv:
                        k = "NEWLY_ADOPTED"
                    elif va == truth and vn != truth:
                        k = "CORRECTED"
                    elif va == "UNRESOLVED" and vn != "UNRESOLVED":
                        k = "CHANGED_TO_UNRESOLVED"
                    elif va == vn:
                        k = "UNCHANGED"
                    else:
                        k = "OTHER_DIFFERENT"
                    cat[k] += 1
                    if vn != sv:
                        adopt[1] += 1
                        adopt[0] += va == sv
                e = {"source_class": cls, "arm": arm, "valid_units": n_units, "n_cases": len(cases), "categories": dict(cat),
                     "adoption_not_already_agreeing": rate(*adopt), "estimable": S.estimable(adopt[1], len(cases)),
                     "source_failed": failed}
                res[f"{cls}|{arm}"] = e
                rows.append({"source_class": cls, "arm": arm, "valid_units": n_units, "n_cases": len(cases),
                             **{k: cat.get(k, 0) for k in ("ALREADY_AGREED", "NEWLY_ADOPTED", "CORRECTED",
                                                           "CHANGED_TO_UNRESOLVED", "UNCHANGED", "OTHER_DIFFERENT", "TRIAL_FAILED")},
                             "adoption_rate": e["adoption_not_already_agreeing"]["rate"], "adoption_n": adopt[1],
                             "estimable": e["estimable"], "source_failed": failed})
        paired = {}
        for cls in ("CORRECT", "DECISIVELY_WRONG", "UNRESOLVED"):
            pp = []
            for (src, tgt, cid, st), arms in units.items():
                if set(P.PAIR_ARMS) - set(arms):
                    continue
                rv, rr = arms["actual_verdict"], arms["actual_rationale"]
                if rv["source_class"] != cls:
                    continue
                tw = self.ev.get(rv["neutral_twin_key"])
                vv, vr, vn, sv = verdict(rv), verdict(rr), verdict(tw), rv["source_verdict"]
                if None in (vv, vr, vn) or vn == sv:
                    continue
                pp.append((vr == sv, vv == sv))
            paired[cls] = paired_table(pp)
        by_cat = defaultdict(Counter)
        for (src, tgt, cid, st), arms in units.items():
            for arm, r in arms.items():
                if r["source_class"] != "DECISIVELY_WRONG":
                    continue
                va, vn = verdict(r), verdict(self.ev.get(r["neutral_twin_key"]))
                if va is None or vn is None or vn == r["source_verdict"]:
                    continue
                key = f"{r['pair_category']}|{src}->{tgt}|{arm}"
                by_cat[key]["n"] += 1
                by_cat[key]["adopted"] += va == r["source_verdict"]
        self.out["pairs"] = {"by_class_arm": res, "paired_rationale_vs_verdict_adoption": paired,
                             "wrong_source_by_pair": {k: dict(v) for k, v in by_cat.items()}}
        to_csv(self.rd / "pairs_by_class.csv", rows)

    # ---------------- anchor
    def anchor(self):
        r2 = self.plan.r2
        res = {}
        for m in self.models:
            cnt = {s: [0, 0] for s in D.STATES}
            traj = [0, 0]
            blind = Counter()
            for c in self.plan.anchor_cases():
                v = {}
                for s in D.STATES:
                    r = self.an.get(f"anchor::{m}::{c['case_id']}::{s}")
                    v[s] = verdict(r)
                    if v[s] is not None:
                        cnt[s][1] += 1
                        cnt[s][0] += v[s] == c["truth"][D.R2_STATE[s]]
                if all(v[s] is not None for s in D.STATES):
                    traj[1] += 1
                    traj[0] += self.pattern(v) == "PASS"
                rb = self.an.get(f"anchorblind::{m}::{c['case_id']}::E0")
                if ok(rb):
                    valid = self.plan.anchor_paper(c, "E0")[1]
                    lab, _ = S.label_defective(rb["result"]["parsed"]["findings"], c, r2, valid)
                    blind[lab] += 1
            res[m] = {"E0_detection": rate(*cnt["E0"]), "E1_clearance": rate(*cnt["E1"]), "E2_detection": rate(*cnt["E2"]),
                      "trajectory": rate(*traj), "blind_labels": dict(blind)}
        self.out["anchor_replication"] = res

    # ---------------- leakage in targeted text
    def leakage(self):
        terms = self.ledger["generic_flag_terms"]
        cnt = defaultdict(lambda: [0, 0])
        for r in self.ev.values():
            if not ok(r):
                continue
            p = r["result"]["parsed"]
            t = " ".join(str(p.get(x) or "") for x in ("analysis", "brief_reason", "evidence_summary")).lower()
            k = (r["model"], r["state"])
            cnt[k][1] += 1
            cnt[k][0] += any(w in t for w in terms)
        self.out["leakage_targeted_text"] = {f"{m}|{s}": rate(*v) for (m, s), v in cnt.items()}

    # ---------------- decision and reports
    def decide(self):
        self.out["decision"] = DR.decide(self.out, self)
        (self.rd / "decision.json").write_text(json.dumps(self.out["decision"], indent=1) + "\n")

    def reports(self):
        o = self.out
        L = ["# Experiment 2B — evaluator report", "", f"Run `{self.rd.name}`, scope `{self.scope}`, design manifest "
             f"`{o['design_manifest_sha256']}`. Primary models: {', '.join(self.models)}. Papers: {', '.join(self.papers)}.",
             "All numbers are produced by `exp2b/evaluate.py` from frozen definitions. Primary statistics exclude the ELVAE anchor.", ""]
        L += ["## Integrity", "", "| Experiment | Model | Requested | Valid | Rate | Truncated | Schema | Parse | Empty | HTTP | Source failed |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for c in o["integrity"]["cells"]:
            L.append(f"| {c['experiment']} | {c['model']} | {c['requested']} | {c['valid']} | {100 * c['valid_rate']:.1f}% | "
                     f"{c['TRUNCATED']} | {c['INVALID_SCHEMA']} | {c['PARSE_FAILED']} | {c['EMPTY_CONTENT']} | {c['HTTP_FAILED']} | {c['SOURCE_FAILED']} |")
        L += ["", f"Fingerprint mismatches: {len(o['integrity']['fingerprint_mismatches'])}; unplanned records: {len(o['integrity']['unplanned_records'])}.", ""]
        L += ["## Provenance (valid targeted trials)", "", "| Experiment | Model | Valid | All exact | Off-by-one (blank neighbour) | Invalid | Empty | Cites target | Target via adjacent | Unsupported |", "|---|---|---|---|---|---|---|---|---|---|"]
        for r in o["provenance"]["by_model"]:
            L.append(f"| {r['experiment']} | {r['model']} | {r['valid_trials']} | {r['status_VALID']} | {r['status_OFF_BY_ONE']} | {r['status_INVALID']} | {r['status_EMPTY']} | "
                     f"{r['support_SUPPORTED']} | {r['support_SUPPORTED_ADJACENT']} | {r['support_UNSUPPORTED']} |")
        h2 = o["h2"]
        L += ["", "## H2 — evidence trajectory", "", "| Model | E0 detection | E1 clearance | E2 detection | Full trajectory | Patterns |", "|---|---|---|---|---|---|"]
        for m, v in h2["by_model"].items():
            L.append(f"| {m} | {pct(v['E0_detection'])} | {pct(v['E1_clearance'])} | {pct(v['E2_detection'])} | {pct(v['trajectory'])} | {v['patterns']} |")
        L += ["", "Trajectory by paper (pooled over models / per model):", ""]
        for p in self.papers:
            L.append(f"- {p}: pooled {pct(h2['by_model_paper'][f'POOLED|{p}']['trajectory'])}; " +
                     "; ".join(f"{m} {pct(h2['by_model_paper'][f'{m}|{p}']['trajectory'])}" for m in self.models))
        L += ["", "Trajectory by family (pooled over models):", ""]
        for fam in self.families:
            L.append(f"- {fam}: {pct(h2['by_family'][f'POOLED|{fam}']['trajectory'])}")
        bl = o["blind"]
        L += ["", "## Blind discovery (strict scorer)", "", "| Model | Valid | TRUE | PARTIAL | AMBIGUOUS | MISSED | TRUE sensitivity | TRUE adjacent-ok | Generic on target | Findings per E0 audit | Clean FP (relations) |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for m, b in bl.items():
            lab = b["labels"]
            L.append(f"| {m} | {b['n_valid']} | {pct(b['true_rate'])} | {lab.get('PARTIAL_DETECTION', 0)} | {lab.get('AMBIGUOUS_REVIEW', 0)} | {lab.get('MISSED', 0)} | "
                     f"{pct(b['true_rate_sensitivity'])} | {pct(b['true_rate_adjacent'])} | {pct(b['generic_on_target'])} | {b['finding_counts_E0']} | {b['clean_false_positives']} |")
        h1 = o["h1"]
        L += ["", "## H1 — discovery vs targeted verification (paired E0 cases)", "", "| Slice | n | Targeted | Blind TRUE | Both | Targeted only | Blind only | Neither | Diff [95% CI] | McNemar p |", "|---|---|---|---|---|---|---|---|---|---|"]
        for group in ("by_model", "by_model_paper", "lopo", "lofo"):
            for k, t in h1[group].items():
                if group != "by_model" and not k.startswith("POOLED"):
                    continue
                L.append(f"| {group}:{k} | {t['n']} | {pct(t['targeted_rate'])} | {pct(t['blind_rate'])} | {t['both']} | {t['first_only']} | {t['second_only']} | {t['neither']} | "
                         f"{t['diff']} [{t['ci95'][0]}, {t['ci95'][1]}] | {t['mcnemar_p']} |")
        mx = o["matrix"]

        def cmp_rows(title, block):
            out = ["", f"### {title}", "", "| Slice | n | Helpful | Harmful | Unchanged | Acc. diff [95% CI] | p | Adoption of prior (neutral disagreed) |", "|---|---|---|---|---|---|---|---|"]
            for group in ("pooled", "by_model", "weak_models", "strong_models", "by_paper", "lopo", "by_family", "lofo", "by_state"):
                if group not in block:
                    continue
                val = block[group]
                items = [("", val)] if "n" in val else list(val.items())
                for k, t in items:
                    out.append(f"| {group}{':' + k if k else ''} | {t['n']} | {t['helpful']} | {t['harmful']} | {t['unchanged']} | {t['diff']} [{t['ci95'][0]}, {t['ci95'][1]}] | {t['mcnemar_p']} | {pct(t['b_adoption_given_neutral_disagreed'])} |")
            return out
        L += ["", "## Controlled exposure", "", f"Noise floor: neutral arm vs byte-identical evidence request — verdict agreement {pct(mx['noise_floor']['verdict_agreement'])}, byte-identical {pct(mx['noise_floor']['byte_identical'])}."]
        L += cmp_rows("H3 — correct verdict + rationale vs correct verdict ('helpful' = correct only with the rationale)", mx["h3_correct_rationale_vs_correct_verdict"])
        L += cmp_rows("S1 — false verdict vs neutral ('harmful' = correct only under neutral)", mx["s1_false_verdict_vs_neutral"])
        L += cmp_rows("S1 — false verdict + rationale vs false verdict", mx["s1_false_rationale_vs_false_verdict"])
        L += cmp_rows("S1 — false verdict + rationale vs neutral", mx["s1_false_rationale_vs_neutral"])
        loc = mx["location_vs_neutral"]
        L += ["", f"Location-only vs neutral: accuracy helpful {loc['accuracy']['helpful']} / harmful {loc['accuracy']['harmful']} (p={loc['accuracy']['mcnemar_p']}); "
              f"direction toward clearance {loc['direction']['toward_clearance']} vs toward issue {loc['direction']['toward_issue']} (p={loc['direction']['sign_test_p']}). "
              f"Balanced prior arms: {mx['balanced_prior_direction']['toward_clearance']} vs {mx['balanced_prior_direction']['toward_issue']} (p={mx['balanced_prior_direction']['sign_test_p']})."]
        pw = o["pairs"]
        L += ["", "## Actual verifier-to-verifier exposure (observational)", "", "| Source class | Arm | Units | Cases | Already agreed | Newly adopted | Corrected | To unresolved | Unchanged | Other | Adoption (not already agreeing) | Estimable |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for e in pw["by_class_arm"].values():
            c = e["categories"]
            L.append(f"| {e['source_class']} | {e['arm']} | {e['valid_units']} | {e['n_cases']} | {c.get('ALREADY_AGREED', 0)} | {c.get('NEWLY_ADOPTED', 0)} | {c.get('CORRECTED', 0)} | "
                     f"{c.get('CHANGED_TO_UNRESOLVED', 0)} | {c.get('UNCHANGED', 0)} | {c.get('OTHER_DIFFERENT', 0)} | {pct(e['adoption_not_already_agreeing'])} | {e['estimable']} |")
        L += ["", "Paired adoption, rationale vs verdict (units whose neutral twin did not already agree):", ""]
        for cls, t in pw["paired_rationale_vs_verdict_adoption"].items():
            L.append(f"- {cls}: n={t['n']}, rationale-only {t['first_only']}, verdict-only {t['second_only']}, both {t['both']}, diff {t['diff']} [{t['ci95'][0]}, {t['ci95'][1]}], p={t['mcnemar_p']}")
        L += ["", "## ANCHOR_REPLICATION (ELVAE; not part of primary statistics)", "", "| Model | E0 | E1 | E2 | Trajectory | Blind labels |", "|---|---|---|---|---|---|"]
        for m, v in o["anchor_replication"].items():
            L.append(f"| {m} | {pct(v['E0_detection'])} | {pct(v['E1_clearance'])} | {pct(v['E2_detection'])} | {pct(v['trajectory'])} | {v['blind_labels']} |")
        L += ["", "## Mechanical decision (frozen rules)", "", f"**{o['decision']['status']}**", "", "```json", json.dumps(o["decision"], indent=1), "```"]
        (self.rd / "REPORT.md").write_text("\n".join(L) + "\n")

        I = ["# Integrity report", "", f"Run `{self.rd.name}`.", ""]
        tot = Counter()
        for c in o["integrity"]["cells"]:
            for k in ("requested", "valid", "failed", "http_attempts") + FAILS:
                tot[k] += c[k]
        I += [f"- Requested {tot['requested']}, valid {tot['valid']}, failed {tot['failed']}.",
              "- Failures: " + ", ".join(f"{k} {tot[k]}" for k in FAILS), f"- HTTP attempts: {tot['http_attempts']}",
              f"- Fingerprint mismatches: {len(o['integrity']['fingerprint_mismatches'])}", f"- Unplanned records: {len(o['integrity']['unplanned_records'])}", "",
              "| Experiment | Model | Requested | Valid | Rate | >=95% | Failures | Provenance | Target support | Warnings | Attempts |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for c in o["integrity"]["cells"]:
            fails = {k: c[k] for k in FAILS if c[k]}
            I.append(f"| {c['experiment']} | {c['model']} | {c['requested']} | {c['valid']} | {100 * c['valid_rate']:.1f}% | {'yes' if c['valid_rate'] >= 0.95 else 'NO'} | "
                     f"{fails or '—'} | {c['provenance']} | {c['target_support']} | {c['warnings'] or '—'} | {c['attempts']} |")
        (self.rd / "INTEGRITY_REPORT.md").write_text("\n".join(I) + "\n")
        (self.rd / "analysis.json").write_text(json.dumps(o, indent=1, default=str) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args()
    rd = Path(a.run_dir)
    if not rd.is_absolute():
        rd = ROOT / rd
    E = Eval(rd)
    E.integrity()
    E.provenance()
    E.h2()
    E.blind()
    E.h1()
    E.matrix()
    E.pairs()
    E.anchor()
    E.leakage()
    E.decide()
    E.reports()
    print("decision:", E.out["decision"]["status"])


if __name__ == "__main__":
    main()

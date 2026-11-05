#!/usr/bin/env python3
"""Shared loader and metrics for POST_HOC_FAIR_SCORING_VALIDATION.

Builds one tidy table of (system, rung, case_id, state) cells from frozen records plus the
new E1 records, scored only with the frozen scorers in exp2b/scoring.py. Nothing is
re-implemented here that already exists frozen.

Rungs
  BLIND_FINDING_LIST               open-ended whole-manuscript scan
  CATEGORY_TARGETED_FINDING_LIST   names the defect family
  RELATION_TARGETED_FINDING_LIST   names the specific relation
  RELATION_LOCALIZED_BINARY_VERDICT  binary verdict on the named relation

Cell fields
  e0_correct     E0 sensitivity numerator (strict discovery, or correct defective verdict)
  e1_false_alarm E1 false-alarm numerator for the tested relation
  target_support provenance target support, binary rung only
"""
from __future__ import annotations
import json, math, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
RR = ROOT / "nature_extension/reviewer_response_20261016"
TV = ROOT / "nature_extension/final_topvenue_validation_20261018"
FROZEN = ROOT / "runs/exp3heldout_20260918_014959"
for p in ("exp3heldout", "exp2b", "exp2br"):
    sys.path.insert(0, str(ROOT / p))
sys.path.insert(0, str(RR / "code"))

import design_heldout as D   # noqa: E402
import scoring as S          # noqa: E402
import client as C           # noqa: E402

RUNGS = ["BLIND_FINDING_LIST", "CATEGORY_TARGETED_FINDING_LIST",
         "RELATION_TARGETED_FINDING_LIST", "RELATION_LOCALIZED_BINARY_VERDICT"]
RUNG_SHORT = {"BLIND_FINDING_LIST": "blind",
              "CATEGORY_TARGETED_FINDING_LIST": "category",
              "RELATION_TARGETED_FINDING_LIST": "relation",
              "RELATION_LOCALIZED_BINARY_VERDICT": "binary"}
ARM_TO_RUNG = {"CATEGORY_TARGETED_DISCOVERY": "CATEGORY_TARGETED_FINDING_LIST",
               "RELATION_TARGETED_DISCOVERY": "RELATION_TARGETED_FINDING_LIST"}
OPENWEIGHT = ["qwen38_27", "qwen36_27", "gemma4_12", "granite42_30", "qwen3_8"]
FRONTIER = "gpt-5.2"
SUPPORTED = {"SUPPORTED", "SUPPORTED_ADJACENT"}
BOOT_SEED = 20261016
BOOT_DRAWS = 10000


def jl(path):
    p = Path(path)
    if not p.exists():
        return
    for line in p.open():
        line = line.strip()
        if line:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


class Fair:
    def __init__(self):
        self.plan = D.Plan()
        self.cases = {c["case_id"]: c for c in self.plan.cases}
        self.man = json.loads((OUT / "e1/E1_FAIR_SCORING_MANIFEST.json").read_text())
        self.subset = self.man["case_ids"]
        self.ledger = self.plan.ledger
        self._valid = {}
        self.cells = {}        # (system, rung, case_id) -> dict
        self._load_all()

    # ---------------------------------------------------------------- helpers
    def valid_ids(self, case, state):
        k = (case["case_id"], state)
        if k not in self._valid:
            self._valid[k] = self.plan.paper_text(case, state)[1]
        return self._valid[k]

    def cell(self, system, rung, cid):
        return self.cells.setdefault((system, rung, cid), {
            "system": system, "rung": rung, "case_id": cid,
            "paper": self.cases[cid]["paper"], "family": self.cases[cid]["family"],
            "domain": self.cases[cid]["domain"]})

    def _score_findinglist(self, system, rung, cid, state, findings, status):
        c = self.cases[cid]
        cell = self.cell(system, rung, cid)
        if status != "OK" or findings is None:
            cell[f"{state.lower()}_status"] = status or "MISSING"
            return
        cell[f"{state.lower()}_status"] = "OK"
        valid = self.valid_ids(c, state)
        if state == "E0":
            lab, feats = S.label_defective(findings, c, self.ledger, valid)
            cell["e0_label"] = lab
            cell["e0_correct"] = int(lab == "TRUE_DETECTION")
            cell["e0_n_findings"] = len(findings)
            cell["e0_feats"] = feats
            cell["e0_findings"] = findings
        else:
            lab, feats = S.label_clean(findings, c, self.ledger, valid)
            cell["e1_label"] = lab
            cell["e1_false_alarm"] = int(lab == "FALSE_POSITIVE")
            cell["e1_n_findings"] = len(findings)

    def _score_binary(self, system, cid, state, parsed, status, prov=None):
        c = self.cases[cid]
        cell = self.cell(system, "RELATION_LOCALIZED_BINARY_VERDICT", cid)
        if status != "OK" or parsed is None:
            cell[f"{state.lower()}_status"] = status or "MISSING"
            return
        cell[f"{state.lower()}_status"] = "OK"
        verdict = parsed.get("verdict")
        cell[f"{state.lower()}_verdict"] = verdict
        if prov is None:
            prov = S.provenance(parsed.get("evidence_line_ids") or [],
                                parsed.get("evidence_line_ids_malformed") or [],
                                self.valid_ids(c, state), c["target_lines"])
        cell[f"{state.lower()}_target_support"] = prov.get("target_support")
        cell[f"{state.lower()}_prov_status"] = prov.get("status")
        if state == "E0":
            cell["e0_correct"] = int(verdict == "ISSUE_PRESENT")
            cell["e0_prov_gated"] = int(verdict == "ISSUE_PRESENT"
                                        and prov.get("target_support") in SUPPORTED)
        else:
            cell["e1_false_alarm"] = int(verdict == "ISSUE_PRESENT")
            # a clean relation is cleared correctly regardless of citation, but we also
            # record whether the clearing response pointed at the tested relation at all
            cell["e1_prov_gated_clear"] = int(verdict != "ISSUE_PRESENT"
                                              and prov.get("target_support") in SUPPORTED)

    # ---------------------------------------------------------------- loaders
    def _load_all(self):
        sub = set(self.subset)

        # --- open-weight blind, frozen. E0 per relation, E1 per paper.
        e1_blind = {}
        for r in jl(FROZEN / "blind_trials.jsonl"):
            if r["state"] == "E1":
                e1_blind[(r["model"], r["paper"])] = r
                continue
            if r.get("case_id") in sub:
                res = r["result"]
                self._score_findinglist(r["model"], "BLIND_FINDING_LIST", r["case_id"], "E0",
                                        (res.get("parsed") or {}).get("findings"), res["status"])
        for m in OPENWEIGHT:
            for cid in self.subset:
                r = e1_blind.get((m, self.cases[cid]["paper"]))
                if r is None:
                    self.cell(m, "BLIND_FINDING_LIST", cid)["e1_status"] = "MISSING"
                    continue
                res = r["result"]
                self._score_findinglist(m, "BLIND_FINDING_LIST", cid, "E1",
                                        (res.get("parsed") or {}).get("findings"), res["status"])
                self.cell(m, "BLIND_FINDING_LIST", cid)["e1_source"] = r["key"]

        # --- open-weight targeted finding lists: E0 frozen ladder, E1 new
        for r in jl(RR / "ladder/ladder_trials.jsonl"):
            res = r["result"]
            self._score_findinglist(r["model"], ARM_TO_RUNG[r["arm"]], r["case_id"], "E0",
                                    (res.get("parsed") or {}).get("findings"), res["status"])
        for r in jl(OUT / "e1/e1_openweight_trials.jsonl"):
            res = r["result"]
            self._score_findinglist(r["model"], ARM_TO_RUNG[r["arm"]], r["case_id"], "E1",
                                    (res.get("parsed") or {}).get("findings"), res["status"])

        # --- open-weight binary verdict, frozen, both states
        for r in jl(FROZEN / "evidence_trials.jsonl"):
            if r.get("arm") != "neutral" or r["case_id"] not in sub or r["state"] == "E2":
                continue
            res = r["result"]
            self._score_binary(r["model"], r["case_id"], r["state"],
                               res.get("parsed"), res["status"],
                               res.get("provenance_check"))

        # --- frontier, E0 frozen and E1 new; parsed here with the frozen validators
        self._load_frontier(TV / "frontier/frontier_openai_trials.jsonl", "E0")
        self._load_frontier(OUT / "e1/e1_frontier_openai_trials.jsonl", "E1")

    @staticmethod
    def _parse(content, validator):
        """Parse one frontier response with the frozen parser and validator.
        Returns (parsed_or_None, status)."""
        try:
            obj, _fence = C.strict_json(content)
        except Exception:
            return None, "JSON_DECODE_FAILED"
        parsed, err, _w = validator(obj)
        return (parsed, "OK") if parsed is not None else (None, f"INVALID_SCHEMA:{err}")

    def _load_frontier(self, path, state):
        blind_by_paper = {}
        rows = list(jl(path))
        for r in rows:
            if r.get("status") != "OK" or r.get("content") is None:
                continue
            if r["rung"] == "BLIND_FINDING_LIST":
                blind_by_paper[r["paper"]] = r
        for r in rows:
            rung, cid = r["rung"], r["case_id"]
            if r.get("status") != "OK" or r.get("content") is None:
                self.cell(FRONTIER, rung, cid)[f"{state.lower()}_status"] = r.get("status", "MISSING")
                continue
            if rung == "RELATION_LOCALIZED_BINARY_VERDICT":
                parsed, st = self._parse(r["content"], C.validate_targeted)
                self._score_binary(FRONTIER, cid, state, parsed, st)
            elif rung != "BLIND_FINDING_LIST":
                parsed, st = self._parse(r["content"], C.validate_blind)
                self._score_findinglist(FRONTIER, rung, cid, state,
                                        (parsed or {}).get("findings"), st)
        # blind: one response per paper, scored against each relation of that paper
        for cid in self.subset:
            r = blind_by_paper.get(self.cases[cid]["paper"])
            if r is None:
                self.cell(FRONTIER, "BLIND_FINDING_LIST", cid)[f"{state.lower()}_status"] = "MISSING"
                continue
            parsed, st = self._parse(r["content"], C.validate_blind)
            self._score_findinglist(FRONTIER, "BLIND_FINDING_LIST", cid, state,
                                    (parsed or {}).get("findings"), st)

    # ---------------------------------------------------------------- views
    def rows(self, system=None, rung=None):
        for (s, g, cid), c in sorted(self.cells.items()):
            if system and s != system:
                continue
            if rung and g != rung:
                continue
            yield c


# ------------------------------------------------------------------- metrics
def loglinear_dprime(hits, n_sig, fas, n_noise):
    """d' with the Hautus (1995) log-linear correction: add 0.5 to each count and 1.0 to
    each total before converting to rates. Applied unconditionally, not only to 0/1 cells,
    so the estimator is the same function everywhere."""
    h = (hits + 0.5) / (n_sig + 1.0)
    f = (fas + 0.5) / (n_noise + 1.0)
    return _z(h) - _z(f), h, f


def _z(p):
    # inverse standard normal CDF, Acklam's rational approximation refined by one
    # Halley step against math.erfc; accurate to better than 1e-12 on (0,1)
    if not 0.0 < p < 1.0:
        raise ValueError(p)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        x = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= ph:
        q, r = p - 0.5, (p - 0.5) ** 2
        x = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
            (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    e = 0.5 * math.erfc(-x / math.sqrt(2)) - p
    u = e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


def cluster_bootstrap(units, stat, draws=BOOT_DRAWS, seed=BOOT_SEED):
    """Manuscript-cluster bootstrap. `units` maps paper -> list of per-case items;
    `stat` maps a flat list of items to a number or None."""
    keys = sorted(units)
    rng = random.Random(seed)
    point = stat([x for k in keys for x in units[k]])
    vals = []
    for _ in range(draws):
        samp = []
        for _ in range(len(keys)):
            samp += units[keys[rng.randrange(len(keys))]]
        v = stat(samp)
        if v is not None:
            vals.append(v)
    if len(vals) < draws * 0.5:
        return point, None, None, len(vals)
    vals.sort()
    lo = vals[int(0.025 * (len(vals) - 1))]
    hi = vals[int(0.975 * (len(vals) - 1))]
    return point, lo, hi, len(vals)


def wilson(k, n, z=1.959963984540054):
    if n == 0:
        return (None, None, None)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return p, (c - h) / d, (c + h) / d

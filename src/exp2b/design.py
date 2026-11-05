"""Experiment 2B frozen trial plan: primary models, phases, cases, matrix subset, pairs, blind items, anchor, validation scope."""
from __future__ import annotations

import json
from pathlib import Path

import models as M
import normalize as N
import protocol as P

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "exp2b"
STATES = ("E0", "E1", "E2")
R2_STATE = {"E0": "E0", "E1": "E1", "E2": "E2"}

# Set from exp2b/MODEL_BAKEOFF.md before freezing. None -> three Qwen primary models, cross-family unavailable.
NONQWEN: str | None = M.SELECTED_NONQWEN
PRIMARY = ["qwen38_27", "qwen36_27", "qwen3_8"] + ([NONQWEN] if NONQWEN else [])
PHASE_MODELS = {"large": ["qwen38_27", "qwen36_27"], "small": ["qwen3_8"] + ([NONQWEN] if NONQWEN else [])}

# (source, target, category). Every target runs in a phase in which its source's evidence trials already exist.
PAIRS = {
    "large": [("qwen38_27", "qwen38_27", "same_exact_checkpoint"),
              ("qwen36_27", "qwen38_27", "same_family_similar_capability")],
    "small": [("qwen38_27", "qwen3_8", "same_family_capability_unmatched")]
    + ([(NONQWEN, "qwen3_8", "cross_family"), ("qwen3_8", NONQWEN, "cross_family"),
        ("qwen36_27", NONQWEN, "cross_family_capability_unmatched")] if NONQWEN else []),
}

# ELVAE anchor: the first 2A-R2 case of each family that is NOT in the 2B development subset (2A-R2 matrix cases).
ANCHOR_CASES = ["arith_decoder_variance", "num_cnn_accuracy", "xref_anchor_table", "stat_range_transition",
                "claim_correction_interval", "method_tau_grid"]

# Validation-gate scope (fixed before any 2B inference; the gate's outputs are never used for tuning).
VALIDATION = {"evidence_cases": ["p03933_num_mc_reps", "p04261_xref_probe"],
              "matrix_case": "p03933_num_mc_reps", "pair_case": "p03933_num_mc_reps", "anchor_case": "num_cnn_accuracy"}


class Plan:
    def __init__(self, scope: str):
        self.scope = scope
        self.ledger = json.loads((EXP / "ledger.json").read_text())
        self.all_cases = self.ledger["cases"]
        self.by_id = {c["case_id"]: c for c in self.all_cases}
        self._papers: dict[str, tuple] = {}
        self.r2 = json.loads((ROOT / "exp2ar2/ledger.json").read_text())
        self.r2_by_id = {c["case_id"]: c for c in self.r2["cases"]}

    # ---- manuscripts
    def _load(self, path: str):
        if path not in self._papers:
            self._papers[path] = N.number((ROOT / path).read_text(encoding="utf-8"))
        return self._papers[path]

    def paper(self, c: dict, st: str):
        return self._load(c["paths"][st])

    def anchor_paper(self, c: dict, st: str):
        return self._load(c["paths"][R2_STATE[st]])

    # ---- plan
    def cases(self):
        if self.scope == "validation":
            return [self.by_id[x] for x in VALIDATION["evidence_cases"]]
        return list(self.all_cases)

    def matrix_cases(self):
        if self.scope == "validation":
            return [self.by_id[VALIDATION["matrix_case"]]]
        return [c for c in self.all_cases if c["matrix"]]

    def pair_cases(self):
        if self.scope == "validation":
            return [self.by_id[VALIDATION["pair_case"]]]
        return self.matrix_cases()

    def pairs(self, phase: str):
        plan = PAIRS[phase]
        if self.scope == "validation":
            plan = plan[:1] if phase == "large" else plan[:2]
        return plan

    def blind_items(self):
        items = []
        cases = self.cases()
        papers = sorted({c["paper"] for c in cases})
        for c in cases:
            text, valid = self.paper(c, "E0")
            items.append({"id": f"{c['case_id']}::E0", "paper": c["paper"], "case_id": c["case_id"], "family": c["family"],
                          "state": "E0", "kind": "defective", "seed": P.seed_for(c["case_id"], "blind"),
                          "text": text, "valid": valid, "target_lines": c["target_lines"]})
        for p in papers:
            text, valid = self._load(f"exp2b/papers/{p}/E1.tex")
            items.append({"id": f"{p}::clean", "paper": p, "case_id": None, "family": None, "state": "E1",
                          "kind": "clean", "seed": P.seed_for(f"{p}::clean", "blind"), "text": text, "valid": valid,
                          "target_lines": None})
        return items

    def anchor_cases(self):
        ids = [VALIDATION["anchor_case"]] if self.scope == "validation" else ANCHOR_CASES
        return [self.r2_by_id[x] for x in ids]

    def counts(self) -> dict:
        n_models = len(PRIMARY)
        n_pairs = sum(len(self.pairs(ph)) for ph in PAIRS)
        return {"evidence": len(self.cases()) * 3 * n_models,
                "blind": len(self.blind_items()) * n_models,
                "matrix": len(self.matrix_cases()) * 2 * len(P.MATRIX_ARMS) * n_models,
                "pair": n_pairs * len(self.pair_cases()) * 2 * len(P.PAIR_ARMS),
                "anchor": len(self.anchor_cases()) * 4 * n_models}

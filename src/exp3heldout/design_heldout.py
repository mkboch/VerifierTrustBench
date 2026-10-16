"""Experiment 3 held-out trial plan (frozen before any verifier inference).

Cohort: exp3heldout/ledger.json (papers, native cases, E0/E1/E2 variants, mechanical checkers).
Protocol: the frozen Experiment 2B targeted protocol and the repaired 2B-R bounded blind protocol, unchanged.

Model sets (chosen entirely from prior experiments, never from held-out behaviour):
  PRIMARY (5): qwen38_27 strong, qwen36_27 medium, gemma4_12 independent competent family, qwen3_8 weak,
               granite42_30 independent intermediate characterization model.
  BROAD (12):  the full Experiment 2B-broad set, run on a pre-registered 60-case held-out subset.

Pre-registered subsets (seeded, balanced, fixed before inference):
  MATRIX_SUBSET  60 cases (3 per paper) for the six-arm exposure matrix, E0 and E1 states, PRIMARY models.
  BROAD_SUBSET   60 cases for the 12-model replication: E0/E1/E2 targeted + blind E0.
Clean blind controls: 2 per paper per model, with two distinct frozen seeds.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("exp2b", "exp2br", "exp2bbroad", "exp3heldout"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))
import normalize as N  # noqa: E402
import protocol as P  # noqa: E402
import models_broad as MB  # noqa: E402

LEDGER_PATH = ROOT / "exp3heldout/ledger.json"
STATES = ("E0", "E1", "E2")
PRIMARY = ["qwen38_27", "qwen36_27", "gemma4_12", "qwen3_8", "granite42_30"]
BROAD = list(MB.ALL_MODELS)
SUBSET_SEED = 20260918
MATRIX_PER_PAPER = 3
BROAD_SUBSET_N = 60
CLEAN_PER_PAPER = 2

# server phases: models that can be served at the same time on 4x24 GB
PHASES = {
    "large": ["qwen38_27", "qwen36_27"],          # :8097 TP2 + :8098 TP2
    "small": ["qwen3_8", "gemma4_12"],            # :8100 TP1 + :8102 TP2
    "granite42_30": ["granite42_30"],             # :8104 TP4
    "mistral_small32": ["mistral_small32"], "olmo31_32": ["olmo31_32"], "llama33_70awq": ["llama33_70awq"],
    "gptoss_20": ["gptoss_20"], "glm4_32": ["glm4_32"], "exaone45_33": ["exaone45_33"], "seedoss_36": ["seedoss_36"],
}


class Plan:
    def __init__(self):
        self.ledger = json.loads(LEDGER_PATH.read_text())
        self.cases = self.ledger["cases"]
        self.by_id = {c["case_id"]: c for c in self.cases}
        self.papers = self.ledger["papers"]
        self.domains = self.ledger["domains"]
        self.families = sorted({c["family"] for c in self.cases})
        self._text = {}

    # ---- manuscripts
    def _load(self, rel):
        if rel not in self._text:
            self._text[rel] = N.number((ROOT / rel).read_text())
        return self._text[rel]

    def paper_text(self, case, state):
        return self._load(case["paths"][state])

    def clean_text(self, paper):
        return self._load(f"exp3heldout/papers/{paper}/E1.tex")

    # ---- subsets (deterministic)
    def matrix_subset(self):
        rng = random.Random(SUBSET_SEED)
        out = []
        for pid in self.papers:
            pc = sorted([c for c in self.cases if c["paper"] == pid], key=lambda c: c["case_id"])
            byf = {}
            for c in pc:
                byf.setdefault(c["family"], []).append(c)
            fams = sorted(byf)
            rng.shuffle(fams)
            picked = []
            for f in fams:                      # one per family first: maximise family spread
                if len(picked) >= MATRIX_PER_PAPER:
                    break
                picked.append(byf[f][0])
            for c in pc:                        # then fill in case order
                if len(picked) >= MATRIX_PER_PAPER:
                    break
                if c not in picked:
                    picked.append(c)
            out += picked[:MATRIX_PER_PAPER]
        return sorted(out, key=lambda c: c["case_id"])

    def broad_subset(self):
        rng = random.Random(SUBSET_SEED + 1)
        per_paper = max(1, BROAD_SUBSET_N // max(1, len(self.papers)))
        out = []
        for pid in self.papers:
            pc = sorted([c for c in self.cases if c["paper"] == pid], key=lambda c: c["case_id"])
            byf = {}
            for c in pc:
                byf.setdefault(c["family"], []).append(c)
            fams = sorted(byf)
            rng.shuffle(fams)
            picked = [byf[f][0] for f in fams][:per_paper]
            for c in pc:
                if len(picked) >= per_paper:
                    break
                if c not in picked:
                    picked.append(c)
            out += picked[:per_paper]
        rest = [c for c in sorted(self.cases, key=lambda c: c["case_id"]) if c not in out]
        rng.shuffle(rest)
        out += rest[:max(0, BROAD_SUBSET_N - len(out))]
        return sorted(out, key=lambda c: c["case_id"])

    # ---- blind items
    def blind_items(self):
        items = []
        for c in self.cases:
            text, valid = self.paper_text(c, "E0")
            items.append({"id": f"{c['case_id']}::E0", "paper": c["paper"], "domain": c["domain"],
                          "case_id": c["case_id"], "family": c["family"], "state": "E0", "kind": "defective",
                          "seed": P.seed_for(c["case_id"], "blind"), "text": text, "valid": valid,
                          "target_lines": c["target_lines"]})
        for pid in self.papers:
            text, valid = self.clean_text(pid)
            for k in range(1, CLEAN_PER_PAPER + 1):
                items.append({"id": f"{pid}::clean{k}", "paper": pid, "domain": self.domains[pid], "case_id": None,
                              "family": None, "state": "E1", "kind": "clean",
                              "seed": P.seed_for(f"{pid}::clean{k}", "blind"), "text": text, "valid": valid,
                              "target_lines": None})
        return items

    def counts(self):
        return {"papers": len(self.papers), "cases": len(self.cases), "evidence_per_model": len(self.cases) * 3,
                "blind_per_model": len(self.blind_items()),
                "matrix_per_model": len(self.matrix_subset()) * 2 * len(P.MATRIX_ARMS),
                "broad_subset_cases": len(self.broad_subset())}

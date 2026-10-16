#!/usr/bin/env python3
"""verifier_profile — reusable Verification Evidence Profile harness.

Computes, from standardized verifier trial records:
  * information-path class (BLIND_DISCOVERY / CATEGORY_TARGETED / RELATION_LOCALIZED / UPSTREAM_AGENT_SUPPLIED)
  * discovery finding-budget curves: Recall@k, Precision@k, rank of first correct finding
  * evidence responsiveness: E0 / E1 / E2 / full trajectory / transition patterns
  * false-alarm rate on valid relations (1 - E1 clearance), reported explicitly
  * verdict x provenance 2x2 and the full provenance class distribution
  * citation precision, span width, adjacent / unrelated / invalid / empty citation classes
  * technical validity
  * paired discovery-vs-localized contrasts (exact McNemar + Newcombe method-10)

Scoring reuses the FROZEN Experiment 2B/3 scorers; nothing is re-defined here.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal, getcontext
from math import comb
from pathlib import Path

getcontext().prec = 60
ROOT = Path(__file__).resolve().parents[2]
for sub in ("exp2b", "exp2br", "exp2bbroad", "exp3heldout"):
    sys.path.insert(0, str(ROOT / sub))

import scoring as S            # noqa: E402  frozen scorer
import provenance_audit as PA  # noqa: E402  frozen 9-way provenance classifier
import evaluate as EV          # noqa: E402  frozen Wilson / Newcombe helpers

# ---------------------------------------------------------------- information path
BLIND_DISCOVERY = "BLIND_DISCOVERY"
CATEGORY_TARGETED = "CATEGORY_TARGETED"
RELATION_LOCALIZED = "RELATION_LOCALIZED"
UPSTREAM_AGENT_SUPPLIED = "UPSTREAM_AGENT_SUPPLIED"

INFO_PATHS = (BLIND_DISCOVERY, CATEGORY_TARGETED, RELATION_LOCALIZED, UPSTREAM_AGENT_SUPPLIED)


def information_path(rec: dict) -> str:
    """Classify what the verifier was given. Descriptive labels; no ordering is asserted."""
    exp = rec.get("experiment", "")
    arm = rec.get("arm")
    if exp in ("blind",) or rec.get("key", "").startswith("broad_blind"):
        return BLIND_DISCOVERY
    if exp == "matrix" and arm not in (None, "neutral"):
        return UPSTREAM_AGENT_SUPPLIED
    return RELATION_LOCALIZED


# ---------------------------------------------------------------- statistics
def exact_mcnemar(b: int, c: int) -> Decimal:
    n = b + c
    if n == 0:
        return Decimal(1)
    k = min(b, c)
    return min(2 * sum(Decimal(comb(n, i)) for i in range(k + 1)) / (Decimal(2) ** n), Decimal(1))


def paired(a_ok: list, b_ok: list) -> dict:
    """Paired contrast: a vs b. Returns discordance table, Newcombe CI, exact McNemar p."""
    t = EV.paired_table(zip(a_ok, b_ok))
    t["exact_p"] = f"{exact_mcnemar(t['first_only'], t['second_only']):.4E}"
    return t


def rate(x: int, n: int) -> dict:
    return EV.rate(x, n)


# ---------------------------------------------------------------- discovery curves
def discovery_curve(findings: list, case: dict, ledger: dict, valid_ids, ks=(1, 2, 3, 5)) -> dict:
    """Recall@k / Precision@k / rank of first correct finding, from the ORDERED finding list.

    A finding is 'correct' under the frozen strict rule: it cites an existing target line (L), names a token of
    the contradiction (V), and uses the family's vocabulary (R) -- the same conjunction label_defective requires
    for TRUE_DETECTION. Ranks are 1-indexed in the order the model returned them.
    """
    feats = [S.finding_features(f, case, case["blind_tokens"]["E0"], ledger["family_terms"],
                                ledger["generic_flag_terms"], valid_ids, ("allegation",), False)
             for f in findings]
    hit = [bool(x["L"] and x["V"] and x["R"]) for x in feats]
    n = len(findings)
    first = next((i + 1 for i, h in enumerate(hit) if h), None)
    out = {"n_findings": n, "rank_first_correct": first, "any_correct": first is not None,
           "n_correct_findings": sum(hit), "hit_vector": hit}
    for k in ks:
        top = hit[:k]
        out[f"recall_at_{k}"] = bool(any(top))            # >=1 correct in top-k (one target per case)
        out[f"precision_at_{k}"] = (sum(top) / min(k, n)) if n else 0.0
        out[f"n_returned_at_{k}"] = min(k, n)
    return out


# ---------------------------------------------------------------- provenance
PROV_CLASSES = ("GROUNDED", "GROUNDED_VIA_ADJACENT", "UNGROUNDED_VALID_LINES", "INVALID_ONLY", "NO_CITATION")


def provenance_detail(ids, malformed, valid_ids, target_lines) -> dict:
    """Frozen provenance class plus citation-precision detail.

    `status` is the frozen 9-way trial class from exp2br.provenance_audit.classify (GROUNDED, GROUNDED_VIA_ADJACENT,
    UNGROUNDED_VALID_LINES, INVALID_ONLY, NO_CITATION) -- NOT the coarser scoring.provenance status field, which
    reports id validity rather than relation support.
    """
    ids = list(ids or [])
    malformed = list(malformed or [])
    _cats, trial_class = PA.classify(ids, malformed, valid_ids, target_lines or [])
    base = dict(S.provenance(ids, malformed, valid_ids, target_lines))
    base["id_validity_status"] = base.pop("status")
    base["status"] = trial_class
    tgt = set(target_lines or [])
    on_target = sum(1 for i in ids if i in tgt)
    nonexistent = sum(1 for i in ids if i not in valid_ids)
    unrelated_valid = sum(1 for i in ids if i in valid_ids and i not in tgt)
    span = (max(ids) - min(ids) + 1) if ids else 0
    return {**base,
            "n_cited": len(ids),
            "n_on_target": on_target,
            "n_unrelated_valid": unrelated_valid,
            "n_nonexistent": nonexistent,
            "n_malformed": len(malformed or []),
            "citation_precision": (on_target / len(ids)) if ids else None,
            "citation_span": span}


def verdict_provenance_cell(verdict_correct: bool, prov_status: str) -> str:
    supported = prov_status in ("GROUNDED", "GROUNDED_VIA_ADJACENT")
    return ("CORRECT" if verdict_correct else "INCORRECT") + ("_RELATION_SUPPORTED" if supported else "_UNSUPPORTED")


VP_CELLS = ("CORRECT_RELATION_SUPPORTED", "CORRECT_UNSUPPORTED",
            "INCORRECT_RELATION_SUPPORTED", "INCORRECT_UNSUPPORTED")


# ---------------------------------------------------------------- responsiveness
STATES = ("E0", "E1", "E2")


def responsiveness(verdicts: dict) -> dict:
    """verdicts: {'E0':v,'E1':v,'E2':v} -> per-state correctness, trajectory, and failure pattern flags."""
    exp = {"E0": "ISSUE_PRESENT", "E1": "NO_ISSUE", "E2": "ISSUE_PRESENT"}
    ok = {s: (verdicts.get(s) == exp[s]) for s in STATES}
    complete = all(verdicts.get(s) is not None for s in STATES)
    return {**{f"{s}_correct": ok[s] for s in STATES},
            "complete": complete,
            "trajectory": complete and all(ok.values()),
            "MISS_DEFECT": verdicts.get("E0") is not None and verdicts["E0"] != "ISSUE_PRESENT",
            "FALSE_ALARM_ON_REPAIR": verdicts.get("E1") == "ISSUE_PRESENT",
            "MISS_REVERSAL": verdicts.get("E2") is not None and verdicts["E2"] != "ISSUE_PRESENT",
            "pattern": "".join("1" if ok[s] else "0" for s in STATES) if complete else "incomplete"}


def false_alarm_rate(e1_correct: int, e1_n: int) -> dict:
    """Reported explicitly as 1 - E1 clearance, never hidden inside trajectory accuracy."""
    r = rate(e1_n - e1_correct, e1_n)
    r["definition"] = "1 - E1 clearance; proportion of VALID tested relations flagged as defective"
    return r

"""Experiment 2B: frozen outcome definitions, provenance classification and strict blind scorer.

Carried over unchanged in substance from exp2ar2/scoring.py (outcome, source_class, estimability, strict blind
labels). New in 2B: per-line provenance categories, and target support kept separate from verdict validity.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- verdicts


def outcome(verdict: str | None, truth: str, status: str) -> str:
    if status != "OK" or verdict is None:
        return "FAILED"
    if verdict == truth:
        return "CORRECT"
    return "WRONG_UNRESOLVED" if verdict == "UNRESOLVED" else "WRONG_DECISIVE"


def source_class(verdict: str | None, truth: str, status: str) -> str:
    if status != "OK" or verdict is None:
        return "FAILED"
    if verdict == truth:
        return "CORRECT"
    if verdict == "UNRESOLVED":
        return "UNRESOLVED"
    return "DECISIVELY_WRONG"


ESTIMABLE_MIN_N = 20
ESTIMABLE_MIN_CASES = 5


def estimable(n: int, n_cases: int) -> bool:
    return n >= ESTIMABLE_MIN_N and n_cases >= ESTIMABLE_MIN_CASES


# --------------------------------------------------------------------------- provenance

PROVENANCE = ("EXACT", "ADJACENT_BLANK", "NONEXISTENT")


def classify_line(i: int, valid_ids: set[int]) -> str:
    """EXACT: a non-empty line of the manuscript sent. ADJACENT_BLANK: not a content line, but the line
    immediately before or after it is one (e.g. the blank line after a paragraph). NONEXISTENT: otherwise."""
    if i in valid_ids:
        return "EXACT"
    if (i - 1) in valid_ids or (i + 1) in valid_ids:
        return "ADJACENT_BLANK"
    return "NONEXISTENT"


def provenance(ids: list[int], malformed: list, valid_ids: set[int], target_lines: list[int] | None) -> dict:
    """Provenance of one set of cited line IDs.

    status        VALID (all exact), OFF_BY_ONE (some adjacent-blank, none nonexistent/malformed),
                  INVALID (any nonexistent or malformed), EMPTY (no IDs)
    target_support (when target_lines given) SUPPORTED: an EXACT id is a target line; SUPPORTED_ADJACENT: only
                  after mapping adjacent-blank ids to their neighbours; UNSUPPORTED otherwise.
    """
    cats = [classify_line(i, valid_ids) for i in ids]
    if not ids and not malformed:
        status = "EMPTY"
    elif malformed or "NONEXISTENT" in cats:
        status = "INVALID"
    elif "ADJACENT_BLANK" in cats:
        status = "OFF_BY_ONE"
    else:
        status = "VALID"
    out = {"status": status, "n_ids": len(ids), "n_malformed": len(malformed),
           "counts": {c: cats.count(c) for c in PROVENANCE}}
    if target_lines is not None:
        tl = set(target_lines)
        exact = {i for i, c in zip(ids, cats) if c == "EXACT"}
        adj = set()
        for i, c in zip(ids, cats):
            if c == "ADJACENT_BLANK":
                adj |= {j for j in (i - 1, i + 1) if j in valid_ids}
        out["target_support"] = ("SUPPORTED" if exact & tl else "SUPPORTED_ADJACENT" if adj & tl else "UNSUPPORTED")
    return out


# --------------------------------------------------------------------------- blind

BLIND_LABELS = ("TRUE_DETECTION", "PARTIAL_DETECTION", "AMBIGUOUS_REVIEW", "MISSED")
BASE_LABELS = ("FALSE_POSITIVE", "TARGET_TOUCHED", "NO_FLAG")


def normalize_text(s: str | None) -> str:
    s = (s or "").replace("\\%", "%").replace("−", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().lower()


def _any(patterns, text):
    return any(re.search(p, text, re.I) for p in patterns)


def finding_features(f, case, tokens, family_terms, generic_terms, valid_ids, text_fields, allow_adjacent=False):
    text = normalize_text(" ".join(f.get(k) or "" for k in text_fields))
    ids = set()
    for i in f.get("evidence_line_ids") or []:
        c = classify_line(i, valid_ids)
        if c == "EXACT":
            ids.add(i)
        elif c == "ADJACENT_BLANK" and allow_adjacent:
            ids |= {j for j in (i - 1, i + 1) if j in valid_ids}
    return {"L": bool(ids & set(case["target_lines"])), "V": _any(tokens, text),
            "R": any(t in text for t in family_terms[case["family"]]), "G": any(t in text for t in generic_terms)}


def label_defective(findings, case, ledger, valid_ids, text_fields=("allegation",), allow_adjacent=False):
    """TRUE_DETECTION: some finding cites an existing target line (L), names a token of this contradiction (V)
    and uses its family's vocabulary (R). AMBIGUOUS_REVIEW: V and R without L. PARTIAL_DETECTION: L with V or R
    or a generic objection. MISSED otherwise. Only TRUE_DETECTION counts as discovery."""
    feats = [finding_features(f, case, case["blind_tokens"]["E0"], ledger["family_terms"],
                              ledger["generic_flag_terms"], valid_ids, text_fields, allow_adjacent) for f in findings]
    if any(x["L"] and x["V"] and x["R"] for x in feats):
        lab = "TRUE_DETECTION"
    elif any(x["V"] and x["R"] and not x["L"] for x in feats):
        lab = "AMBIGUOUS_REVIEW"
    elif any(x["L"] and (x["V"] or x["R"] or x["G"]) for x in feats):
        lab = "PARTIAL_DETECTION"
    else:
        lab = "MISSED"
    return lab, feats


def label_clean(findings, case, ledger, valid_ids, text_fields=("allegation",), allow_adjacent=False):
    """Blind audit of an unmodified manuscript scored against one case relation of that paper.
    FALSE_POSITIVE: a finding with L, V (E1 tokens) and R. TARGET_TOUCHED: L only. NO_FLAG otherwise."""
    feats = [finding_features(f, case, case["blind_tokens"]["E1"], ledger["family_terms"],
                              ledger["generic_flag_terms"], valid_ids, text_fields, allow_adjacent) for f in findings]
    if any(x["L"] and x["V"] and x["R"] for x in feats):
        return "FALSE_POSITIVE", feats
    if any(x["L"] for x in feats):
        return "TARGET_TOUCHED", feats
    return "NO_FLAG", feats


SENSITIVITY_TEXT_FIELDS = ("allegation", "evidence_summary")

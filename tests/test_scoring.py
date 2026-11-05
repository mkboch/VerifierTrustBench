"""The frozen scoring layer: verdict outcomes, provenance classification, and the strict blind
labels. Provenance is scored separately from the verdict, which is what makes the
verdict x provenance dissociation measurable; these tests pin that separation down."""
from __future__ import annotations
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC / "exp2b"))
import scoring as S  # noqa: E402


# ---------------------------------------------------------------- verdict outcome

@pytest.mark.parametrize("verdict,truth,status,want", [
    ("ISSUE_PRESENT", "ISSUE_PRESENT", "OK", "CORRECT"),
    ("NO_ISSUE", "NO_ISSUE", "OK", "CORRECT"),
    ("NO_ISSUE", "ISSUE_PRESENT", "OK", "WRONG_DECISIVE"),
    ("UNRESOLVED", "ISSUE_PRESENT", "OK", "WRONG_UNRESOLVED"),
    (None, "ISSUE_PRESENT", "OK", "FAILED"),
    ("ISSUE_PRESENT", "ISSUE_PRESENT", "TRUNCATED", "FAILED"),
])
def test_outcome(verdict, truth, status, want):
    assert S.outcome(verdict, truth, status) == want


def test_a_technically_failed_generation_is_never_scored_correct():
    assert S.outcome("ISSUE_PRESENT", "ISSUE_PRESENT", "LENGTH") == "FAILED"
    assert S.source_class("ISSUE_PRESENT", "ISSUE_PRESENT", "LENGTH") == "FAILED"


# ---------------------------------------------------------------- line provenance

VALID = {10, 11, 12, 20, 21}


@pytest.mark.parametrize("line,want", [
    (10, "EXACT"), (21, "EXACT"),
    (13, "ADJACENT_BLANK"),   # blank line right after a content line
    (19, "ADJACENT_BLANK"),
    (50, "NONEXISTENT"),
])
def test_classify_line(line, want):
    assert S.classify_line(line, VALID) == want


def test_provenance_status_ladder():
    assert S.provenance([10, 11], [], VALID, None)["status"] == "VALID"
    assert S.provenance([10, 13], [], VALID, None)["status"] == "OFF_BY_ONE"
    assert S.provenance([10, 99], [], VALID, None)["status"] == "INVALID"
    assert S.provenance([10], ["L00abc"], VALID, None)["status"] == "INVALID"
    assert S.provenance([], [], VALID, None)["status"] == "EMPTY"


def test_target_support_requires_citing_the_tested_relation():
    """A citation that is valid but lands on an unrelated line is UNSUPPORTED. This is the
    distinction between 'cited something real' and 'cited the thing under test'."""
    assert S.provenance([20], [], VALID, [20])["target_support"] == "SUPPORTED"
    assert S.provenance([10], [], VALID, [20])["target_support"] == "UNSUPPORTED"
    assert S.provenance([19], [], VALID, [20])["target_support"] == "SUPPORTED_ADJACENT"


def test_verdict_and_provenance_are_independent_axes():
    """A correct verdict can carry unsupported provenance and vice versa; neither implies the other."""
    correct_unsupported = (S.outcome("ISSUE_PRESENT", "ISSUE_PRESENT", "OK"),
                           S.provenance([10], [], VALID, [20])["target_support"])
    wrong_supported = (S.outcome("NO_ISSUE", "ISSUE_PRESENT", "OK"),
                       S.provenance([20], [], VALID, [20])["target_support"])
    assert correct_unsupported == ("CORRECT", "UNSUPPORTED")
    assert wrong_supported == ("WRONG_DECISIVE", "SUPPORTED")


# ---------------------------------------------------------------- strict blind labels

LEDGER = {"family_terms": {"arithmetic": ["arithmetic", "sum", "does not add"]},
          "generic_flag_terms": ["unclear", "inconsistent"]}
CASE = {"family": "arithmetic", "target_lines": [20],
        "blind_tokens": {"E0": ["57.20"], "E1": ["44.34"]}}


def finding(line, text):
    return {"evidence_line_ids": [line], "allegation": text}


def test_true_detection_needs_line_value_and_family_vocabulary():
    lab, _ = S.label_defective([finding(20, "the arithmetic is wrong: 57.20 does not add up")],
                               CASE, LEDGER, VALID, allow_adjacent=False)
    assert lab == "TRUE_DETECTION"


def test_right_line_without_the_value_is_only_partial():
    lab, _ = S.label_defective([finding(20, "something here is unclear")],
                               CASE, LEDGER, VALID)
    assert lab == "PARTIAL_DETECTION"


def test_right_complaint_on_the_wrong_line_is_ambiguous_not_detection():
    lab, _ = S.label_defective([finding(10, "the arithmetic for 57.20 does not add up")],
                               CASE, LEDGER, VALID)
    assert lab == "AMBIGUOUS_REVIEW"


def test_unrelated_finding_is_missed():
    lab, _ = S.label_defective([finding(10, "the prose could be tightened")], CASE, LEDGER, VALID)
    assert lab == "MISSED"


def test_no_findings_is_missed():
    lab, _ = S.label_defective([], CASE, LEDGER, VALID)
    assert lab == "MISSED"


def test_only_true_detection_counts_as_discovery():
    """The strict labels exist so that 'nearly found it' is never counted as discovery."""
    assert S.BLIND_LABELS[0] == "TRUE_DETECTION"
    for text in ("something here is unclear", "the prose could be tightened"):
        lab, _ = S.label_defective([finding(20, text)], CASE, LEDGER, VALID)
        assert lab != "TRUE_DETECTION"


def test_clean_control_scoring_is_available_and_distinct():
    """False alarms on unmodified text are scored by a separate function."""
    assert S.label_clean is not S.label_defective
    lab, _ = S.label_clean([], CASE, LEDGER, VALID)
    assert lab in S.BASE_LABELS

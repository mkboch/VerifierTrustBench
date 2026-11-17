"""AI-session assessments must never again be presented as human judgements.

This repository described six language-model chat sessions as six human reviewers, and
built a measured scorer false-negative rate, human inter-rater reliability statistics and
a scorer-validity verdict on top of that description. The description was wrong and the
conclusions have been withdrawn.

These tests make the misstatement unrepeatable: the words cannot come back in public text,
the data file must declare what it is, and the withdrawn conclusions must stay withdrawn.
"""
from __future__ import annotations
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "docs/data"

#: phrases that assert human provenance for the scorer assessments
HUMAN_CLAIMS = [
    "six human reviewers", "six reviewers", "six colleagues", "six named colleagues",
    "human reviewers rated", "human adjudication", "human inter-rater",
    "human validation", "human-validated", "human scorer audit", "human volunteers",
    "independent human", "six independent", "human annotation reliability",
    "proven human consensus", "human scorer-corrected",
]

#: files a reader meets; the changelog is exempt because it must quote the old claim
PUBLIC = ["README.md", "docs/index.html", "docs/assets/app.js",
          "docs/data/DATA_DICTIONARY.md", "docs/data/scorer_audit_items.json",
          "docs/data/fair_scoring_support.json", "docs/data/research_results.json",
          "docs/data/robustness.json"]


def read(rel):
    p = ROOT / rel
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def flat(rel):
    """Whitespace-normalised, so a phrase that wraps across lines is still found."""
    return " ".join(read(rel).split())


@pytest.mark.parametrize("rel", PUBLIC)
def test_no_public_file_claims_human_annotation(rel):
    """The claim may appear only inside an explicit correction or negation."""
    low = flat(rel).lower()
    bad = []
    for phrase in HUMAN_CLAIMS:
        for m in re.finditer(re.escape(phrase), low):
            window = low[max(0, m.start() - 260):m.end() + 160]
            negated = any(w in window for w in (
                "not ", "never", "previously described", "was incorrect", "corrected",
                "withdrawn", "no longer", "rather than", "instead of", "wrong"))
            if not negated:
                bad.append(f"{phrase!r} @ {m.start()}")
    assert bad == [], f"{rel} asserts human annotation: {bad}"


def test_the_assessment_file_declares_what_it_is():
    d = json.loads(read("docs/data/scorer_audit_items.json"))
    assert "provenance" in d and "not_human_validation" in d
    prov = d["provenance"].lower()
    assert "chatgpt" in prov and "claude" in prov
    assert "not verified" in prov or "not_verified" in prov
    for key in ("targeted", "blind"):
        item = d["audits"][key]["items"][0]
        assert "n_sessions" in item, f"{key} items still use a reviewer field"
        assert "n_reviewers" not in item


def test_the_scorer_validity_verdict_stays_withdrawn():
    v = json.loads(read("docs/data/fair_scoring_support.json"))["scorer_audit"]["verdict"]
    assert v["status"] == "WITHDRAWN_2026_11_16"
    # the superseded conclusion is retained, not deleted
    assert "superseded_conclusion_retained_for_provenance" in v


def test_correction_scenarios_are_labelled_exploratory():
    sc = json.loads(read("docs/data/research_results.json"))["scorer_correction_scenarios"]
    assert sc["status"] == "EXPLORATORY_NOT_EMPIRICALLY_SUPPORTED"
    assert "PROVENANCE_CORRECTION_2026_11_16" in sc


def test_the_gold_label_exercise_is_flagged_not_asserted():
    gl = json.loads(read("docs/data/research_results.json"))["gold_label_validation"]
    assert gl["status"] == "PROVENANCE_UNCONFIRMED_PENDING_AUTHOR"


def test_the_changelog_records_the_correction_with_its_date():
    cl = flat("CHANGELOG.md")
    assert "16 November 2026" in cl
    assert "Annotation provenance clarification" in cl
    low = cl.lower()
    assert "three chatgpt" in low and "three claude" in low
    assert "not human-participant annotations" in low
    # the original misstatement must be quoted, not erased
    assert "previously described" in low


def test_no_consent_or_irb_claim_survives_in_public_text():
    for rel in PUBLIC + ["CHANGELOG.md"]:
        low = read(rel).lower()
        for phrase in ("irb approval", "ethics approval", "consent form",
                       "informed consent", "institutional review board approved"):
            assert phrase not in low, f"{rel} claims {phrase!r}"


def test_raw_assessment_counts_were_not_altered_by_the_correction():
    """Relabelling must not change an outcome."""
    d = json.loads(read("docs/data/scorer_audit_items.json"))
    t, b = d["audits"]["targeted"], d["audits"]["blind"]
    assert (t["n_items"], t["total_judgments"]) == (30, 180)
    assert (b["n_items"], b["total_judgments"]) == (60, 360)
    LV = ["Yes", "Partially", "No", "Ambiguous / Cannot determine"]
    tot = {k: sum(i["counts"][k] for i in t["items"]) for k in LV}
    assert tot == {"Yes": 41, "Partially": 11, "No": 124,
                   "Ambiguous / Cannot determine": 4}

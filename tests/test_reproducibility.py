"""The public release must actually reproduce the published results, from itself alone.

These tests run the shipped reproduction end to end and check the things that would make
a reproduction claim hollow: that the data is intact, that the estimators are the frozen
ones, and that no private material rides along with the outcomes.
"""
from __future__ import annotations
import json
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "docs/data"
sys.path.insert(0, str(ROOT))

from reproducibility import contrasts as C, data as D  # noqa: E402
from reproducibility.estimators import phi_inv, rates  # noqa: E402


def test_published_data_matches_its_checksums():
    rows, ok = D.verify_checksums()
    bad = [r for r in rows if r[1] != "PASS"]
    assert ok, f"released data does not match SHA256SUMS.txt: {bad}"
    assert len(rows) >= 7, "the manifest covers fewer files than the release ships"


def test_the_cell_table_is_structurally_sound():
    doc, cells = D.load_cells()
    assert D.validate_cells(doc, cells) == []
    assert len(cells) == 1440
    assert doc["n_clusters"] == 21 and doc["n_relations"] == 60


def test_the_log_linear_correction_is_unconditional():
    """Applying it only at the boundaries is a different, biased estimator."""
    r = rates(10, 100, 5, 100)
    assert r["dprime"] == pytest.approx(phi_inv(10.5 / 101) - phi_inv(5.5 / 101), abs=1e-12)
    # and at a boundary it must not blow up
    assert abs(rates(0, 100, 0, 100)["dprime"]) < 1e-9


def test_pooled_and_system_balanced_are_not_the_same_estimand():
    """If these ever coincided everywhere, one of them would be computed wrongly."""
    doc, cells = D.load_cells()
    ow = [s["id"] for s in doc["systems"] if s["id"] != "gpt-5.2"]
    p = C.contrast(cells, "category", "binary", ow, "dprime", "pooled", draws=200)
    b = C.contrast(cells, "category", "binary", ow, "dprime", "system_balanced", draws=200)
    assert p["point"] != pytest.approx(b["point"], abs=1e-6)
    # the published case where they disagree in SIGN
    assert p["point"] < 0 < b["point"]


def test_eligibility_drops_a_cell_from_both_sides_or_neither():
    doc, cells = D.load_cells()
    ow = [s["id"] for s in doc["systems"] if s["id"] != "gpt-5.2"]
    pairs = C.eligible(cells, "relation", "binary", ow)
    for p in pairs:
        assert p["a"]["e0_scoreable"] and p["a"]["e1_scoreable"]
        assert p["b"]["e0_scoreable"] and p["b"]["e1_scoreable"]
    assert len(pairs) == 298


def test_a_rung_against_itself_is_exactly_zero():
    doc, cells = D.load_cells()
    ow = [s["id"] for s in doc["systems"] if s["id"] != "gpt-5.2"]
    r = C.contrast(cells, "binary", "binary", ow, "balanced_accuracy", "pooled", draws=100)
    assert r["point"] == pytest.approx(0.0, abs=1e-12)
    assert not r["excludes_zero"]


def test_verify_all_runs_clean_from_the_release():
    """The headline claim of the release, executed."""
    out = ROOT / ".pytest_repro_out"
    r = subprocess.run([sys.executable, "-m", "reproducibility.verify_all",
                        "--out", str(out), "--no-figures"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    summary = json.loads((out / "RECONCILIATION.json").read_text())
    assert summary["failed"] == 0, summary["failures"]
    assert summary["passed"] == summary["assertions_checked"]
    assert summary["assertions_checked"] >= 140
    assert summary["exact_frozen_bootstrap"] is True
    # discrepancies are REPORTED, never silently reconciled
    assert summary["manuscript_discrepancies_reported"] >= 1


def test_no_released_file_names_a_third_party_manuscript():
    arxiv = re.compile(r"\b(?:19|20|21|22|23|24|25|26|27)\d\d\.\d{4,5}\b")
    for f in sorted(DATA.glob("*.json")):
        m = arxiv.search(f.read_text())
        assert m is None, f"{f.name} contains an arXiv identifier {m.group(0)!r}"


def test_human_review_data_is_counts_only():
    doc = json.loads((DATA / "scorer_audit_items.json").read_text())
    raw = (DATA / "scorer_audit_items.json").read_text()
    assert "Reviewer_" not in raw, "a reviewer identifier reached the public data"
    assert '"notes"' not in raw, "free-text reviewer notes reached the public data"
    for key in ("targeted", "blind"):
        for item in doc["audits"][key]["items"]:
            assert set(item["counts"]) == {
                "Yes", "Partially", "No", "Ambiguous / Cannot determine"}
            assert sum(item["counts"].values()) == item["n_reviewers"]
    # the reviewer-axis statistics must be declared unrecomputable, not quietly omitted
    assert "retained_audited_aggregates" in doc


def test_the_scorer_correction_scenarios_stay_distinct():
    """The manuscript and an earlier public aggregate quote DIFFERENT scenarios."""
    rr = json.loads((DATA / "research_results.json").read_text())
    sc = rr["scorer_correction_scenarios"]
    assert set(sc["scenarios"]) == {"one_sided_strict", "one_sided_with_partial",
                                    "symmetric_strict", "symmetric_with_partial"}
    w = sc["which_scenario_the_manuscript_quotes"]
    assert w["conservative_one_sided"] != w["earlier_public_aggregate_used"]
    assert "modelled" in sc["symmetric_scenarios_are_modelled"].lower()
    # the E1 near misses were never audited; a symmetric figure must say so
    assert "never audited" in sc["symmetric_scenarios_are_modelled"].lower() \
        or "NEVER AUDITED" in sc["symmetric_scenarios_are_modelled"]


def test_every_manuscript_macro_declares_a_reproduction_route():
    idx = json.loads((DATA / "manuscript_results_index.json").read_text())
    assert idx["n_macros"] >= 300
    allowed = {"recomputable", "audited_aggregate", "restricted", "mixed"}
    for macro, e in idx["entries"].items():
        assert e["reproduction_route"] in allowed, (macro, e["reproduction_route"])
        assert e["canonical_source"], f"{macro} has no canonical source"

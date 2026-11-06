"""The public release must actually reproduce the published results, from itself alone.

These tests run the shipped reproduction end to end and check the things that would make
a reproduction claim hollow: that the data is intact, that the estimators are the frozen
ones, and that no private material rides along with the outcomes.
"""
from __future__ import annotations
import csv
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
    # The corrected manuscript agrees with the frozen record, so the CURRENT run reports
    # none. The ten found against the superseded draft are preserved in their own report
    # rather than deleted, which is what keeps "zero" from meaning "suppressed".
    assert summary["current_manuscript_discrepancies"] == 0
    assert summary["historical_discrepancies_archived"] == 10


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


# --------------------------------------------- versioned manuscript targets


def test_the_active_targets_are_versioned_and_discrepancy_free():
    """The corrected manuscript must agree with the frozen record, and say which it is."""
    t = json.loads((ROOT / "reproducibility/manuscript_targets.json").read_text())
    assert t.get("manuscript_version") == "2026-11-05-corrected"
    assert t["manuscript_vs_canonical_discrepancies"]["items"] == [], (
        "the active target set still records discrepancies against the frozen record")


def test_the_superseded_draft_and_its_ten_discrepancies_are_archived():
    """Resolved corrections stay auditable. They are archived, never deleted."""
    a = json.loads((ROOT / "reproducibility/manuscript_targets_archive.json").read_text())
    assert a["status"] == "superseded"
    ids = [d["id"] for d in a["discrepancies"]["items"]]
    assert ids == [f"D{i}" for i in range(1, 11)], ids
    for d in a["discrepancies"]["items"]:
        assert d["where"] and d["manuscript"] is not None and d["canonical"] is not None
        assert d["why"], f"{d['id']} has no explanation"
    # the superseded values themselves are kept, not just their labels
    assert "superseded_draft_targets" in a
    assert a["superseded_draft_targets"]["ladder_e0"][0]["n"] == 297, (
        "the draft's uniform 297 denominator is not preserved in the archive")


def test_no_analysis_module_reads_the_archive():
    for name in ("estimators.py", "bootstrap.py", "contrasts.py", "data.py"):
        f = ROOT / "reproducibility" / name
        if f.exists():
            assert "archive" not in f.read_text().lower()


def test_the_checker_fails_when_a_current_target_disagrees():
    """A checker that cannot fail proves nothing.

    Reintroduce the old D3 error -- 147 binary E0 hits instead of 148 -- into a copy of
    the targets and assert the run exits non-zero and names the offending assertion.
    """
    import tempfile
    t = json.loads((ROOT / "reproducibility/manuscript_targets.json").read_text())
    for row in t["ladder_e0"]:
        if row["rung"] == "binary":
            row["hits"] = 147
    d = pathlib.Path(tempfile.mkdtemp())
    bad = d / "bad_targets.json"
    bad.write_text(json.dumps(t))
    r = subprocess.run([sys.executable, "-m", "reproducibility.verify_all",
                        "--targets", str(bad), "--out", str(d / "out"),
                        "--draws", "200", "--no-figures"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0, "the checker passed a target that disagrees with the data"
    assert "binary E0 hits" in r.stdout, r.stdout[-2000:]


def test_historical_discrepancies_are_reported_separately_from_current_ones():
    out = ROOT / ".pytest_hist_out"
    r = subprocess.run([sys.executable, "-m", "reproducibility.verify_all",
                        "--out", str(out), "--draws", "200", "--no-figures"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]
    summary = json.loads((out / "RECONCILIATION.json").read_text())
    assert summary["current_manuscript_discrepancies"] == 0
    assert summary["historical_discrepancies_archived"] == 10
    assert summary["manuscript_version"] == "2026-11-05-corrected"
    hist = json.loads((out / "HISTORICAL_DISCREPANCIES.json").read_text())
    assert hist["n"] == 10
    assert (out / "HISTORICAL_DISCREPANCIES.md").exists()
    # the two must not be conflated: no historical id appears in the current run's rows
    rows = list(csv.DictReader(open(out / "RECONCILIATION.csv")))
    assert not [r_ for r_ in rows if r_["status"] == "DISCREPANCY"]


def test_paired_and_marginal_targets_are_both_present_and_distinct():
    t = json.loads((ROOT / "reproducibility/manuscript_targets.json").read_text())
    paired = t["relation_to_verdict_paired_pooled"]
    marginal = t["open_weight_raw_vs_fair"]["marginal_relation_to_verdict"]
    assert paired["n"] == 298 and marginal["relation"]["n"] == 299
    assert abs(paired["raw_difference_pp"] - marginal["raw_difference_pp"]) > 0.4

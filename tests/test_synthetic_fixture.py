"""The one data file this release ships must be, and must keep saying it is, synthetic.

A code release that quietly starts shipping measured outcomes is the failure mode these
tests exist to prevent. They check the markers that let a reader tell the difference, and
they check that the fixture is regenerable rather than hand-edited.
"""
from __future__ import annotations
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/data/synthetic_demo_cells.json"
DOC = json.loads(FIXTURE.read_text())


def test_the_fixture_declares_itself_synthetic():
    assert DOC["synthetic"] is True
    assert "warning" in DOC and len(DOC["warning"]) > 100
    w = DOC["warning"].lower()
    for phrase in ("random number generator", "nothing here is a measurement",
                   "do not cite"):
        assert phrase in w, f"the warning no longer says {phrase!r}"
    assert "not_experimental_evidence" in DOC


def test_the_demo_systems_match_nothing_real():
    for s in DOC["systems"]:
        assert s["id"].startswith("demo_system_"), s["id"]
        assert s["label"].startswith("Demo system "), s["label"]


def test_the_fixture_is_the_only_data_file():
    data = sorted(p.name for p in (ROOT / "docs/data").glob("*")
                  if p.suffix in {".json", ".csv"})
    # The release now ships the study's outcome data as well. What must stay true is that
    # exactly ONE file declares itself synthetic, so fabricated numbers can never be
    # mistaken for measured ones.
    synthetic = []
    for name in data:
        try:
            doc = json.loads((ROOT / "docs/data" / name).read_text())
        except (ValueError, OSError):
            continue
        if isinstance(doc, dict) and doc.get("synthetic") is True:
            synthetic.append(name)
    assert synthetic == ["synthetic_demo_cells.json"], synthetic


def test_the_fixture_carries_outcomes_and_nothing_else():
    """Every value must be a short label, a 0/1 outcome or null. A finding, a rationale or
    a cited line would fail this on length alone."""
    assert set(DOC["fields"]) == {
        "system", "rung", "cluster", "relation", "family", "domain",
        "e0_scoreable", "e1_scoreable", "e0_hit", "e1_false_alarm", "e0_prov_gated"}
    for row in DOC["cells"]:
        assert len(row) == len(DOC["fields"])
        for v in row:
            if v is None:
                continue
            if isinstance(v, int):
                assert 0 <= v <= 1, f"a non-binary outcome in the fixture: {v}"
            else:
                assert isinstance(v, str) and len(v) <= 24, f"long string: {v[:60]!r}"


def test_no_arxiv_identifier_or_real_identifier_appears():
    import re
    raw = FIXTURE.read_text()
    assert not re.search(r"\b\d{4}\.\d{4,5}\b", raw), "something shaped like an arXiv id"
    assert "qwen" not in raw.lower() and "gemma" not in raw.lower()
    assert "granite" not in raw.lower() and "gpt-" not in raw.lower()


def test_the_fixture_regenerates_byte_for_byte():
    """It is generated, not curated. If someone hand-edits it, this fails."""
    before = FIXTURE.read_bytes()
    r = subprocess.run([sys.executable, str(ROOT / "tools/make_synthetic_demo.py")],
                       capture_output=True, text=True, cwd=ROOT)
    after = FIXTURE.read_bytes()
    try:
        assert r.returncode == 0, r.stdout + r.stderr
        assert after == before, "the fixture on disk is not what the generator produces"
    finally:
        FIXTURE.write_bytes(before)

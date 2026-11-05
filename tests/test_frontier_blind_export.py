"""The GPT-5.2 blind E0 export bug must not come back.

Commit fd4b291f exported GPT-5.2 blind E0 outcomes with manuscript-level deduplication.
The E0 runner issued one blind request PER RELATION; keying by manuscript kept one
response per manuscript and scored it against all of that manuscript's relations. The
published blind E0 total was 2/60 instead of 18/60.

The audit that shipped it ran 151 assertions and passed, because GPT-5.2 was excluded
from every cell-level test. These tests close that gap. They check the released table
against the CANONICAL frontier aggregate and against structural properties of the data,
not against a copied constant, so a future regression cannot be papered over by editing an
expected value.
"""
from __future__ import annotations
import collections
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reproducibility import contrasts as C, data as D  # noqa: E402

RUNG_KEY = {"blind": "BLIND_FINDING_LIST",
            "category": "CATEGORY_TARGETED_FINDING_LIST",
            "relation": "RELATION_TARGETED_FINDING_LIST",
            "binary": "RELATION_LOCALIZED_BINARY_VERDICT"}


@pytest.fixture(scope="module")
def cells():
    return D.load_cells()[1]


@pytest.fixture(scope="module")
def canonical():
    rr = json.loads((ROOT / "docs/data/research_results.json").read_text())
    return rr["frontier"]["openai"]["rungs"]


def test_cell_table_agrees_with_the_canonical_frontier_aggregate(cells, canonical):
    """Two independently derived files must tell the same story.

    research_results.json carries the canonical per-rung totals; fair_scoring_cells.json
    carries the per-cell outcomes they must sum to. The shipped bug made these two
    disagree -- 18 in one file, 2 in the other -- and nothing noticed.
    """
    for rung, r in ((r["rung"], r) for r in C.ladder(cells, ["gpt-5.2"])):
        ck = canonical[RUNG_KEY[rung]]
        assert r["hits"] == ck["detected"], (
            f"{rung}: cell table has {r['hits']} E0 hits, canonical aggregate has "
            f"{ck['detected']}")
        assert r["n_e0"] == ck["n_scored"], (
            f"{rung}: cell table has {r['n_e0']} scoreable, canonical has {ck['n_scored']}")


def test_blind_e0_outcomes_are_not_deduplicated_by_manuscript(cells):
    """The signature of the bug: blind E0 outcomes constant within every manuscript.

    When one response is scored against all of a manuscript's relations, every relation of
    that manuscript gets the same outcome. Real per-relation responses vary. This asserts
    variation exists, which no amount of adjusting an expected total can fake.
    """
    blind = [c for c in cells if c["system"] == "gpt-5.2" and c["rung"] == "blind"
             and c["e0_scoreable"]]
    assert len(blind) == 60
    by_cluster = collections.defaultdict(set)
    for c in blind:
        by_cluster[c["cluster"]].add(c["e0_hit"])
    varying = [k for k, v in by_cluster.items() if len(v) > 1]
    assert varying, (
        "every manuscript's blind E0 outcomes are identical across its relations, which is "
        "what manuscript-level deduplication produces")
    # with the bug the total collapses; with per-relation scoring it does not
    assert sum(c["e0_hit"] for c in blind) == 18


def test_each_gpt_blind_cell_is_independent_of_its_neighbours(cells):
    """A manuscript whose relations all share one response cannot have 4 distinct answers."""
    blind = [c for c in cells if c["system"] == "gpt-5.2" and c["rung"] == "blind"]
    per_cluster = collections.Counter(c["cluster"] for c in blind)
    assert max(per_cluster.values()) > 1, "test data has no multi-relation manuscript"
    distinct = sum(1 for k, v in collections.defaultdict(set,
                   {k: {c["e0_hit"] for c in blind if c["cluster"] == k}
                    for k in per_cluster}).items() if len(v) > 1)
    assert distinct >= 5, (
        f"only {distinct} manuscripts show differing blind E0 outcomes across their "
        "relations; manuscript-level deduplication would give 0")


@pytest.mark.parametrize("rung,hits,fas", [
    ("blind", 18, 0), ("category", 32, 1), ("relation", 25, 0), ("binary", 39, 2)])
def test_gpt_rung_totals(cells, rung, hits, fas):
    r = {x["rung"]: x for x in C.ladder(cells, ["gpt-5.2"])}[rung]
    assert (r["hits"], r["false_alarms"], r["n_e0"], r["n_e1"]) == (hits, fas, 60, 60)


def test_the_two_weightings_coincide_for_a_single_system(cells):
    """GPT-5.2 is one system. If pooled and system-balanced ever differ for it, one of the
    two estimands is computed wrongly."""
    for metric in ("balanced_accuracy", "dprime"):
        p = C.contrast(cells, "relation", "binary", ["gpt-5.2"], metric, "pooled", draws=200)
        b = C.contrast(cells, "relation", "binary", ["gpt-5.2"], metric, "system_balanced",
                       draws=200)
        assert p["point"] == pytest.approx(b["point"], abs=1e-12)


def test_the_correction_did_not_touch_any_other_system(cells):
    """Open-weight totals are unchanged by the frontier fix."""
    ow = [s for s in {c["system"] for c in cells} if s != "gpt-5.2"]
    lad = {r["rung"]: r for r in C.ladder(cells, sorted(ow))}
    assert (lad["blind"]["hits"], lad["blind"]["n_e0"]) == (35, 299)
    assert (lad["category"]["hits"], lad["category"]["n_e0"]) == (66, 297)
    assert (lad["relation"]["hits"], lad["relation"]["n_e0"]) == (60, 299)
    assert (lad["binary"]["hits"], lad["binary"]["n_e0"]) == (148, 299)


def test_paired_and_marginal_raw_effects_are_not_interchangeable(cells):
    """They use different denominators and must never be quoted for one another."""
    ow = sorted(s for s in {c["system"] for c in cells} if s != "gpt-5.2")
    pairs = C.eligible(cells, "relation", "binary", ow)
    paired = 100 * (sum(p["b"]["e0_hit"] for p in pairs)
                    - sum(p["a"]["e0_hit"] for p in pairs)) / len(pairs)
    lad = {r["rung"]: r for r in C.ladder(cells, ow)}
    marginal = 100 * (lad["binary"]["sensitivity"] - lad["relation"]["sensitivity"])
    assert len(pairs) == 298 and lad["relation"]["n_e0"] == 299
    assert paired == pytest.approx(29.8658, abs=5e-4)
    assert marginal == pytest.approx(29.4314, abs=5e-4)
    assert abs(paired - marginal) > 0.4, "the two estimands have collapsed together"

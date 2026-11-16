"""Youden's J, the metric-scale decomposition, and the rung ordering.

A raw detection difference and a balanced-accuracy difference are not on the same scale.
Because balanced accuracy averages sensitivity and specificity, a difference in it is
exactly half a difference in Youden's J:

    dBA = (dTPR - dFPR) / 2 = dJ / 2

So the gap between a raw difference and a balanced-accuracy difference has two parts: the
false-alarm penalty, which is a real empirical cost, and the division by two, which is
arithmetic. Reporting the whole gap as a false-alarm effect overstates it roughly
fourfold. These tests pin the identity and the split so the claim cannot drift.
"""
from __future__ import annotations
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reproducibility import contrasts as C, data as D  # noqa: E402
from reproducibility.estimators import identity_check, rates  # noqa: E402


@pytest.fixture(scope="module")
def setup():
    doc, cells = D.load_cells()
    return cells, [s["id"] for s in doc["systems"] if s["id"] != "gpt-5.2"]


def test_youden_j_is_exactly_twice_balanced_accuracy_minus_one(setup):
    cells, ow = setup
    for r in C.ladder(cells, ow) + C.ladder(cells, ["gpt-5.2"]):
        assert identity_check(r) < 1e-12, f"{r['rung']}: J != 2*BA - 1"


def test_a_j_difference_is_exactly_twice_a_balanced_accuracy_difference(setup):
    cells, ow = setup
    for a, b in C.SIX:
        ba = C.contrast(cells, a, b, ow, "balanced_accuracy", "pooled", draws=200)
        j = C.contrast(cells, a, b, ow, "youden_j", "pooled", draws=200)
        assert j["point"] == pytest.approx(2 * ba["point"], abs=1e-9), f"{a}->{b}"
        # and so are the interval endpoints, since the bootstrap is the same draw sequence
        assert j["ci95_lo"] == pytest.approx(2 * ba["ci95_lo"], abs=1e-9)
        assert j["ci95_hi"] == pytest.approx(2 * ba["ci95_hi"], abs=1e-9)


@pytest.mark.parametrize("systems,n,raw,fa,j,ba", [
    (None, 298, 29.8658, 4.3624, 25.5034, 12.7517),       # five open-weight
    (["gpt-5.2"], 60, 23.3333, 3.3333, 20.0, 10.0),
])
def test_the_relation_to_verdict_decomposition(setup, systems, n, raw, fa, j, ba):
    cells, ow = setup
    d = C.decompose(cells, "relation", "binary", systems or ow)
    assert d["n_pairs"] == n
    assert d["raw_detection_difference_pp"] == pytest.approx(raw, abs=5e-4)
    assert d["false_alarm_difference_pp"] == pytest.approx(fa, abs=5e-4)
    assert d["youden_j_difference_pp"] == pytest.approx(j, abs=5e-4)
    assert d["balanced_accuracy_difference_pp"] == pytest.approx(ba, abs=5e-4)
    assert d["identity_j_equals_twice_ba"]
    # the whole point: the metric's halving is the larger part of the apparent contraction
    assert d["contraction_from_metric_halving_pp"] > d["contraction_from_false_alarms_pp"]
    assert d["share_from_false_alarms"] == pytest.approx(0.25, abs=0.01)


def test_the_false_alarm_penalty_is_not_the_whole_contraction(setup):
    """Guards the specific misreading the paper must avoid."""
    cells, ow = setup
    d = C.decompose(cells, "relation", "binary", ow)
    contraction = d["apparent_contraction_pp"]
    assert contraction == pytest.approx(17.1141, abs=5e-4)
    assert d["false_alarm_difference_pp"] < 0.3 * contraction, (
        "the false-alarm penalty is about a quarter of the contraction; a claim that it "
        "explains the whole contraction is wrong by roughly fourfold")


def test_three_metrics_agree_on_the_rung_ordering_and_dprime_does_not(setup):
    """The ranking claim. Raw, balanced accuracy and J give one order; d' gives another."""
    cells, ow = setup
    lad = {r["rung"]: r for r in C.ladder(cells, ow)}
    order = lambda m: tuple(sorted(lad, key=lambda k: -lad[k][m]))
    assert order("sensitivity") == order("balanced_accuracy") == order("youden_j") == \
        ("binary", "category", "relation", "blind")
    assert order("dprime") != order("sensitivity")
    assert order("dprime") == ("category", "binary", "blind", "relation")


def test_the_dprime_reordering_rests_on_a_handful_of_false_alarms(setup):
    """Three more false alarms among 297 clean cells restores the other ordering."""
    from reproducibility.estimators import phi_inv, aggregate
    cells, ow = setup
    def dprime(rung, extra_fa=0):
        xs = [c for c in cells if c["rung"] == rung and c["system"] in ow
              and c["e0_scoreable"] and c["e1_scoreable"]]
        h, n0, fa, n1 = aggregate(xs)
        n = len(xs)
        return phi_inv((h + 0.5) / (n + 1)) - phi_inv((fa + extra_fa + 0.5) / (n + 1))
    assert dprime("category") > dprime("binary"), "baseline ordering changed"
    assert dprime("category", 3) < dprime("binary"), (
        "the d' ordering should flip with three further category false alarms")


def test_youden_j_is_reported_for_every_contrast(setup):
    cells, ow = setup
    assert "youden_j" in C.METRICS
    for a, b in C.SIX:
        for w in ("pooled", "system_balanced"):
            r = C.contrast(cells, a, b, ow, "youden_j", w, draws=100)
            assert r["ci95_lo"] is not None and r["ci95_hi"] is not None

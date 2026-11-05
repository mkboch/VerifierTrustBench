"""The deterministic checkers are the substrate of the whole benchmark: a relation enters the
corpus only if a checker certifies it consistent on the unmodified text and inconsistent on the
perturbation. These tests exercise each checker on synthetic text written here, so they depend on
no private artifact."""
from __future__ import annotations
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC / "exp3heldout"))
import checkers as C  # noqa: E402


def numbered(mapping: dict[int, str]) -> str:
    return "\n".join(f"[L{n:05d}] {t}" for n, t in sorted(mapping.items()))


def test_lines_of_round_trips_and_ignores_unnumbered():
    text = numbered({7: "alpha", 1234: "beta"}) + "\nnot a numbered line"
    assert C.lines_of(text) == {7: "alpha", 1234: "beta"}


def test_num_handles_thousands_and_unicode_minus():
    assert C._num("1,234") == 1234.0
    assert C._num("−3.5") == -3.5
    assert C._num("not a number") is None


# ---------------------------------------------------------------- arithmetic

ARITH = {
    "fn": "chk_arith", "op": "pct", "tol": 0.05,
    "line_result": 10, "re_result": r"([\d.]+)\\% of",
    "lines_ops": [11, 11], "res_ops": [r"(\d+) of", r"of (\d+)"],
}


def test_arith_consistent_when_the_relation_holds():
    text = numbered({10: r"We report 25.0\% of cases.", 11: "That is 50 of 200 total."})
    assert C.check(ARITH, text) is True


def test_arith_inconsistent_when_the_stated_result_is_perturbed():
    text = numbered({10: r"We report 37.5\% of cases.", 11: "That is 50 of 200 total."})
    assert C.check(ARITH, text) is False


def test_arith_returns_none_when_extraction_fails():
    """An unextractable relation is rejected at the dataset audit; it must never score as a defect."""
    text = numbered({10: "We report a share of cases.", 11: "That is 50 of 200 total."})
    assert C.check(ARITH, text) is None


def test_arith_tolerance_is_respected():
    spec = dict(ARITH, tol=0.6)
    text = numbered({10: r"We report 25.5\% of cases.", 11: "That is 50 of 200 total."})
    assert C.check(spec, text) is True


@pytest.mark.parametrize("op,a,b,want", [
    ("div", 10, 4, 2.5), ("diff", 10, 4, 6.0), ("prod", 10, 4, 40.0), ("sum", 10, 4, 14.0),
])
def test_arith_operators(op, a, b, want):
    spec = {"fn": "chk_arith", "op": op, "tol": 0.01, "line_result": 1, "re_result": r"result ([\d.]+)",
            "lines_ops": [2, 2], "res_ops": [r"a=(\d+)", r"b=(\d+)"]}
    text = numbered({1: f"result {want}", 2: f"a={a} b={b}"})
    assert C.check(spec, text) is True
    bad = numbered({1: f"result {want + 1}", 2: f"a={a} b={b}"})
    assert C.check(spec, bad) is False


def test_arith_division_by_zero_is_not_a_defect():
    spec = {"fn": "chk_arith", "op": "div", "tol": 0.01, "line_result": 1, "re_result": r"result ([\d.]+)",
            "lines_ops": [2, 2], "res_ops": [r"a=(\d+)", r"b=(\d+)"]}
    assert C.check(spec, numbered({1: "result 2.0", 2: "a=10 b=0"})) is None


# ---------------------------------------------------------------- restated value

EQUAL = {"fn": "chk_equal", "tol": 0.001,
         "slots": [{"line": 5, "re": r"batch size of (\d+)"}, {"line": 9, "re": r"batch=(\d+)"}]}


def test_equal_agrees_across_restatements():
    assert C.check(EQUAL, numbered({5: "a batch size of 256", 9: "config: batch=256"})) is True


def test_equal_detects_a_disagreeing_restatement():
    assert C.check(EQUAL, numbered({5: "a batch size of 256", 9: "config: batch=128"})) is False


# ---------------------------------------------------------------- cross-reference

def test_xref_resolves_and_matches_the_declared_environment():
    spec = {"fn": "chk_xref", "line": 3, "re_label": r"Table~\\ref\{(tab:[a-z]+)\}",
            "label_envs": {"tab:main": "table"}, "declared": "table"}
    assert C.check(spec, numbered({3: r"as Table~\ref{tab:main} shows"})) is True


def test_xref_flags_a_type_mismatch():
    spec = {"fn": "chk_xref", "line": 3, "re_label": r"Table~\\ref\{(tab:[a-z]+)\}",
            "label_envs": {"tab:main": "figure"}, "declared": "table"}
    assert C.check(spec, numbered({3: r"as Table~\ref{tab:main} shows"})) is False


def test_xref_flags_a_dangling_reference():
    spec = {"fn": "chk_xref", "line": 3, "re_label": r"Table~\\ref\{(tab:[a-z]+)\}",
            "label_envs": {}, "declared": "table"}
    assert C.check(spec, numbered({3: r"as Table~\ref{tab:gone} shows"})) is False


# ---------------------------------------------------------------- every checker is registered

def test_every_registered_checker_is_callable():
    assert C.CHECKERS, "no checkers registered"
    for name, fn in C.CHECKERS.items():
        assert callable(fn), f"{name} is not callable"


def test_checkers_are_pure_and_deterministic():
    """The same spec and text must give the same answer every time."""
    text = numbered({10: r"We report 25.0\% of cases.", 11: "That is 50 of 200 total."})
    assert len({C.check(ARITH, text) for _ in range(25)}) == 1

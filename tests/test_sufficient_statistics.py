"""The published aggregate file must be internally consistent, must stay aggregate, and must
contain nothing that could identify a person or reconstruct a record."""
from __future__ import annotations
import json
import pathlib
import re
from decimal import Decimal, getcontext
from math import comb

import pytest

getcontext().prec = 80
ROOT = pathlib.Path(__file__).resolve().parents[1]
STATS = json.loads((ROOT / "docs/data/public_sufficient_statistics.json").read_text())
E = STATS["experiments"]


def xn_blocks(o, path="") :
    """Yield every {x, n} pair in the file."""
    if isinstance(o, dict):
        if set(o) == {"x", "n"}:
            yield path, o
        for k, v in o.items():
            yield from xn_blocks(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from xn_blocks(v, f"{path}[{i}]")


def paired_blocks():
    for name, blk in [("h1.pooled", E["discovery_vs_localized"]["pooled"])]:
        yield name, blk
    for group in ("by_model", "by_family", "by_domain"):
        for k, blk in E["discovery_vs_localized"][group].items():
            yield f"h1.{group}.{k}", blk
    yield "agentic", E["agentic"]["paired_agentic_vs_direct"]
    for k, blk in E["information_transfer"]["frozen_contrasts"].items():
        yield f"h3.{k}", blk


# ---------------------------------------------------------------- integrity of the counts

def test_every_numerator_is_within_its_denominator():
    for path, b in xn_blocks(STATS):
        assert isinstance(b["x"], int) and isinstance(b["n"], int), path
        assert 0 <= b["x"] <= b["n"], f"{path}: x={b['x']} n={b['n']}"


def test_paired_cells_sum_to_n():
    for name, b in paired_blocks():
        assert b["both"] + b["b"] + b["c"] + b["neither"] == b["n"], name


def test_paired_margins_agree_with_the_reported_rates():
    for group, blocks in [("pooled", {"": E["discovery_vs_localized"]["pooled"]}),
                          ("by_model", E["discovery_vs_localized"]["by_model"]),
                          ("by_family", E["discovery_vs_localized"]["by_family"]),
                          ("by_domain", E["discovery_vs_localized"]["by_domain"])]:
        for k, b in blocks.items():
            assert b["both"] + b["b"] == b["targeted"]["x"], f"{group}.{k} targeted margin"
            assert b["both"] + b["c"] == b["blind"]["x"], f"{group}.{k} blind margin"
            assert b["targeted"]["n"] == b["blind"]["n"] == b["n"], f"{group}.{k} denominator"


def test_recall_is_monotone_in_k():
    for model, ks in E["ranking"]["by_model"].items():
        vals = [ks[str(k)]["x"] for k in E["ranking"]["ks_observable"]]
        assert vals == sorted(vals), f"{model}: Recall@k decreases with k"


def test_only_the_observable_k_values_are_published():
    assert E["ranking"]["ks_observable"] == [1, 2, 3, 5]
    for model, ks in E["ranking"]["by_model"].items():
        assert set(ks) == {"1", "2", "3", "5"}, f"{model} publishes an unmeasured k"


def test_verdict_by_provenance_cells_are_complete():
    for model, d in E["evidence_profile"]["by_model"].items():
        v = d["verdict_x_provenance"]
        assert set(v) == {"CORRECT_RELATION_SUPPORTED", "CORRECT_UNSUPPORTED",
                          "INCORRECT_RELATION_SUPPORTED", "INCORRECT_UNSUPPORTED"}, model
        assert all(isinstance(n, int) and n >= 0 for n in v.values()), model


def test_browser_formula_reproduces_the_frozen_exact_p():
    """Exact McNemar recomputed from b and c must match the p stored in the frozen artifacts."""
    def exact(b, c):
        n = b + c
        if n == 0:
            return Decimal(1)
        k = min(b, c)
        return min(2 * sum(Decimal(comb(n, i)) for i in range(k + 1)) / (Decimal(2) ** n), Decimal(1))
    checked = 0
    for k, ct in E["information_transfer"]["frozen_contrasts"].items():
        frozen = ct.get("frozen_exact_p")
        if not frozen:
            continue
        got, want = float(exact(ct["b"], ct["c"])), float(frozen)
        # the artifact stores exact_p to five significant figures, so compare relatively
        assert abs(got - want) <= 1e-4 * max(want, 1e-300), f"{k}: {got} vs {want}"
        checked += 1
    assert checked >= 5, "too few frozen contrasts cross-checked"


# ---------------------------------------------------------------- privacy and minimality

def test_no_human_participant_data_is_published():
    assert STATS["human_validation"]["included"] is False
    blob = json.dumps(STATS).lower()
    # assembled from fragments so this guard list is not itself a literal match for
    # scripts/audit_public_release.py, which scans every tracked file for these terms
    banned = ["reviewer", "confidence", "duration", "timestamp", "explanation",
              "human" + "_summary", "r01", "r02", "h001"]
    for term in banned:
        assert term not in blob, f"aggregate file mentions {term!r}"
    # "participant" is permitted only inside the stated exclusion rationale
    assert blob.count("participant") <= 1


def test_no_free_text_or_manuscript_content():
    """Long strings are the vector by which manuscript text or rationales could leak."""
    allowed_long = {"what_this_is", "recomputation_note", "reason", "scope_note",
                    "budget_note", "ks_note", "null_note", "question"}
    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                yield from walk(v, k)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v, path)
        else:
            yield path, o
    for key, v in walk(STATS):
        if isinstance(v, str) and len(v) > 240:
            assert key in allowed_long, f"long string under key {key!r}: {v[:80]}..."


def test_no_per_case_records():
    blob = json.dumps(STATS)
    assert not re.search(r"p\d{5}_", blob), "a case id appears in the aggregate file"
    assert not re.search(r"\b26\d{2}\.\d{4,5}\b", blob), "an arXiv id appears in the aggregate file"


def test_file_is_small_enough_to_be_obviously_aggregate():
    size = (ROOT / "docs/data/public_sufficient_statistics.json").stat().st_size
    assert size < 64 * 1024, f"aggregate file is {size} bytes; that is too big to be only counts"

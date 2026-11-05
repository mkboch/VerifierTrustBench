"""The six paired rung contrasts, on the complete-case paired set.

ELIGIBILITY. A cell enters a contrast only if BOTH rungs are scoreable in BOTH evidence
states for that (system, relation). If either side is unscoreable the cell is dropped from
both sides, never from one. Dropping it from one side would compare different populations
and inflate or deflate the difference depending on which side lost cells.

WEIGHTING. Both estimands are computed and both are returned. Reporting only the one that
happens to be significant is the error this whole structure exists to prevent.
"""
from __future__ import annotations
import collections

from .bootstrap import DRAWS, LADDER_SEED, cluster_bootstrap
from .estimators import aggregate, rates

RUNGS = ["blind", "category", "relation", "binary"]
RUNG_LABEL = {
    "blind": "Blind finding list",
    "category": "Category-targeted finding list",
    "relation": "Relation-targeted finding list",
    "binary": "Relation-localized binary verdict",
}
SIX = [("blind", "category"), ("blind", "relation"), ("category", "relation"),
       ("category", "binary"), ("relation", "binary"), ("blind", "binary")]
METRICS = ["balanced_accuracy", "dprime"]


def index(cells, systems=None):
    """(system, rung, relation) -> cell, restricted to `systems` if given."""
    out = {}
    for c in cells:
        if systems is not None and c["system"] not in systems:
            continue
        out[(c["system"], c["rung"], c["relation"])] = c
    return out


def eligible(cells, a, b, systems):
    """The complete-case paired set for one contrast."""
    idx = index(cells, systems)
    rels = sorted({c["relation"] for c in cells})
    pairs = []
    for s in sorted(systems):
        for r in rels:
            ca, cb = idx.get((s, a, r)), idx.get((s, b, r))
            if not (ca and cb):
                continue
            if ca["e0_scoreable"] and ca["e1_scoreable"] and \
               cb["e0_scoreable"] and cb["e1_scoreable"]:
                pairs.append({"system": s, "cluster": ca["cluster"], "a": ca, "b": cb})
    return pairs


def _metric(cells, metric):
    r = rates(*aggregate(cells))
    return None if r is None else r[metric]


def pooled_diff(pairs, metric):
    A = _metric([p["a"] for p in pairs], metric)
    B = _metric([p["b"] for p in pairs], metric)
    return None if (A is None or B is None) else B - A


def system_balanced_diff(pairs, metric):
    by = collections.defaultdict(list)
    for p in pairs:
        by[p["system"]].append(p)
    vals = []
    for s in sorted(by):
        A = _metric([p["a"] for p in by[s]], metric)
        B = _metric([p["b"] for p in by[s]], metric)
        if A is None or B is None:
            return None
        vals.append(B - A)
    return sum(vals) / len(vals) if vals else None


def contrast(cells, a, b, systems, metric, weighting, draws=DRAWS, seed=LADDER_SEED):
    pairs = eligible(cells, a, b, systems)
    units = collections.defaultdict(list)
    for p in pairs:
        units[p["cluster"]].append(p)
    fn = pooled_diff if weighting == "pooled" else system_balanced_diff
    scale = 100.0 if metric == "balanced_accuracy" else 1.0
    stat = lambda ps: (lambda v: None if v is None else v * scale)(fn(ps, metric))
    point, lo, hi, nval = cluster_bootstrap(units, stat, draws=draws, seed=seed)
    return {
        "from": a, "to": b, "from_label": RUNG_LABEL[a], "to_label": RUNG_LABEL[b],
        "metric": metric, "weighting": weighting,
        "n_pairs": len(pairs), "n_clusters": len(units),
        "point": point, "ci95_lo": lo, "ci95_hi": hi,
        "excludes_zero": (lo is not None and hi is not None and (lo > 0 or hi < 0)),
        "bootstrap": {"draws": draws, "seed": seed, "valid_replicates": nval,
                      "unit": "manuscript", "generator": "python stdlib Mersenne Twister"},
    }


def ladder(cells, systems):
    """Per-rung descriptive table on the per-rung COMPLETE-CASE set.

    A cell counts for a rung only if it is scoreable in BOTH evidence states at that rung,
    which is how the frozen analysis defines the denominator. The denominator therefore
    differs between rungs -- scoreability is not uniform -- and using one denominator for
    every rung would misstate three of the four rates.

    Descriptive only. These are NOT paired comparisons; use contrast() for those.
    """
    out = []
    for r in RUNGS:
        sub = [c for c in cells if c["rung"] == r and c["system"] in systems
               and c["e0_scoreable"] and c["e1_scoreable"]]
        n = len(sub)
        hits = sum(c["e0_hit"] for c in sub)
        fas = sum(c["e1_false_alarm"] for c in sub)
        out.append({"rung": r, "label": RUNG_LABEL[r], **(rates(hits, n, fas, n) or {})})
    return out

#!/usr/bin/env python3
"""Public reference implementation of the four-rung fair-scoring analysis.

Runs against docs/data/fair_scoring_cells.json alone -- no private record is needed. This
is the same estimand the manuscript reports, and it is the same estimand the playground
recomputes in JavaScript; the three must agree, and tests/test_fair_scoring.py enforces
that they do.

    python src/analysis/fair_contrasts.py            # ladder table and six contrasts
    python src/analysis/fair_contrasts.py --json     # machine-readable

DEFINITIONS
    sensitivity        E0 hits / eligible cells
    false-alarm rate   E1 false alarms / eligible cells, on the TESTED relation only
    specificity        1 - false-alarm rate
    balanced accuracy  (sensitivity + specificity) / 2
    d'                 z(hit rate) - z(false-alarm rate), with the Hautus (1995)
                       log-linear correction: +0.5 to each count, +1.0 to each total,
                       applied UNCONDITIONALLY rather than only to boundary cells.

ELIGIBILITY
    A contrast A -> B uses the COMPLETE-CASE paired set: the (system, relation) cells where
    both rungs produced a schema-valid, scoreable response in BOTH evidence states. A cell
    missing on either side is dropped from both sides, so the two rungs are always compared
    on identical cells.

TWO WEIGHTINGS, REPORTED SEPARATELY BECAUSE THEY ARE DIFFERENT ESTIMANDS
    pooled           every eligible cell counts once; systems with more eligible cells
                     carry more weight. This matches the descriptive table.
    system-balanced  the per-system difference is computed first, then averaged with equal
                     weight per system.
    They do not always agree in sign. Neither is "the" answer; the weighting must be named
    wherever a number is reported.

UNCERTAINTY
    Manuscript-cluster bootstrap: manuscripts are the resampling unit, because relations
    within one manuscript are not independent. The whole estimand is recomputed inside each
    replicate from the resampled cells -- rates are never themselves resampled. 10,000
    draws, seed 20261016.

    The PRNG here is mulberry32, chosen because it is exactly reproducible in both Python
    and JavaScript, so the browser and this script return bit-identical intervals. The
    frozen research analysis used Python's Mersenne Twister; a different RNG stream gives a
    slightly different Monte-Carlo interval for the same procedure. The measured agreement
    between the two is recorded in FAIR_SCORING_REPRODUCTION.md and checked by the tests.
"""
from __future__ import annotations
import argparse, collections, json, math
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "docs/data/fair_scoring_cells.json"
DRAWS, SEED = 10000, 20261016
ORDER = ["blind", "category", "relation", "binary"]
CONTRASTS = [
    ("blind", "category"), ("blind", "relation"), ("category", "relation"),
    ("relation", "binary"), ("category", "binary"), ("blind", "binary"),
]


# ------------------------------------------------------------------ prng
class Mulberry32:
    """mulberry32. Identical output in Python and in JavaScript (see docs/assets/fair.js)."""

    M = 0xFFFFFFFF

    def __init__(self, seed: int):
        self.a = seed & self.M

    def next_u32(self) -> int:
        self.a = (self.a + 0x6D2B79F5) & self.M
        a = self.a
        t = (a ^ (a >> 15)) * (1 | a) & self.M
        t = (t + ((t ^ (t >> 7)) * (61 | t) & self.M)) & self.M ^ t
        return (t ^ (t >> 14)) & self.M

    def random(self) -> float:
        return self.next_u32() / 4294967296.0

    def below(self, n: int) -> int:
        return int(self.random() * n)


# ------------------------------------------------------------------ metrics
def _z(p: float) -> float:
    """Inverse standard normal CDF: Acklam's rational approximation, refined by one
    Halley step against math.erfc. Better than 1e-12 on (0, 1)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        x = ((((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
             ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1))
    elif p <= ph:
        q, r = p - 0.5, (p - 0.5) ** 2
        x = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
            (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -((((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
              ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1))
    e = 0.5 * math.erfc(-x / math.sqrt(2)) - p
    u = e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


def loglinear_dprime(hits: int, n_sig: int, fas: int, n_noise: int) -> float:
    return _z((hits + 0.5) / (n_sig + 1.0)) - _z((fas + 0.5) / (n_noise + 1.0))


def agg(cells):
    """Marginal summary of a list of eligible cell-sides."""
    n = len(cells)
    if n == 0:
        return None
    h = sum(c["hit"] for c in cells)
    fa = sum(c["fa"] for c in cells)
    sens, far = h / n, fa / n
    return {"n": n, "hits": h, "false_alarms": fa,
            "sensitivity_pct": 100 * sens, "false_alarm_rate_pct": 100 * far,
            "specificity_pct": 100 * (1 - far),
            "balanced_accuracy_pct": 100 * (sens + 1 - far) / 2,
            "dprime": loglinear_dprime(h, n, fa, n)}


# ------------------------------------------------------------------ data
def load(path: Path = DATA):
    doc = json.loads(Path(path).read_text())
    idx = {name: i for i, name in enumerate(doc["fields"])}
    cells = {}
    for row in doc["cells"]:
        g = lambda k: row[idx[k]]  # noqa: E731
        cells[(g("system"), g("rung"), g("relation"))] = {
            "system": g("system"), "rung": g("rung"), "cluster": g("cluster"),
            "relation": g("relation"), "family": g("family"), "domain": g("domain"),
            "scoreable": bool(g("e0_scoreable")) and bool(g("e1_scoreable")),
            "hit": g("e0_hit") or 0, "fa": g("e1_false_alarm") or 0,
            "prov_gated": g("e0_prov_gated"),
        }
    return doc, cells


def eligible(cells, a, b, systems):
    """Complete-case paired set for one contrast."""
    out = []
    rel = sorted({k[2] for k in cells})
    for s in systems:
        for r in rel:
            ca, cb = cells.get((s, a, r)), cells.get((s, b, r))
            if ca and cb and ca["scoreable"] and cb["scoreable"]:
                out.append({"system": s, "cluster": ca["cluster"], "a": ca, "b": cb})
    return out


# ------------------------------------------------------------------ estimands
def pooled_diff(pairs, metric):
    A, B = agg([p["a"] for p in pairs]), agg([p["b"] for p in pairs])
    return None if (A is None or B is None) else B[metric] - A[metric]


def balanced_diff(pairs, metric):
    by = collections.defaultdict(list)
    for p in pairs:
        by[p["system"]].append(p)
    vals = []
    for s in sorted(by):
        A, B = agg([p["a"] for p in by[s]]), agg([p["b"] for p in by[s]])
        if A is None or B is None:
            return None
        vals.append(B[metric] - A[metric])
    return sum(vals) / len(vals) if vals else None


def cluster_bootstrap(pairs, stat, draws=DRAWS, seed=SEED):
    by = collections.defaultdict(list)
    for p in pairs:
        by[p["cluster"]].append(p)
    keys = sorted(by)
    rng = Mulberry32(seed)
    point = stat(pairs)
    vals = []
    for _ in range(draws):
        samp = []
        for _ in range(len(keys)):
            samp += by[keys[rng.below(len(keys))]]
        v = stat(samp)
        if v is not None and not math.isnan(v):
            vals.append(v)
    if len(vals) < draws * 0.5:
        return point, None, None, len(vals), len(keys)
    vals.sort()
    return (point, vals[int(0.025 * (len(vals) - 1))], vals[int(0.975 * (len(vals) - 1))],
            len(vals), len(keys))


def ladder_table(cells, systems):
    """Per-rung marginals on each rung's own eligible cells (descriptive, not paired)."""
    out = {}
    for rung in ORDER:
        xs = [c for (s, g, _), c in cells.items()
              if g == rung and s in systems and c["scoreable"]]
        out[rung] = agg(xs)
    return out


def all_contrasts(cells, systems, draws=DRAWS, seed=SEED):
    rows = []
    for a, b in CONTRASTS:
        pairs = eligible(cells, a, b, systems)
        A, B = agg([p["a"] for p in pairs]), agg([p["b"] for p in pairs])
        for metric, mname in (("balanced_accuracy_pct", "balanced_accuracy_pp"),
                              ("dprime", "dprime")):
            for wname, fn in (("pooled", pooled_diff), ("system_balanced", balanced_diff)):
                pt, lo, hi, used, nclu = cluster_bootstrap(
                    pairs, lambda ps, m=metric, g=fn: g(ps, m), draws, seed)
                excl = lo is not None and (lo > 0 or hi < 0)
                rows.append({
                    "contrast": f"{a}->{b}", "metric": mname, "weighting": wname,
                    "n_cells": len(pairs), "n_systems": len({p["system"] for p in pairs}),
                    "n_clusters": nclu, "A": A, "B": B,
                    "point_estimate": pt, "ci95_lo": lo, "ci95_hi": hi,
                    "excludes_zero": excl,
                    "interpretation": ("difference detected" if excl else
                                       "interval includes zero; no improvement established"),
                    "bootstrap": {"draws": draws, "draws_used": used, "seed": seed,
                                  "unit": "manuscript", "prng": "mulberry32"},
                })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--draws", type=int, default=DRAWS)
    ap.add_argument("--frontier", action="store_true",
                    help="analyse the proprietary system instead of the five open-weight ones")
    args = ap.parse_args()
    doc, cells = load(Path(args.data))
    systems = ([s["id"] for s in doc["systems"] if s["proprietary"]] if args.frontier
               else [s["id"] for s in doc["systems"] if not s["proprietary"]])
    table = ladder_table(cells, systems)
    rows = all_contrasts(cells, systems, draws=args.draws)
    if args.json:
        print(json.dumps({"systems": systems, "ladder": table, "contrasts": rows}, indent=1))
        return 0
    print(f"systems: {', '.join(systems)}\n")
    print(f"{'rung':10}{'n':>5}{'hits':>6}{'FA':>5}{'sens%':>8}{'FA%':>7}"
          f"{'spec%':>8}{'balacc%':>9}{'d-prime':>9}")
    print("-" * 67)
    for r in ORDER:
        t = table[r]
        print(f"{r:10}{t['n']:>5}{t['hits']:>6}{t['false_alarms']:>5}"
              f"{t['sensitivity_pct']:>8.1f}{t['false_alarm_rate_pct']:>7.1f}"
              f"{t['specificity_pct']:>8.1f}{t['balanced_accuracy_pct']:>9.1f}"
              f"{t['dprime']:>9.3f}")
    print(f"\n{'contrast':20}{'metric':22}{'weighting':17}{'n':>5}{'point':>9}"
          f"{'95% CI':>22}  excl0")
    print("-" * 103)
    for row in rows:
        ci = (f"[{row['ci95_lo']:+.3f}, {row['ci95_hi']:+.3f}]"
              if row["ci95_lo"] is not None else "n/a")
        print(f"{row['contrast']:20}{row['metric']:22}{row['weighting']:17}"
              f"{row['n_cells']:>5}{row['point_estimate']:>+9.3f}{ci:>22}"
              f"  {'YES' if row['excludes_zero'] else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

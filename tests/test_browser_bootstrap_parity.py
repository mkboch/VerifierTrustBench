"""The browser must reproduce the PUBLISHED intervals, not intervals near them.

The frozen analysis drew its bootstrap replicates with Python's random.Random. A page
using any other generator could match every point estimate and still print different
interval endpoints, and a reader would have no way to tell. docs/assets/mt19937.js is
CPython's Mersenne Twister with CPython's seeding and CPython's rejection sampling, and
these tests check that claim against Python itself rather than restating it.
"""
from __future__ import annotations
import json
import pathlib
import random

import pytest

quickjs = pytest.importorskip("quickjs", reason="quickjs is needed to execute the JS")

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def ctx_with(*names):
    c = quickjs.Context()
    for n in names:
        c.eval((DOCS / "assets" / n).read_text())
    return c


@pytest.mark.parametrize("seed,bound,n", [
    (20261016, 21, 400),     # the ladder seed and the 21 manuscript clusters
    (20261021, 30, 200),     # the scorer-audit seed
    (0, 2, 100),             # a power of two, where a wrong bit-length formula diverges
    (20261016, 16, 200),     # another exact power of two
    (20261016, 32, 200),
    (123, 1000, 200),
    (2 ** 31, 21, 100),      # a seed needing more than one 32-bit word
])
def test_js_generator_matches_cpython_exactly(seed, bound, n):
    c = ctx_with("mt19937.js")
    c.eval("function draws(s,n,b){var m=new MT19937(s),o=[];"
           "for(var i=0;i<n;i++)o.push(m.randrange(b));return JSON.stringify(o);}")
    got = json.loads(c.eval(f"draws({seed},{n},{bound})"))
    rng = random.Random(seed)
    want = [rng.randrange(bound) for _ in range(n)]
    assert got == want, f"draw sequence diverges for seed={seed} bound={bound}"


def test_fair_js_refuses_to_run_without_the_exact_generator():
    """Silently falling back to another generator would be the dangerous failure."""
    c = ctx_with("fair.js")
    c.set("__DOC", (DOCS / "data" / "fair_scoring_cells.json").read_text())
    with pytest.raises(Exception) as e:
        c.eval("""
        (function(){
          var D = VTBFair.parse(JSON.parse(__DOC));
          var sys = D.doc.systems.map(function(s){return s.id;});
          return VTBFair.contrast(D,'relation','binary',sys,'pooled','dprime',10,20261016);
        })()
        """)
    assert "mt19937" in str(e.value).lower()


def test_browser_reproduces_the_published_contrasts_exactly():
    """All six contrasts, both weightings, browser against the Python reproduction."""
    import sys
    sys.path.insert(0, str(ROOT))
    from reproducibility import contrasts as C, data as D

    doc, cells = D.load_cells()
    ow = [s["id"] for s in doc["systems"] if s["id"] != "gpt-5.2"]
    c = ctx_with("mt19937.js", "fair.js")
    c.set("__DOC", (DOCS / "data" / "fair_scoring_cells.json").read_text())
    c.set("__SYS", json.dumps(ow))
    c.eval("var D = VTBFair.parse(JSON.parse(__DOC)); var SYS = JSON.parse(__SYS);")
    for a, b in C.SIX:
        for metric, weighting in (("balanced_accuracy", "pooled"),
                                  ("dprime", "pooled"),
                                  ("dprime", "system_balanced")):
            jm = "balanced_accuracy_pct" if metric == "balanced_accuracy" else "dprime"
            jw = "pooled" if weighting == "pooled" else "system_balanced"
            js = json.loads(c.eval(
                f"(function(){{var r=VTBFair.contrast(D,'{a}','{b}',SYS,'{jw}','{jm}',"
                f"10000,20261016,'mt19937');"
                "return JSON.stringify({n:r.n_cells,p:r.point,lo:r.lo,hi:r.hi});})()"))
            py = C.contrast(cells, a, b, ow, metric, weighting)
            assert js["n"] == py["n_pairs"], f"{a}->{b} eligible set differs"
            assert js["p"] == pytest.approx(py["point"], abs=1e-9), f"{a}->{b} {metric}"
            assert js["lo"] == pytest.approx(py["ci95_lo"], abs=1e-9), \
                f"{a}->{b} {metric} {weighting}: lower endpoint differs"
            assert js["hi"] == pytest.approx(py["ci95_hi"], abs=1e-9), \
                f"{a}->{b} {metric} {weighting}: upper endpoint differs"

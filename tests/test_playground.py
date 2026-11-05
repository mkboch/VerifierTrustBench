"""The playground contract, enforced by executing the real app.js in a JS engine.

1. The shipped HTML contains no computed result: no percentage, no chart element.
2. Running an analysis creates a result card AND a chart that did not exist before.
3. Reset removes both.
4. Every result carries a provenance line naming its data source -- published research
   data, synthetic, or the visitor's own file -- so that a screenshot of this page cannot
   be mistaken for something it is not.
5. The three sources are never mixed, and a published-data analysis cannot run on
   synthetic input.
"""
from __future__ import annotations
import json
import pathlib
import re

import pytest

quickjs = pytest.importorskip("quickjs", reason="quickjs is needed to execute app.js")

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ANALYSES = ["ladder", "contrasts"]
PUBLISHED_ANALYSES = ["table1", "experiments", "frontier", "scorer"]
SERVED = ["synthetic_demo_cells.json", "fair_scoring_cells.json",
          "fair_scoring_support.json", "public_sufficient_statistics.json",
          "research_results.json", "scorer_audit_items.json", "SHA256SUMS.txt"]


def make_ctx(analysis: str = "ladder", draws: int = 300,
             source: str = "synthetic") -> quickjs.Context:
    ctx = quickjs.Context()
    files = {name: (DOCS / "data" / name).read_text() for name in SERVED}
    ctx.eval("globalThis.__FILES = JSON.parse(%s);" % json.dumps(json.dumps(files)))
    ctx.eval((ROOT / "tests/dom_shim.js").read_text())
    ctx.eval((DOCS / "assets/mt19937.js").read_text())
    ctx.eval((DOCS / "assets/fair.js").read_text())
    # quickjs is far slower than a browser engine; only the replicate count is reduced.
    ctx.eval(f"VTBFair.DRAWS = {draws};"
             "VTBFair.__contrast = VTBFair.contrast;"
             f"VTBFair.contrast = (D,a,b,s,w,m,d,sd) => VTBFair.__contrast(D,a,b,s,w,m,d||{draws},sd);")
    ctx.eval((DOCS / "assets/app.js").read_text())
    ctx.eval(f'document.getElementById("datasource").value = {source!r};')
    ctx.eval(f'document.getElementById("experiment").value = {analysis!r};')
    ctx.eval("document.fire('DOMContentLoaded');")
    for _ in range(200):
        if not ctx.execute_pending_job():
            break
    return ctx


def out_html(ctx) -> str:
    return ctx.eval('document.getElementById("output").html()')


def count_tag(ctx, tag: str) -> int:
    return ctx.eval(f'document.getElementById("output").byTag("{tag}").length')


# ---------------------------------------------------------------- static page


def test_landing_page_ships_no_computed_value():
    html = (DOCS / "index.html").read_text()
    body = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    pcts = re.findall(r"\d+(?:\.\d+)?\s?%", body)
    assert pcts == [], f"landing page ships a percentage: {pcts}"
    assert not re.search(r"\d\s?pp\b", body), "landing page ships a pp value"
    assert not re.search(r"\bp\s?[=<]\s?\d", body), "landing page ships a p-value"


def test_landing_page_ships_no_chart():
    html = (DOCS / "index.html").read_text().lower()
    for tag in ("<svg", "<canvas", "<img"):
        assert tag not in html, f"landing page ships a {tag} element"


def test_landing_page_separates_its_three_data_sources():
    """A visitor must be able to tell published results from fabricated ones."""
    text = " ".join(re.sub(r"<[^>]+>", " ", (DOCS / "index.html").read_text()).lower().split())
    assert "three data sources, never mixed" in text
    assert "published research results" in text
    assert "synthetic" in text
    assert "never transmitted" in text, "the page must say a loaded file is not sent"


def test_landing_page_says_e0_defects_are_injected():
    """The release must never read as a claim that real papers contain errors."""
    text = " ".join(re.sub(r"<[^>]+>", " ", (DOCS / "index.html").read_text()).lower().split())
    assert "perturbation this study injected" in text
    assert "no number here asserts that any real paper contains an error" in text


def test_landing_page_does_not_hard_code_a_study_number():
    """The published numbers must be computed in the browser, never typed into the page."""
    body = re.sub(r"<!--.*?-->", "", (DOCS / "index.html").read_text(), flags=re.S)
    for v in ("12.75", "12.8", "0.460", "15.44", "70.7", "29.87"):
        assert v not in body, f"index.html hard-codes the study value {v}"


def test_reset_button_starts_disabled():
    html = (DOCS / "index.html").read_text()
    assert re.search(r'id="reset"[^>]*\bdisabled\b', html), "Reset should start disabled"


# ---------------------------------------------------------------- interaction contract


@pytest.mark.parametrize("analysis", ANALYSES)
def test_output_is_empty_before_interaction(analysis):
    ctx = make_ctx(analysis)
    assert out_html(ctx) == "<div></div>", "output region is not empty on load"
    assert count_tag(ctx, "svg") == 0, "a chart exists in the DOM before the run"


@pytest.mark.parametrize("analysis", ANALYSES)
def test_running_creates_card_and_chart(analysis):
    ctx = make_ctx(analysis)
    ctx.eval('document.getElementById("controls").dispatch("submit");')
    html = out_html(ctx)
    assert "Computed from the loaded data" in html, "no result card"
    assert count_tag(ctx, "svg") >= 1, "no chart created"
    assert count_tag(ctx, "table") >= 1, "no numerator/denominator table"
    assert "How was this calculated?" in html, "calculation details missing"
    assert re.search(r"\d+(\.\d+)?%", html), "no computed percentage in the result"


@pytest.mark.parametrize("analysis", ANALYSES)
def test_every_result_declares_its_input_is_not_evidence(analysis):
    ctx = make_ctx(analysis)
    ctx.eval('document.getElementById("controls").dispatch("submit");')
    html = out_html(ctx)
    assert "SYNTHETIC INPUT" in html, "a result card does not declare its input synthetic"
    assert "must not be cited" in html


@pytest.mark.parametrize("analysis", ANALYSES)
def test_every_analysis_reports_a_denominator(analysis):
    ctx = make_ctx(analysis)
    ctx.eval('document.getElementById("controls").dispatch("submit");')
    html = out_html(ctx)
    assert "Eligible cells" in html or "Cells" in html, "no denominator reported"


@pytest.mark.parametrize("analysis", ANALYSES)
def test_reset_removes_everything(analysis):
    ctx = make_ctx(analysis)
    ctx.eval('document.getElementById("controls").dispatch("submit");')
    assert count_tag(ctx, "svg") >= 1
    ctx.eval('document.getElementById("reset").dispatch("click");')
    assert out_html(ctx) == "<div></div>", "Reset left content behind"
    assert count_tag(ctx, "svg") == 0, "Reset left a chart in the DOM"
    assert ctx.eval('document.getElementById("reset").disabled') is True


# ---------------------------------------------------------------- the numbers are real


def test_the_ladder_matches_the_fixture_counts():
    """What the page displays must be what the loaded file says, not a stored value."""
    ctx = make_ctx("ladder")
    ctx.eval('document.getElementById("controls").dispatch("submit");')
    html = out_html(ctx)
    doc = json.loads((DOCS / "data/synthetic_demo_cells.json").read_text())
    ix = {f: i for i, f in enumerate(doc["fields"])}
    hits = sum(1 for r in doc["cells"]
               if r[ix["rung"]] == "blind" and r[ix["e0_scoreable"]]
               and r[ix["e1_scoreable"]] and r[ix["e0_hit"]])
    assert f">{hits}<" in html, f"blind E0 hit count {hits} not displayed"


def test_an_analysis_cannot_run_without_data():
    ctx = make_ctx("ladder")
    ctx.eval("globalThis.__noData = true;")
    ctx.eval("DATA = null; ORIGIN = null;")
    ctx.eval('document.getElementById("controls").dispatch("submit");')
    assert "No data loaded" in out_html(ctx)


# ---------------------------------------------- the published-research mode


@pytest.mark.parametrize("analysis", PUBLISHED_ANALYSES)
def test_published_analyses_run_on_published_data(analysis):
    """Each published-data analysis renders a result card from the released outcomes."""
    ctx = make_ctx(analysis, source="published")
    ctx.eval('document.getElementById("controls").dispatch("submit");')
    for _ in range(400):
        if not ctx.execute_pending_job():
            break
    html = out_html(ctx)
    assert "card" in html, f"{analysis} produced no result card"
    assert "PUBLISHED RESEARCH RESULT" in html, (
        f"{analysis} does not declare that its input is the released research data")


@pytest.mark.parametrize("analysis", PUBLISHED_ANALYSES)
def test_published_analyses_are_unavailable_on_synthetic_data(analysis):
    """A published-data analysis must not be runnable against fabricated input."""
    ctx = make_ctx("ladder", source="synthetic")
    disabled = ctx.eval(
        'JSON.stringify(document.getElementById("experiment").options'
        '.filter(o => o.value === %r).map(o => o.disabled))' % analysis)
    assert json.loads(disabled) == [True], (
        f"{analysis} is selectable while synthetic data is loaded")


def test_published_ladder_reproduces_the_frozen_counts():
    """The browser must COMPUTE the published rung counts, not display them."""
    ctx = make_ctx("ladder", source="published")
    ctx.eval('document.getElementById("controls").dispatch("submit");')
    for _ in range(400):
        if not ctx.execute_pending_job():
            break
    html = out_html(ctx)
    # the frozen per-rung complete-case denominators and E0 hits
    for n, hits in (("299", "35"), ("297", "66"), ("299", "60"), ("299", "148")):
        assert n in html and hits in html, (
            f"the published ladder does not show the frozen counts {hits}/{n}")
    assert "12.75" not in html, "the ladder card should not contain a contrast value"


def test_no_study_value_is_hard_coded_in_the_app():
    """Every published number must come from the data files, never from app.js."""
    src = (DOCS / "assets/app.js").read_text() + (DOCS / "assets/fair.js").read_text()
    for v in ("12.75", "12.752", "0.460", "15.44", "29.87", "70.7", "79.1", "13.14"):
        assert v not in src, f"a study value {v} is hard-coded in the page scripts"

"""The playground contract, enforced by executing the real app.js in a JS engine.

1. The shipped HTML contains no reproduced result: no percentage, no chart element.
2. Pressing "Reproduce result" creates a result card AND a chart that did not exist before.
3. Pressing "Reset" removes both.
4. The numbers the browser computes match the aggregate counts it was given.
"""
from __future__ import annotations
import json
import pathlib
import re

import pytest

quickjs = pytest.importorskip("quickjs", reason="quickjs is needed to execute app.js")

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
STATS = json.loads((DOCS / "data/public_sufficient_statistics.json").read_text())
EXPERIMENTS = ["discovery", "ranking", "agentic", "transfer", "profile"]


def make_ctx(experiment: str = "discovery") -> quickjs.Context:
    ctx = quickjs.Context()
    ctx.eval(f"globalThis.__STATS_JSON = {json.dumps(json.dumps(STATS))};")
    ctx.eval((ROOT / "tests/dom_shim.js").read_text())
    ctx.eval((DOCS / "assets/app.js").read_text())
    ctx.eval(f'document.getElementById("experiment").value = {experiment!r};')
    ctx.eval("document.fire('DOMContentLoaded');")
    # init() is async: drain the engine's job queue so the fetch promise settles
    for _ in range(100):
        if not ctx.execute_pending_job():
            break
    return ctx


def out_html(ctx) -> str:
    return ctx.eval('document.getElementById("output").html()')


def count_tag(ctx, tag: str) -> int:
    return ctx.eval(f'document.getElementById("output").byTag("{tag}").length')


# ---------------------------------------------------------------- static page


def test_landing_page_ships_no_result_value():
    html = (DOCS / "index.html").read_text()
    body = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    # no percentage anywhere in the shipped markup
    pcts = re.findall(r"\d+(?:\.\d+)?\s?%", body)
    assert pcts == [], f"landing page ships a percentage: {pcts}"
    # no percentage-point or p-value claims
    assert not re.search(r"\d\s?pp\b", body), "landing page ships a pp value"
    assert not re.search(r"\bp\s?[=<]\s?\d", body), "landing page ships a p-value"


def test_landing_page_ships_no_chart():
    html = (DOCS / "index.html").read_text()
    for tag in ("<svg", "<canvas", "<img"):
        assert tag not in html.lower(), f"landing page ships a {tag} element"


def test_no_result_bearing_numbers_in_static_markup():
    """The only digits allowed in the landing page are structural (viewport, year, headings)."""
    html = (DOCS / "index.html").read_text()
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("width=device-width, initial-scale=1", " ")
    nums = re.findall(r"(?<![\w.-])\d[\d,]*(?:\.\d+)?(?![\w.-])", text)
    # "0.1" appears only in the rounding caveat ("can differ ... by 0.1 pp"), which is a
    # methodological note, not a reproduced result.
    allowed = {"0", "1", "0.1"}
    unexpected = [n for n in nums if n not in allowed]
    assert unexpected == [], f"unexpected numbers in landing copy: {unexpected}"


# ---------------------------------------------------------------- interaction contract


@pytest.mark.parametrize("experiment", EXPERIMENTS)
def test_output_is_empty_before_interaction(experiment):
    ctx = make_ctx(experiment)
    assert out_html(ctx) == "<div></div>", "output region is not empty on load"
    assert count_tag(ctx, "svg") == 0, "a chart exists in the DOM before Reproduce"


@pytest.mark.parametrize("experiment", EXPERIMENTS)
def test_reproduce_creates_card_and_chart(experiment):
    ctx = make_ctx(experiment)
    ctx.eval('document.getElementById("controls").dispatch("submit");')
    html = out_html(ctx)
    assert "Reproduced result" in html, "no result card after Reproduce"
    assert count_tag(ctx, "svg") >= 1, "no chart created by Reproduce"
    assert count_tag(ctx, "table") >= 1, "no numerator/denominator table after Reproduce"
    assert "How was this calculated?" in html, "calculation details missing"
    assert re.search(r"\d+(\.\d+)?%", html), "no computed percentage in the result"


@pytest.mark.parametrize("experiment", EXPERIMENTS)
def test_reset_removes_everything(experiment):
    ctx = make_ctx(experiment)
    ctx.eval('document.getElementById("controls").dispatch("submit");')
    assert count_tag(ctx, "svg") >= 1
    ctx.eval('document.getElementById("reset").dispatch("click");')
    assert out_html(ctx) == "<div></div>", "Reset left content behind"
    assert count_tag(ctx, "svg") == 0, "Reset left a chart in the DOM"
    assert ctx.eval('document.getElementById("reset").disabled') is True


def test_reset_button_starts_disabled():
    html = (DOCS / "index.html").read_text()
    assert re.search(r'id="reset"[^>]*\bdisabled\b', html), "Reset should start disabled"


# ---------------------------------------------------------------- numbers are real


def test_discovery_matches_the_aggregate_counts():
    ctx = make_ctx("discovery")
    ctx.eval('document.getElementById("controls").dispatch("submit");')
    html = out_html(ctx)
    p = STATS["experiments"]["discovery_vs_localized"]["pooled"]
    for v in (p["targeted"]["x"], p["targeted"]["n"], p["blind"]["x"], p["b"], p["c"]):
        assert str(v) in html, f"count {v} missing from the reproduced card"
    rate = 100 * p["targeted"]["x"] / p["targeted"]["n"]
    assert f"{rate:.1f}%" in html


def test_every_experiment_reports_a_denominator():
    for experiment in EXPERIMENTS:
        ctx = make_ctx(experiment)
        ctx.eval('document.getElementById("controls").dispatch("submit");')
        html = out_html(ctx)
        assert "Cases" in html or "Trials" in html or "Denominator" in html, \
            f"{experiment} reports no denominator"

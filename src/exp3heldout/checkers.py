"""Deterministic checkers for the held-out corpus (no model involvement anywhere).

Every frozen case carries a checker spec. `check(spec, numbered_text)` re-extracts the relation's values from the
variant manuscript itself and returns True (relation holds / consistent), False (relation violated / inconsistent) or
None (extraction failed -> the case is rejected at the dataset audit, never scored).

Mutations are always in-line string replacements, so line numbers are identical in E0, E1 and E2 and a spec can name
lines directly. Checkers use only arithmetic, string and regex operations.
"""
from __future__ import annotations

import re

LINE_RE = re.compile(r"^\[L(\d{5})\] (.*)$")


def lines_of(numbered_text: str) -> dict[int, str]:
    out = {}
    for ln in numbered_text.split("\n"):
        m = LINE_RE.match(ln)
        if m:
            out[int(m.group(1))] = m.group(2)
    return out


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", "").replace("\\,", "").replace("−", "-").replace("--", "-"))
    except ValueError:
        return None


def _extract(lines, line_no, rx, group=1):
    txt = lines.get(int(line_no))
    if txt is None:
        return None
    m = re.search(rx, txt)
    if not m:
        return None
    try:
        return m.group(group)
    except IndexError:
        return None


def _extract_num(lines, line_no, rx, group=1):
    v = _extract(lines, line_no, rx, group)
    return None if v is None else _num(v)


# --------------------------------------------------------------------------- relation checkers

def chk_arith(spec, lines):
    """A stated result must follow from stated operands: op in {div, pct, diff, ratio_pct, prod}."""
    res = _extract_num(lines, spec["line_result"], spec["re_result"])
    ops = [_extract_num(lines, l, r) for l, r in zip(spec["lines_ops"], spec["res_ops"])]
    if res is None or any(o is None for o in ops):
        return None
    op = spec["op"]
    try:
        if op == "div":
            want = ops[0] / ops[1]
        elif op == "pct":
            want = 100.0 * ops[0] / ops[1]
        elif op == "diff":
            want = ops[0] - ops[1]
        elif op == "pct_diff":
            want = 100.0 * (ops[0] - ops[1]) / ops[1]
        elif op == "prod":
            want = ops[0] * ops[1]
        elif op == "sum":
            want = sum(ops)
        else:
            return None
    except ZeroDivisionError:
        return None
    return abs(res - want) <= spec["tol"]


def chk_equal(spec, lines):
    """Two or more slots reporting the same quantity must agree within tolerance."""
    vals = [_extract_num(lines, s["line"], s["re"]) for s in spec["slots"]]
    if any(v is None for v in vals):
        return None
    return max(vals) - min(vals) <= spec["tol"]


def chk_xref(spec, lines):
    """A cited cross-reference must resolve to an existing label whose environment matches the declared type."""
    lab = _extract(lines, spec["line"], spec["re_label"])
    if lab is None:
        return None
    env = spec["label_envs"].get(lab)
    if env is None:
        return False           # dangling reference
    return env == spec["declared"]


def chk_stat_sig(spec, lines):
    """A significance claim must agree with the reported p-value at the stated threshold."""
    p = _extract_num(lines, spec["line_p"], spec["re_p"])
    claim_txt = lines.get(int(spec["line_claim"]))
    if p is None or claim_txt is None:
        return None
    m = re.search(spec["re_claim"], claim_txt)
    if not m:
        return None
    negated = bool(re.search(spec["re_negation"], claim_txt))
    claims_significant = not negated
    return claims_significant == (p < spec["alpha"])


def chk_range(spec, lines):
    """A reported central value must lie inside the reported range."""
    v = _extract_num(lines, spec["line_val"], spec["re_val"])
    lo = _extract_num(lines, spec["line_lo"], spec["re_lo"])
    hi = _extract_num(lines, spec["line_hi"], spec["re_hi"])
    if None in (v, lo, hi):
        return None
    lo, hi = min(lo, hi), max(lo, hi)
    return lo - spec["tol"] <= v <= hi + spec["tol"]


def chk_extreme(spec, lines):
    """A superlative claim must be supported by the values the passage reports."""
    claimed = _extract_num(lines, spec["line_claimed"], spec["re_claimed"])
    others = [_extract_num(lines, l, r) for l, r in zip(spec["lines_others"], spec["res_others"])]
    if claimed is None or any(o is None for o in others):
        return None
    return claimed >= max(others) if spec["direction"] == "max" else claimed <= min(others)


CHECKERS = {"chk_arith": chk_arith, "chk_equal": chk_equal, "chk_xref": chk_xref,
            "chk_stat_sig": chk_stat_sig, "chk_range": chk_range, "chk_extreme": chk_extreme}


def check(spec: dict, numbered_text: str):
    """True = relation consistent, False = violated, None = not extractable."""
    return CHECKERS[spec["fn"]](spec, lines_of(numbered_text))

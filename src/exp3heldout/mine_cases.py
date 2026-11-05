#!/usr/bin/env python3
"""Mine native, mechanically verifiable cases from a prepared manuscript (no model involvement anywhere).

    python exp3heldout/mine_cases.py --all            # every prepared paper in exp3heldout/papers
    python exp3heldout/mine_cases.py --papers <id>..  # selected papers
    python exp3heldout/mine_cases.py --dev            # yield check on the OLD Experiment 2B papers

For each of the six frozen defect families the miner searches the standardised manuscript for a relation that can be
re-checked deterministically from the manuscript text, then builds two minimal native mutations of existing content:
  E0  defective variant (relation violated)
  E2  a distinct minimal mutation violating the same relation in another way
E1 is the unmodified manuscript. A candidate is kept only if the frozen checker returns consistent(E1),
inconsistent(E0) and inconsistent(E2), and if applying each edit leaves the line numbering unchanged.

Edits are addressed as (line, old, new) where `old` is the smallest window around the mutated literal that occurs
exactly once in that line, so a value repeated inside a long paragraph is still edited unambiguously.
Output: exp3heldout/mined/<paper>.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2b"))
sys.path.insert(0, str(ROOT / "exp3heldout"))
import normalize as N  # noqa: E402
import checkers as C  # noqa: E402

PAPERS = ROOT / "exp3heldout/papers"
OUT = ROOT / "exp3heldout/mined"
MAX_PER_FAMILY = 3
TARGET_PER_PAPER = 12
SOFT_CAP = 3
NUM = r"\d+(?:\.\d+)?"

SETTING_WORDS = ("batch size", "learning rate", "epochs", "folds", "iterations", "layers", "hidden units", "seeds",
                 "replicates", "simulations", "participants", "patients", "subjects", "samples", "window", "dropout",
                 "kernel size", "temperature", "threshold", "trials", "runs", "steps", "dimension", "neighbors",
                 "neighbours", "clusters", "components", "trees", "estimators", "beam", "warmup", "weight decay",
                 "resolution", "grid", "timestep", "time step", "horizon", "bandwidth", "burn-in", "chains")
METRIC_WORDS = ("accuracy", "auc", "f1", "dice", "precision", "recall", "rmse", "mae", "mse", "psnr", "ssim", "error",
                "loss", "sensitivity", "specificity", "correlation", "iou", "bleu", "perplexity", "throughput",
                "latency", "efficiency", "yield", "score", "rate", "gain", "improvement", "coverage", "power")
CLAIM_MAX = ("highest", "largest", "greatest", "best", "maximum", "strongest", "most accurate", "outperform", "top")
CLAIM_MIN = ("lowest", "smallest", "least", "minimum", "weakest", "fewest")
NEG_SIG = r"\b(?:not|no|non-?|without|failed to reach)\s+(?:a\s+)?(?:statistical(?:ly)?\s+)?signific"
REL_CUES = ("%", "percent", "fold", "ratio", "times", "differen", "lift", "gain", "increase", "decrease", "reduction",
            "improvement", "total", "sum", "average", "mean", "drop", "relative", "speedup", "speed-up")
STOP = set("the and for with that this from were was are have has been also which when where their there into over "
           "under between within using used than then each other both more most less least about after before during "
           "such these those they them its our we can may not but all any one two three per model models data".split())
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\\(])")


# --------------------------------------------------------------------------- helpers

def esc(s: str) -> str:
    return re.escape(s)


def fmt_like(value: float, original: str) -> str:
    dec = len(original.split(".")[1]) if "." in original else 0
    return f"{value:.{dec}f}"


def mutate(original: str, factor: float, min_rel: float = 0.15) -> str | None:
    try:
        v = float(original)
    except ValueError:
        return None
    if v == 0:
        return None
    s = fmt_like(v * factor, original)
    try:
        nv = float(s)
    except ValueError:
        return None
    if s == original or nv == 0 or abs(nv - v) / max(abs(v), 1e-9) < min_rel:
        return None
    return s


def uniq_window(line: str, literal: str, occurrence: int = 0):
    """Smallest window around one occurrence of `literal` that appears exactly once in `line`."""
    starts = [m.start() for m in re.finditer(esc(literal), line)]
    if not starts or occurrence >= len(starts):
        return None
    i = starts[occurrence]
    for pad in (0, 6, 12, 20, 30, 45, 65, 90):
        a, b = max(0, i - pad), min(len(line), i + len(literal) + pad)
        win = line[a:b]
        if line.count(win) == 1:
            return win, a
    return None


def uniq_edit(line: str, literal: str, new_literal: str, occurrence: int = 0):
    got = uniq_window(line, literal, occurrence)
    if got is None or new_literal is None:
        return None
    win, a = got
    rel = line.index(literal, a) - a
    new_win = win[:rel] + new_literal + win[rel + len(literal):]
    if new_win == win:
        return None
    return {"old": win, "new": new_win}


def ctx_re(s: str) -> str:
    return r"\s*".join(esc(t) for t in s.split())


def slot_regex(line: str, literal: str, occurrence: int = 0):
    """Regex capturing the numeric slot by its context; must match exactly once and select this occurrence."""
    starts = [m.start() for m in re.finditer(esc(literal), line)]
    if occurrence >= len(starts):
        return None
    i = starts[occurrence]
    for pad in (14, 24, 38, 60, 90):
        left = ctx_re(line[max(0, i - pad):i].strip())
        right = ctx_re(line[i + len(literal):i + len(literal) + max(8, pad // 2)].strip())
        for rx in ([rf"{left}\s*({NUM})"] if left else []) + ([rf"({NUM})\s*{right}"] if right else []):
            try:
                ms = list(re.finditer(rx, line))
            except re.error:
                continue
            if len(ms) == 1 and ms[0].group(1) == literal:
                return rx
    return None


def clean_words(text: str) -> list[str]:
    t = re.sub(r"\\[a-zA-Z@]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ", text)
    t = re.sub(r"[^A-Za-z0-9\-\s]", " ", t)
    return [w for w in t.split() if w]


def anchor(text: str, exclude: list[str], want: int = 10) -> str:
    t = text
    for e in exclude:
        t = t.replace(e, " ")
    best, cur = [], []
    for w in clean_words(t):
        if re.fullmatch(r"[A-Za-z][A-Za-z\-]*", w) and len(w) > 1:
            cur.append(w)
            if len(cur) > len(best):
                best = list(cur)
        else:
            cur = []
    return " ".join(best[:want]) if best else " ".join(clean_words(t)[:want])


def sentences(line: str):
    out, pos = [], 0
    for part in SENT_SPLIT.split(line):
        i = line.index(part, pos)
        out.append((i, part))
        pos = i + len(part)
    return out


def numbers_in(text: str):
    out = []
    for m in re.finditer(rf"(?<![\w.]){NUM}(?![\w])", text):
        lit = m.group(0)
        v = float(lit)
        if "." not in lit and (v < 2 or v > 100000):
            continue
        if "." not in lit and 1900 <= v <= 2100:
            continue
        out.append((lit, m.start()))
    return out


def section_map(lines):
    out, cur = {}, "front"
    for ln in sorted(lines):
        m = re.match(r"\\(?:sub)*section\*?\{([^}]*)\}", lines[ln])
        if m:
            cur = m.group(1).lower()
        out[ln] = cur
    return out


def label_envs(body: str) -> dict:
    envs, stack = {}, []
    for raw in body.split("\n"):
        for m in re.finditer(r"\\(begin|end)\{([a-zA-Z*]+)\}", raw):
            if m.group(1) == "begin":
                stack.append(m.group(2).rstrip("*"))
            elif stack:
                stack.pop()
        for m in re.finditer(r"\\label\{([^}]+)\}", raw):
            env = next((e for e in reversed(stack)
                        if e in ("table", "figure", "algorithm", "equation", "align", "gather", "subfigure",
                                 "subtable")), None)
            env = {"align": "equation", "gather": "equation", "subfigure": "figure", "subtable": "table"}.get(env, env)
            if env is None:
                env = "section" if re.search(r"\\(?:sub)*section", raw) else "other"
            envs[m.group(1)] = env
    return envs


DECLARED = {"table": "table", "tab": "table", "tables": "table", "figure": "figure", "fig": "figure",
            "figures": "figure", "section": "section", "sec": "section", "equation": "equation", "eq": "equation",
            "eqn": "equation", "algorithm": "algorithm", "alg": "algorithm", "appendix": "section"}


# --------------------------------------------------------------------------- miners

def mine_arith(lines, secs, body, envs):
    out = []
    for ln in sorted(lines):
        t = lines[ln]
        if t.count("&") > 3:
            continue
        for _, sent in sentences(t):
            low = sent.lower()
            if not any(w in low for w in REL_CUES):
                continue
            nums = numbers_in(sent)
            if not (3 <= len(nums) <= 9):
                continue
            vals = [(lit, float(lit), st) for lit, st in nums]
            found = []
            for i, (li, vi, si) in enumerate(vals):
                for j, (lj, vj, sj) in enumerate(vals):
                    for k, (lk, vk, sk) in enumerate(vals):
                        if len({i, j, k}) != 3 or vj == 0:
                            continue
                        for op, want in (("pct", 100.0 * vk / vj), ("div", vk / vj), ("diff", vk - vj),
                                         ("sum", vk + vj)):
                            if want <= 0 or abs(want) > 1e7:
                                continue
                            tol = max(abs(vi) * 0.004, (10 ** -len(li.split(".")[1])) / 2 if "." in li else 0.5)
                            if abs(vi - want) <= tol:
                                found.append({"op": op, "res": li, "a": lk, "b": lj, "tol": tol, "pos": si})
            if not found or len({frozenset((f["res"], f["a"], f["b"])) for f in found}) != 1:
                continue
            prio = {"pct": 0, "div": 1, "diff": 2, "sum": 3}
            best = sorted(found, key=lambda f: (prio[f["op"]], -f["pos"]))[0]
            res_lit, a_lit, b_lit, tol, op = best["res"], best["a"], best["b"], best["tol"], best["op"]
            if len({res_lit, a_lit, b_lit}) != 3:
                continue
            decs = [x for x in (res_lit, a_lit, b_lit) if "." in x and len(x.split(".")[1]) >= 2]
            if len(decs) < 2 and "%" not in sent:
                continue
            ri = sent.index(res_lit)
            if not any(w in sent[max(0, ri - 30):ri + len(res_lit) + 25].lower() for w in REL_CUES):
                continue
            rr, ra, rb = slot_regex(t, res_lit), slot_regex(t, a_lit), slot_regex(t, b_lit)
            if not all((rr, ra, rb)):
                continue
            e0v, e2v = mutate(res_lit, 1.29), mutate(a_lit, 1.37)
            e0, e2 = uniq_edit(t, res_lit, e0v), uniq_edit(t, a_lit, e2v)
            if not e0 or not e2:
                continue
            out.append({"family": "arithmetic", "line": ln, "target_lines": [ln],
                        "spec": {"fn": "chk_arith", "line_result": ln, "re_result": rr, "lines_ops": [ln, ln],
                                 "res_ops": [ra, rb], "op": op, "tol": tol},
                        "edits": {"E0": [{"line": ln, **e0}], "E2": [{"line": ln, **e2}]},
                        "values": {"stated": res_lit, "op": op, "operand_a": a_lit, "operand_b": b_lit,
                                   "e0_value": e0v, "e2_value": e2v},
                        "anchor": anchor(sent, [res_lit, a_lit, b_lit])})
    return out


def _repeat_pairs(lines, vocab, require_prose=True, max_occ=3, min_gap=5):
    pos = {}
    for ln in sorted(lines):
        for m in re.finditer(rf"(?<![\w.]){NUM}(?![\w])", lines[ln]):
            lit = m.group(0)
            v = float(lit)
            if "." not in lit or v == 0 or 1900 <= v <= 2100:
                continue
            pos.setdefault(lit, []).append((ln, m.start()))
    pairs = []
    for lit, occ in pos.items():
        if not (2 <= len(occ) <= max_occ):
            continue
        l1, s1 = occ[0]
        nxt = next(((l, s) for l, s in occ[1:] if abs(l - l1) >= min_gap), None)
        if nxt is None:
            continue
        l2, s2 = nxt
        ctx1 = lines[l1][max(0, s1 - 110):s1 + 70].lower()
        ctx2 = lines[l2][max(0, s2 - 110):s2 + 70].lower()
        kw = [w for w in vocab if w in ctx1 and w in ctx2]
        if not kw:
            w1 = {w for w in re.findall(r"[a-z]{4,}", ctx1) if w not in STOP}
            w2 = {w for w in re.findall(r"[a-z]{4,}", ctx2) if w not in STOP}
            kw = sorted(w1 & w2)
            if not kw:
                continue
        if require_prose and not [l for l in (l1, l2) if lines[l].count("&") <= 2]:
            continue
        pairs.append({"lit": lit, "l1": l1, "l2": l2, "kw": kw[0]})
    return pairs


def _equal_case(lines, p, family, f0, f2, extra):
    lit, l1, l2 = p["lit"], p["l1"], p["l2"]
    r1, r2 = slot_regex(lines[l1], lit), slot_regex(lines[l2], lit)
    if not r1 or not r2:
        return None
    e0v, e2v = mutate(lit, f0, min_rel=0.1), mutate(lit, f2, min_rel=0.1)
    e0, e2 = uniq_edit(lines[l1], lit, e0v), uniq_edit(lines[l2], lit, e2v)
    if not e0 or not e2:
        return None
    return {"family": family, "line": l1, "target_lines": sorted({l1, l2}),
            "spec": {"fn": "chk_equal", "tol": max(1e-9, abs(float(lit)) * 0.004),
                     "slots": [{"line": l1, "re": r1}, {"line": l2, "re": r2}]},
            "edits": {"E0": [{"line": l1, **e0}], "E2": [{"line": l2, **e2}]},
            "values": {"value": lit, "e0_value": e0v, "e2_value": e2v, **extra},
            "anchor": anchor(lines[l1], [lit])}


def mine_numerical(lines, secs, body, envs):
    return [c for p in _repeat_pairs(lines, METRIC_WORDS)
            if (c := _equal_case(lines, p, "numerical", 1.23, 0.72, {"keyword": p["kw"]}))]


def mine_method(lines, secs, body, envs):
    out = []
    for p in _repeat_pairs(lines, SETTING_WORDS, require_prose=False):
        if not any(w in lines[p["l1"]].lower() for w in SETTING_WORDS):
            continue
        c = _equal_case(lines, p, "method_result", 2.0, 0.45, {"setting": p["kw"]})
        if c:
            out.append(c)
    for kw in SETTING_WORDS:
        hits = [(ln, m) for ln in sorted(lines)
                for m in re.finditer(rf"{esc(kw)}[^.\n]{{0,28}}?(?<![\d.])(\d{{2,5}})(?![\d.])", lines[ln], re.I)]
        if len(hits) != 2:
            continue
        (l1, m1), (l2, m2) = hits
        if l1 == l2 or m1.group(1) != m2.group(1):
            continue
        c = _equal_case(lines, {"lit": m1.group(1), "l1": l1, "l2": l2, "kw": kw}, "method_result", 2.0, 0.4,
                        {"setting": kw})
        if c:
            out.append(c)
    return out


def mine_xref(lines, secs, body, envs):
    out = []
    for ln in sorted(lines):
        t = lines[ln]
        for m in re.finditer(r"\b(Table|Figure|Fig\.?|Section|Sec\.?|Equation|Eq\.?|Algorithm)[~ ]*"
                             r"\\(?:ref|eqref|autoref)\{([^}]+)\}", t):
            word, lab = m.group(1).lower().rstrip("."), m.group(2)
            declared = DECLARED.get(word)
            if declared is None or envs.get(lab) != declared:
                continue
            others = sorted(l for l, e in envs.items()
                            if e in ("table", "figure", "equation", "algorithm") and e != declared)
            if not others:
                continue
            wrong = others[0]
            dangling = (lab[:-1] if len(lab) > 4 else lab) + "zz"
            while dangling in envs:
                dangling += "q"
            full = m.group(0)
            e0 = uniq_edit(t, full, full.replace(lab, wrong))
            e2 = uniq_edit(t, full, full.replace(lab, dangling))
            if not e0 or not e2:
                continue
            rx = None
            for pad in (0, 20, 40):
                cand = (ctx_re(t[max(0, m.start() - pad):m.start()].strip()) +
                        rf"\s*{esc(m.group(1))}[~ ]*\\(?:ref|eqref|autoref)\{{([^}}]+)\}}")
                try:
                    ms = list(re.finditer(cand, t))
                except re.error:
                    continue
                if len(ms) == 1 and ms[0].group(1) == lab:
                    rx = cand
                    break
            if rx is None:
                continue
            out.append({"family": "cross_reference", "line": ln, "target_lines": [ln],
                        "spec": {"fn": "chk_xref", "line": ln, "re_label": rx, "declared": declared,
                                 "label_envs": envs},
                        "edits": {"E0": [{"line": ln, **e0}], "E2": [{"line": ln, **e2}]},
                        "values": {"declared": declared, "label": lab, "wrong_label": wrong, "dangling": dangling},
                        "anchor": anchor(t, [full])})
    return out


def mine_statistical(lines, secs, body, envs):
    out = []
    for ln in sorted(lines):
        t = lines[ln]
        if not re.search(r"signific", t, re.I):
            continue
        for m in re.finditer(r"\$?\bp\b\$?(?:\s*[-\u2013]?\s*values?)?\s*(?:=|<|\\leq|\\le|\\lt|of|was|were)\s*"
                             r"\$?\s*(0?\.\d+)", t, re.I):
            pv = m.group(1)
            try:
                p = float(pv)
            except ValueError:
                continue
            sig = re.search(r"(signific\w*)", t, re.I)
            negated = bool(re.search(NEG_SIG, t, re.I))
            if sig is None or (p < 0.05) == negated:
                continue
            rx = slot_regex(t, pv)
            if rx is None:
                continue
            e0v = "0.21" if p < 0.05 else "0.001"
            e0 = uniq_edit(t, pv, e0v)
            if negated:
                neg = re.search(NEG_SIG, t, re.I).group(0)
                e2 = uniq_edit(t, neg, re.sub(r"\b(not|no|non-?)\s*", "", neg, count=1, flags=re.I))
            else:
                e2 = uniq_edit(t, sig.group(1), "not " + sig.group(1))
            if not e0 or not e2:
                continue
            out.append({"family": "statistical", "line": ln, "target_lines": [ln],
                        "spec": {"fn": "chk_stat_sig", "line_p": ln, "re_p": rx, "line_claim": ln,
                                 "re_claim": r"signific", "re_negation": NEG_SIG, "alpha": 0.05},
                        "edits": {"E0": [{"line": ln, **e0}], "E2": [{"line": ln, **e2}]},
                        "values": {"p": pv, "negated": negated, "alpha": 0.05, "e0_value": e0v},
                        "anchor": anchor(t, [pv])})
            break
    for ln in sorted(lines):
        t = lines[ln]
        for m in re.finditer(rf"(?:mean|median|average)[^.\n]{{0,45}}?({NUM})[^.\n]{{0,70}}?rang\w+[^.\n]{{0,25}}?"
                             rf"(?:from\s*)?({NUM})\s*(?:to|--|-|\u2013)\s*({NUM})", t, re.I):
            v, lo, hi = m.group(1), m.group(2), m.group(3)
            try:
                fv, flo, fhi = float(v), float(lo), float(hi)
            except ValueError:
                continue
            if not (min(flo, fhi) <= fv <= max(flo, fhi)) or len({v, lo, hi}) != 3:
                continue
            rv, rl, rh = slot_regex(t, v), slot_regex(t, lo), slot_regex(t, hi)
            if not all((rv, rl, rh)):
                continue
            e0 = uniq_edit(t, v, fmt_like(max(flo, fhi) * 1.4 + 0.01, v))
            e2hi = fmt_like(min(flo, fhi) * 0.5, hi) if fv > min(flo, fhi) else None
            e2 = uniq_edit(t, hi, e2hi) if e2hi and e2hi != hi else None
            if not e0 or not e2:
                continue
            out.append({"family": "statistical", "line": ln, "target_lines": [ln],
                        "spec": {"fn": "chk_range", "line_val": ln, "re_val": rv, "line_lo": ln, "re_lo": rl,
                                 "line_hi": ln, "re_hi": rh, "tol": 0.0},
                        "edits": {"E0": [{"line": ln, **e0}], "E2": [{"line": ln, **e2}]},
                        "values": {"value": v, "low": lo, "high": hi, "kind": "range_containment"},
                        "anchor": anchor(t, [v, lo, hi])})
            break
    return out


def mine_claim(lines, secs, body, envs):
    out = []
    for ln in sorted(lines):
        t = lines[ln]
        if t.count("&") > 3:
            continue
        for _, sent in sentences(t):
            low = sent.lower()
            direction = ("max" if any(w in low for w in CLAIM_MAX) else
                         "min" if any(w in low for w in CLAIM_MIN) else None)
            if direction is None:
                continue
            nums = numbers_in(sent)
            dec = [x for x in nums if "." in x[0] and len(x[0].split(".")[1]) >= 2]
            pct = [x for x in nums if f"{x[0]}\\%" in sent or f"{x[0]}%" in sent]
            group = dec if len(dec) >= 2 else (pct if len(pct) >= 2 else [])
            if not (2 <= len(group) <= 6):
                continue
            claim_pos = min((low.find(w) for w in (CLAIM_MAX if direction == "max" else CLAIM_MIN) if w in low),
                            default=0)
            fv = [(lit, float(lit), st) for lit, st in group]
            pick = max(fv, key=lambda x: x[1]) if direction == "max" else min(fv, key=lambda x: x[1])
            if abs(pick[2] - claim_pos) > 130:
                continue
            claimed = pick[0]
            others = [x[0] for x in fv if x[0] != claimed]
            if not others or len(set(others)) != len(others):
                continue
            fo = [float(o) for o in others]
            rc = slot_regex(t, claimed)
            ro = [slot_regex(t, o) for o in others]
            if rc is None or any(r is None for r in ro):
                continue
            best = max(fo) if direction == "max" else min(fo)
            fc = float(claimed)
            e0v = fmt_like(best * (0.86 if direction == "max" else 1.16), claimed)
            tgt = others[fo.index(best)]
            e2v = fmt_like(fc * (1.14 if direction == "max" else 0.86), tgt)
            if e0v == claimed or e2v == tgt:
                continue
            e0, e2 = uniq_edit(t, claimed, e0v), uniq_edit(t, tgt, e2v)
            if not e0 or not e2:
                continue
            out.append({"family": "claim_evidence", "line": ln, "target_lines": [ln],
                        "spec": {"fn": "chk_extreme", "line_claimed": ln, "re_claimed": rc,
                                 "lines_others": [ln] * len(others), "res_others": ro, "direction": direction},
                        "edits": {"E0": [{"line": ln, **e0}], "E2": [{"line": ln, **e2}]},
                        "values": {"claimed": claimed, "others": others, "direction": direction,
                                   "e0_value": e0v, "e2_value": e2v},
                        "anchor": anchor(sent, [claimed] + others)})
            break
    return out


MINERS = {"arithmetic": mine_arith, "numerical": mine_numerical, "cross_reference": mine_xref,
          "statistical": mine_statistical, "claim_evidence": mine_claim, "method_result": mine_method}


# --------------------------------------------------------------------------- validation

def apply_edits(body: str, edits: list) -> str | None:
    raw = body.split("\n")
    for e in edits:
        i = int(e["line"]) - 1          # exp2b/normalize.number() numbers by absolute line index
        if not (0 <= i < len(raw)) or raw[i].count(e["old"]) != 1:
            return None
        raw[i] = raw[i].replace(e["old"], e["new"])
    return "\n".join(raw)


def validate(cand, body):
    numbered, _ = N.number(body)
    n_lines = len(C.lines_of(numbered))
    if C.check(cand["spec"], numbered) is not True:
        return None
    variants = {}
    for st in ("E0", "E2"):
        nb = apply_edits(body, cand["edits"][st])
        if nb is None:
            return None
        nnum, _ = N.number(nb)
        if len(C.lines_of(nnum)) != n_lines or C.check(cand["spec"], nnum) is not False:
            return None
        variants[st] = nb
    return variants


def mine_paper(pid: str, body: str, target: int = TARGET_PER_PAPER) -> list:
    """Validated candidates per family (capped), then a round-robin pick that maximises family balance."""
    numbered, _ = N.number(body)
    lines = C.lines_of(numbered)
    secs, envs = section_map(lines), label_envs(body)
    pools, used = {}, set()
    for fam, fn in MINERS.items():
        good = []
        for cand in fn(lines, secs, body, envs):
            if len(good) >= MAX_PER_FAMILY:
                break
            if set(cand["target_lines"]) & used:
                continue
            if validate(cand, body) is None:
                continue
            cand["paper"] = pid
            good.append(cand)
            used |= set(cand["target_lines"])
        pools[fam] = good
    # round-robin with a soft per-family cap first (balance), then fill to target from remaining candidates
    kept = []
    for cap in (SOFT_CAP, MAX_PER_FAMILY):
        round_i = 0
        while len(kept) < target and round_i < cap:
            for fam in MINERS:
                if len(kept) >= target:
                    break
                if len(pools[fam]) > round_i and pools[fam][round_i] not in kept:
                    kept.append(pools[fam][round_i])
            round_i += 1
    return kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--papers", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dev", action="store_true")
    a = ap.parse_args()
    if a.dev:
        grand = {}
        for pid in ("2609.03933", "2609.01018", "2609.00473", "2609.04261", "2609.01675"):
            cases = mine_paper(pid, (ROOT / f"exp2b/papers/{pid}/E1.tex").read_text())
            by = {}
            for c in cases:
                by[c["family"]] = by.get(c["family"], 0) + 1
                grand[c["family"]] = grand.get(c["family"], 0) + 1
            print(pid, len(cases), by, flush=True)
        print("GRAND", grand)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    pids = a.papers or ([p.name for p in sorted(PAPERS.iterdir()) if (p / "E1.tex").exists()] if a.all else [])
    for pid in pids:
        cases = mine_paper(pid, (PAPERS / pid / "E1.tex").read_text())
        by = {}
        for c in cases:
            by[c["family"]] = by.get(c["family"], 0) + 1
        (OUT / f"{pid}.json").write_text(json.dumps({"paper": pid, "n_cases": len(cases), "by_family": by,
                                                     "cases": cases}, indent=1))
        print(f"{pid}: {len(cases)} cases {by}", flush=True)


if __name__ == "__main__":
    main()

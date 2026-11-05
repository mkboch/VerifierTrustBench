#!/usr/bin/env python3
"""Section 9: full Anthropic accounting and a deterministic hand-parse sensitivity.

EXISTING RECORDS ONLY. No new Anthropic request is issued in this phase.

Every record is placed in exactly one mutually exclusive category, and the previously
reported "49 compliant + 8 prose = 57" is reconciled against the frozen strict parser.

The hand parse is deterministic and mechanical: a prose response is resolved only if
exactly one verdict token from the frozen vocabulary appears literally in its text. There
is no LLM judge, no paraphrase matching and no human interpretation of intent.
"""
from __future__ import annotations
import collections, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
TV = ROOT / "nature_extension/final_topvenue_validation_20261018"
for p in ("exp3heldout", "exp2b", "exp2br"):
    sys.path.insert(0, str(ROOT / p))
import design_heldout as D   # noqa: E402
import client as C           # noqa: E402

VERDICTS = C.VERDICTS
plan = D.Plan()
cases = {c["case_id"]: c for c in plan.cases}
rs = [json.loads(l) for l in (TV / "frontier/frontier_anthropic_trials.jsonl").open()]


def lenient(txt):
    """The parser the earlier frontier analysis used: strict JSON, then a brace scan."""
    if not txt:
        return None
    t = txt.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def strict(txt):
    """The frozen protocol parser. Brace scanning is explicitly NOT permitted."""
    try:
        obj, _f = C.strict_json(txt)
    except Exception:
        return None
    parsed, _err, _w = C.validate_targeted(obj)
    return parsed


def handparse(txt):
    """Deterministic sensitivity parse. Resolved only when exactly one verdict token from
    the frozen vocabulary appears literally. No inference about intent."""
    if not txt:
        return None, "empty"
    found = {v for v in VERDICTS if re.search(rf"\b{v}\b", txt)}
    if len(found) == 1:
        return found.pop(), "single_explicit_token"
    if not found:
        return None, "no_explicit_verdict_token"
    return None, f"ambiguous_multiple_tokens:{','.join(sorted(found))}"


binary = [r for r in rs if r["rung"] == "RELATION_LOCALIZED_BINARY_VERDICT"]
findlist = [r for r in rs if r["rung"] != "RELATION_LOCALIZED_BINARY_VERDICT"]

cat = {}
for r in binary:
    cid = r["case_id"]
    if r["status"].startswith("REFUSAL") and r.get("stop_reason") == "refusal":
        cat[cid] = ("POLICY_REFUSAL", None, None)
    elif r["status"].startswith("REFUSAL") or r["status"].startswith("ERROR"):
        cat[cid] = (f"TECHNICAL_FAILURE:{r.get('stop_reason') or r['status']}", None, None)
    else:
        s, l = strict(r["content"]), lenient(r["content"])
        if s is not None:
            cat[cid] = ("COMPLIANT_STRICT", s.get("verdict"), None)
        elif isinstance(l, dict) and l.get("verdict") in VERDICTS:
            cat[cid] = ("RECOVERABLE_BY_BRACE_SCAN", l.get("verdict"), None)
        else:
            hp, why = handparse(r["content"])
            cat[cid] = ("PROSE", None, (hp, why))

counts = collections.Counter(v[0] for v in cat.values())
n_strict = counts["COMPLIANT_STRICT"]
n_brace = counts["RECOVERABLE_BY_BRACE_SCAN"]
n_prose = counts["PROSE"]
n_ref = counts["POLICY_REFUSAL"]
n_tech = sum(v for k, v in counts.items() if k.startswith("TECHNICAL_FAILURE"))

# accuracy under each reading
def acc(pred_of):
    n = k = 0
    for cid, (c, v, hp) in cat.items():
        p = pred_of(c, v, hp)
        if p is None:
            continue
        n += 1
        k += int(p == cases[cid]["truth"]["E0"])
    return {"n_scored": n, "n_correct": k,
            "accuracy_pct": round(100 * k / n, 1) if n else None,
            "n_of_60_scoreable": n}


strict_only = acc(lambda c, v, hp: v if c == "COMPLIANT_STRICT" else None)
brace_incl = acc(lambda c, v, hp: v if c in ("COMPLIANT_STRICT", "RECOVERABLE_BY_BRACE_SCAN") else None)
hand_incl = acc(lambda c, v, hp: (v if c in ("COMPLIANT_STRICT", "RECOVERABLE_BY_BRACE_SCAN")
                                  else (hp[0] if c == "PROSE" and hp else None)))

# finding-list rungs
fl = collections.defaultdict(lambda: collections.Counter())
fl_dupe = {}
for r in findlist:
    fl[r["rung"]][("POLICY_REFUSAL" if r.get("stop_reason") == "refusal"
                   else f"CLIENT_SIDE_ERROR:{r['status']}")] += 1
for rung in sorted(fl):
    ids = [r["case_id"] for r in findlist if r["rung"] == rung]
    dup = [k for k, v in collections.Counter(ids).items() if v > 1]
    fl_dupe[rung] = {"n_records": len(ids), "n_distinct_relations": len(set(ids)),
                     "duplicated_relations": dup}

refusal_language = []
seen = set()
for r in rs:
    if r.get("stop_reason") != "refusal":
        continue
    # a refusal returns no text block at all; what is recorded is the stop reason itself
    sig = (r["rung"], r.get("content") is None)
    if sig in seen:
        continue
    seen.add(sig)
    refusal_language.append({
        "rung": r["rung"], "stop_reason": r["stop_reason"],
        "text_blocks_returned": 0 if r.get("content") is None else 1,
        "recorded_text": (r.get("content") or "")[:200] or
                         "none — the API returned stop_reason='refusal' with zero content "
                         "blocks, so there is no refusal sentence to quote",
        "output_tokens": r.get("output_tokens")})

payload = {
    "label": "ANTHROPIC_ACCOUNTING_AND_SENSITIVITY",
    "scope": "existing records only; no new Anthropic request was issued in this phase",
    "llm_judge_used": False,
    "model": rs[0]["model"],
    "total_records": len(rs),
    "binary_verdict_rung": {
        "expected_cases": 60,
        "records": len(binary),
        "all_60_accounted": len(cat) == 60,
        "categories": dict(counts),
        "mutually_exclusive_total": sum(counts.values()),
    },
    "the_49_plus_8_reconciliation": {
        "previously_reported": "49 compliant + 8 prose = 57, with 3 unexplained",
        "the_missing_3": {
            "policy_refusals": n_ref,
            "technical_failures": n_tech,
            "detail": [f"{cid}: {c}" for cid, (c, _v, _h) in sorted(cat.items())
                       if c == "POLICY_REFUSAL" or c.startswith("TECHNICAL_FAILURE")],
            "explanation": "57 is the count of records whose status was OK. The remaining 3 "
                           "of the 60 are not OK at all: "
                           f"{n_ref} policy refusals (stop_reason='refusal') and "
                           f"{n_tech} technical failure (stop_reason='max_tokens', a truncation "
                           "the frozen protocol already classes as a technical failure, not a "
                           "refusal). 49 + 8 therefore sums to the OK subset, not to 60.",
        },
        "the_49_itself_is_parser_dependent": {
            "strict_frozen_parser_compliant": n_strict,
            "additionally_recoverable_by_brace_scan": n_brace,
            "sum": n_strict + n_brace,
            "explanation": "The earlier figure of 49 was produced by a parser that falls back "
                           "to scanning for the outermost {...} when strict JSON fails. The "
                           "frozen protocol parser (exp2b/client.py::strict_json) explicitly "
                           "forbids brace scanning. Under the frozen parser only "
                           f"{n_strict} of the 60 are compliant; a further {n_brace} contain a "
                           "readable JSON object embedded in prose. The strict count is the "
                           "primary one because it is the protocol the rest of the study used.",
        },
    },
    "prose_sensitivity_parse": {
        "rule": "deterministic: resolved only if exactly one token of the frozen verdict "
                "vocabulary appears literally in the text",
        "vocabulary": list(VERDICTS),
        "n_prose": n_prose,
        "resolved": sum(1 for c, _v, h in cat.values() if c == "PROSE" and h and h[0]),
        "unresolved": sum(1 for c, _v, h in cat.values() if c == "PROSE" and h and not h[0]),
        "reasons": dict(collections.Counter(h[1] for c, _v, h in cat.values()
                                            if c == "PROSE" and h)),
    },
    "accuracy": {
        "primary_strict_parser": strict_only,
        "sensitivity_including_brace_scan": brace_incl,
        "sensitivity_including_hand_parse": hand_incl,
        "note": "The three readings differ in how many of the 60 are scoreable, not in the "
                "scoring rule. No reading changes a verdict that the strict parser already read.",
    },
    "finding_list_rungs": {
        "per_rung": {k: dict(v) for k, v in fl.items()},
        "coverage": fl_dupe,
        "conclusion": "Every finding-list request that reached the provider was refused. The "
                      "interface is not measurable under the frozen prompt, which is why this "
                      "phase issues no further Anthropic requests.",
    },
    "refusal_language": {
        "summary": "The provider signalled refusal structurally rather than in prose: the API "
                   "returned stop_reason='refusal' with zero content blocks. There is "
                   "therefore no refusal sentence in the record to quote, and no manuscript "
                   "content is reproduced here.",
        "representative_records": refusal_language,
    },
    "what_was_not_done": ["no sentence ablation", "no prompt-bypass experiment",
                          "no new Anthropic request", "no LLM judge"],
}
(OUT / "data/ANTHROPIC_ACCOUNTING.json").write_text(json.dumps(payload, indent=1) + "\n")
print(json.dumps({k: payload[k] for k in
                  ("binary_verdict_rung", "the_49_plus_8_reconciliation",
                   "prose_sensitivity_parse", "accuracy")}, indent=1))

#!/usr/bin/env python3
"""Experiment 2B-broad technical preflight / validation gate for one served model.

    python exp2bbroad/preflight_broad.py --model <name> [--out exp2bbroad/results]

Technical checks only (scientific accuracy is never a criterion):
  P1 context      every one of the five frozen manuscripts fits: chat-templated prompt tokens (server /tokenize) +
                  max_tokens + 256 <= 32,768, for the bounded blind request and the longest targeted request.
  P2 server       /v1/models serves the expected checkpoint.
  P3 targeted     the frozen targeted schema returns valid JSON on the longest manuscript (2609.03933) and on one short one.
  P4 blind        the repaired (2B-R bounded) blind schema returns valid JSON on the longest manuscript.
  P5 final answer non-empty final content; where the server separates reasoning, reasoning is present but never scored.
  P6 repeatability three identical repeats of two targeted requests and one blind request; byte identity and verdict identity
                  are recorded. Non-determinism does NOT fail the gate: it is quantified and the model is labelled.
  P7 validity     no systemic failure: >= 90% of the preflight requests valid, and no status class dominating.
  P8 line IDs     every valid targeted output carries well-formed evidence_line_ids (^L[0-9]{5}$), none malformed.

The gate passes if P1-P5, P7 and P8 hold. P6 is reported. Results: results/preflight_<model>.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2bbroad"))
import models_broad as MB  # noqa: E402
sys.path.insert(0, str(ROOT / "exp2br"))
import client as C  # noqa: E402
import design as D  # noqa: E402
import protocol as P  # noqa: E402
import protocol_br as PBR  # noqa: E402

MAX_MODEL_LEN, MARGIN = 32768, 256
LONG_PAPER, SHORT_PAPER = "2609.03933", "2609.00473"


def tokenize(cfg, payload):
    body = {"model": payload["model"], "messages": payload["messages"], "add_generation_prompt": True}
    if payload.get("chat_template_kwargs"):
        body["chat_template_kwargs"] = payload["chat_template_kwargs"]
    req = urllib.request.Request(cfg["endpoint"] + "/tokenize", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=180).read())["count"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", default=str(ROOT / "exp2bbroad/results"))
    a = ap.parse_args()
    cfg = MB.MODELS[a.model]
    plan = D.Plan("full")
    out = {"model": a.model, "family": cfg["family"], "reasoning_mode": cfg["reasoning_mode"],
           "competence_class": MB.COMPETENCE_CLASS[a.model], "checks": {}}

    # P2 server identity
    with urllib.request.urlopen(cfg["endpoint"] + "/v1/models", timeout=60) as r:
        d = json.loads(r.read())["data"][0]
    out["checks"]["P2_server"] = {"served_id": d.get("id"), "root": d.get("root"), "max_model_len": d.get("max_model_len"),
                                  "pass": d.get("id") == cfg["served_name"] and d.get("root") == cfg["root"]}

    # P1 context on all five frozen manuscripts
    ctx, fits = {}, True
    by_paper = {}
    for c in plan.cases():
        by_paper.setdefault(c["paper"], []).append(c)
    for paper, cases in sorted(by_paper.items()):
        c = max(cases, key=lambda x: len(x["question"]))
        text, _ = plan.paper(c, "E1")
        rat = max((cc["rationales"][s]["false"] for cc in cases if cc.get("rationales") for s in ("E0", "E1")), key=len)
        tgt = MB.apply_extra(cfg, P.build_targeted(cfg, text, c["question"], P.exposure_text(
            "false_rationale", prior_verdict="ISSUE_PRESENT", prior_rationale=rat), 1))[0]
        bl = MB.apply_extra(cfg, PBR.build_blind_br(cfg, text, 1))[0]
        row = {}
        for name, pl, kind in (("blind", bl, "blind"), ("targeted_longest", tgt, "targeted")):
            n = tokenize(cfg, pl)
            tot = n + P.MAX_TOKENS[kind] + MARGIN
            row[name] = {"prompt_tokens": n, "total": tot, "fits": tot <= MAX_MODEL_LEN}
            fits &= row[name]["fits"]
        ctx[paper] = row
        print(a.model, paper, row, flush=True)
    out["checks"]["P1_context"] = {"papers": ctx, "pass": fits, "max_model_len": MAX_MODEL_LEN, "margin": MARGIN}

    # live requests: targeted long, targeted short, blind long (x3 repeats each for P6)
    long_case = max([c for c in plan.cases() if c["paper"] == LONG_PAPER], key=lambda c: len(c["question"]))
    short_case = [c for c in plan.cases() if c["paper"] == SHORT_PAPER][0]
    blind_item = next(it for it in plan.blind_items() if it["paper"] == LONG_PAPER and it["kind"] == "defective")
    reqs = []
    for name, c, st in (("targeted_long_E0", long_case, "E0"), ("targeted_short_E1", short_case, "E1")):
        text, valid = plan.paper(c, st)
        pl, _ = MB.apply_extra(cfg, P.build_targeted(cfg, text, c["question"], P.exposure_text("neutral"), P.seed_for(c["case_id"], st)))
        reqs.append((name, pl, C.validate_targeted, "targeted", valid))
    plb, _ = MB.apply_extra(cfg, PBR.build_blind_br(cfg, blind_item["text"], blind_item["seed"]))
    reqs.append(("blind_long", plb, C.validate_blind, "blind", blind_item["valid"]))

    statuses, rows, line_ok, line_total, malformed, empty_content, reasoning_seen = Counter(), [], 0, 0, 0, 0, 0
    for name, pl, val, kind, valid in reqs:
        reps = []
        for i in range(3):
            r = C.call_with_retries(cfg["endpoint"], pl, val, max_retries=0, timeout=P.TIMEOUT_S[kind])
            statuses[r["status"]] += 1
            content = r.get("content") or ""
            diag = r.get("diagnostics") or {}
            if r["status"] == "OK":
                if not content.strip():
                    empty_content += 1
                if kind == "targeted":
                    p = r["parsed"]
                    line_total += 1
                    line_ok += bool(p["evidence_line_ids"])
                    malformed += len(p["evidence_line_ids_malformed"])
            reasoning_seen += bool((diag.get("reasoning_length") or 0) or (diag.get("reasoning_content_length") or 0))
            reps.append({"status": r["status"], "sha256": hashlib.sha256(content.encode()).hexdigest(),
                         "verdict": (r.get("parsed") or {}).get("verdict"),
                         "n_findings": len((r.get("parsed") or {}).get("findings") or []) if kind == "blind" else None,
                         "completion_tokens": (diag.get("usage") or {}).get("completion_tokens"),
                         "reasoning_chars": diag.get("reasoning_length") or diag.get("reasoning_content_length") or 0})
            print(a.model, name, i, reps[-1]["status"], reps[-1]["verdict"] or reps[-1]["n_findings"], flush=True)
        rows.append({"probe": name, "kind": kind, "repeats": reps,
                     "byte_identical": len({x["sha256"] for x in reps}) == 1,
                     "verdict_identical": len({x["verdict"] for x in reps}) == 1 if kind == "targeted" else None,
                     "n_findings_identical": len({x["n_findings"] for x in reps}) == 1 if kind == "blind" else None})
    n_req = sum(statuses.values())
    n_ok = statuses.get("OK", 0)
    out["checks"]["P3_targeted_schema"] = {"pass": all(all(x["status"] == "OK" for x in r["repeats"]) for r in rows if r["kind"] == "targeted")}
    out["checks"]["P4_blind_schema"] = {"pass": all(all(x["status"] == "OK" for x in r["repeats"]) for r in rows if r["kind"] == "blind")}
    out["checks"]["P5_final_answer"] = {"empty_content": empty_content, "requests_with_reasoning_channel": reasoning_seen,
                                        "pass": empty_content == 0 and n_ok > 0}
    out["checks"]["P6_repeatability"] = {
        "probes": rows, "all_byte_identical": all(r["byte_identical"] for r in rows),
        "all_verdict_identical": all(r["verdict_identical"] for r in rows if r["kind"] == "targeted"),
        "note": "reported, never a gate; non-deterministic models run the same frozen single-run protocol and are labelled"}
    out["checks"]["P7_validity"] = {"requests": n_req, "valid": n_ok, "statuses": dict(statuses),
                                    "pass": n_req > 0 and n_ok / n_req >= 0.90}
    out["checks"]["P8_line_ids"] = {"valid_targeted": line_total, "with_line_ids": line_ok, "malformed": malformed,
                                    "pass": line_total > 0 and line_ok == line_total and malformed == 0}
    gate = [k for k in ("P1_context", "P2_server", "P3_targeted_schema", "P4_blind_schema", "P5_final_answer", "P7_validity", "P8_line_ids")]
    out["gate_pass"] = all(out["checks"][k]["pass"] for k in gate)
    out["determinism_label"] = "deterministic" if out["checks"]["P6_repeatability"]["all_byte_identical"] else "non_deterministic_single_run"
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / f"preflight_{a.model}.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"model": a.model, "gate_pass": out["gate_pass"], "determinism": out["determinism_label"],
                      "checks": {k: v["pass"] for k, v in out["checks"].items() if "pass" in v}}, indent=1))
    sys.exit(0 if out["gate_pass"] else 2)


if __name__ == "__main__":
    main()

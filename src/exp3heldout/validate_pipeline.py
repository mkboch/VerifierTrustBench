#!/usr/bin/env python3
"""Technical validation of the held-out runner/protocol/scorer using OLD papers only.

    python exp3heldout/validate_pipeline.py --models qwen38_27 qwen36_27 ...

Builds a throwaway dev ledger from the Experiment 2B papers with the same miner/builder used for the held-out corpus,
then issues a handful of requests per model to prove: targeted schema valid, blind (bounded) schema valid, line IDs
present, mechanical gold comparison works, and the strict blind scorer runs. No held-out manuscript is used and no
scientific question about a held-out paper is asked.
Writes exp3heldout/validation_dev.json
"""
import argparse, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp3heldout"))
import mine_cases as M, checkers as CK, build_dataset as B
sys.path.insert(0, str(ROOT / "exp2b")); sys.path.insert(0, str(ROOT / "exp2br")); sys.path.insert(0, str(ROOT / "exp2bbroad"))
import normalize as N, protocol as P, protocol_br as PBR, client as C, scoring as S
import models_broad as MB

DEV_PAPERS = ["2609.04261", "2609.01018"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    a = ap.parse_args()
    out = {"dev_papers": DEV_PAPERS, "models": {}, "when": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    cases = []
    for pid in DEV_PAPERS:
        body = (ROOT / f"exp2b/papers/{pid}/E1.tex").read_text()
        mined = M.mine_paper(pid, body)[:2]
        for i, cand in enumerate(mined, start=1):
            variants = M.validate(cand, body)
            numbered, valid = N.number(variants["E0"])
            cases.append({"paper": pid, "case_id": f"dev_{pid[-4:]}_{i}", "family": cand["family"],
                          "question": B.question_for(cand), "target_lines": cand["target_lines"],
                          "blind_tokens": B.blind_tokens_for(cand), "spec": cand["spec"],
                          "e0_numbered": numbered, "e0_valid": valid,
                          "e1_numbered": N.number(body)[0], "e1_valid": N.number(body)[1]})
    ledger = {"family_terms": json.loads((ROOT / "exp2b/ledger.json").read_text())["family_terms"],
              "generic_flag_terms": json.loads((ROOT / "exp2b/ledger.json").read_text())["generic_flag_terms"]}
    for m in a.models:
        cfg = MB.MODELS[m]
        res = {"targeted": [], "blind": []}
        for c in cases[:2]:
            for state, text, valid in (("E0", c["e0_numbered"], c["e0_valid"]), ("E1", c["e1_numbered"], c["e1_valid"])):
                payload, _ = MB.apply_extra(cfg, P.build_targeted(cfg, text, c["question"], P.exposure_text("neutral"),
                                                                  P.seed_for(c["case_id"], state)))
                r = C.call_with_retries(cfg["endpoint"], payload, C.validate_targeted, max_retries=1,
                                        timeout=P.TIMEOUT_S["targeted"])
                p = r.get("parsed") or {}
                gold_ok = None
                if r["status"] == "OK":
                    expected = "ISSUE_PRESENT" if state == "E0" else "NO_ISSUE"
                    gold_ok = (p["verdict"] == expected)
                res["targeted"].append({"case": c["case_id"], "state": state, "status": r["status"],
                                        "verdict": p.get("verdict"), "matches_gold": gold_ok,
                                        "line_ids": len(p.get("evidence_line_ids") or []),
                                        "malformed_ids": len(p.get("evidence_line_ids_malformed") or [])})
        c = cases[0]
        payload, _ = MB.apply_extra(cfg, PBR.build_blind_br(cfg, c["e0_numbered"], P.seed_for(c["case_id"], "blind")))
        r = C.call_with_retries(cfg["endpoint"], payload, C.validate_blind, max_retries=1, timeout=P.TIMEOUT_S["blind"])
        lab = None
        if r["status"] == "OK":
            case_for_scorer = {"family": c["family"], "target_lines": c["target_lines"], "blind_tokens": c["blind_tokens"]}
            lab, _ = S.label_defective(r["parsed"]["findings"], case_for_scorer, ledger, c["e0_valid"])
        res["blind"].append({"case": c["case_id"], "status": r["status"],
                             "n_findings": len((r.get("parsed") or {}).get("findings") or []), "scorer_label": lab})
        # Technical gate: the protocol plumbing must work. Verdict correctness is the experiment's subject, not a
        # gate, and an isolated TRUNCATED response is a known low-rate event (1 in 720 targeted trials in 2B), so the
        # rule is: >= 70% of targeted requests valid, no valid output emits a MALFORMED line ID, at least one valid
        # output demonstrates that the model can emit well-formed line IDs, and the bounded blind request is valid
        # and scoreable.
        #
        # An EMPTY evidence_line_ids list is deliberately NOT a failure (amendment A2, VALIDATION_GATE.md): the
        # targeted schema permits it, the frozen provenance classifier has a dedicated EMPTY/UNSUPPORTED class for
        # it, and "the model chose to cite nothing" is model behaviour that the provenance analysis measures, not
        # broken plumbing. The rule below is uniform across models and is implied by the previous rule, so it cannot
        # turn any earlier PASS into a FAIL.
        tg = res["targeted"]
        n_ok = sum(x["status"] == "OK" for x in tg)
        ok_tg = [x for x in tg if x["status"] == "OK"]
        res["empty_line_id_outputs"] = sum(x["line_ids"] == 0 for x in ok_tg)
        res["pass"] = (n_ok >= 0.7 * len(tg)
                       and all(x["malformed_ids"] == 0 for x in ok_tg)
                       and any(x["line_ids"] > 0 for x in ok_tg)
                       and all(x["status"] == "OK" and x["scorer_label"] is not None for x in res["blind"]))
        out["models"][m] = res
        print(m, "pass" if res["pass"] else "FAIL", json.dumps(res)[:400], flush=True)
    out["all_pass"] = all(v["pass"] for v in out["models"].values())
    (ROOT / "exp3heldout/validation_dev.json").write_text(json.dumps(out, indent=1) + "\n")
    print("ALL PASS", out["all_pass"])
    sys.exit(0 if out["all_pass"] else 2)


if __name__ == "__main__":
    main()

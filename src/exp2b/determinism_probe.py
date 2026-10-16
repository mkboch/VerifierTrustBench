#!/usr/bin/env python3
"""2B determinism probe: 3 requests (targeted neutral, targeted false_rationale, blind) x 3 repeats per model,
on the first validation case. Writes <run_dir>/determinism_<models>.json. Target: 100% byte-identical."""
import argparse, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2b"))
import client as C, design as D, models as M, protocol as P

ap = argparse.ArgumentParser(); ap.add_argument("--run-dir", required=True); ap.add_argument("--models", nargs="+", required=True)
a = ap.parse_args()
plan = D.Plan("validation")
c = plan.matrix_cases()[0]
report, all_same = {}, True
for m in a.models:
    cfg = M.MODELS[m]
    t0, v0 = plan.paper(c, "E0")
    t1, v1 = plan.paper(c, "E1")
    reqs = [("targeted E0 neutral", P.build_targeted(cfg, t0, c["question"], P.exposure_text("neutral"), P.seed_for(c["case_id"], "E0"))[0], C.validate_targeted, "targeted"),
            ("targeted E1 false_rationale", P.build_targeted(cfg, t1, c["question"], P.exposure_text("false_rationale", prior_verdict="ISSUE_PRESENT", prior_rationale=c["rationales"]["E1"]["false"]), P.seed_for(c["case_id"], "E1"))[0], C.validate_targeted, "targeted"),
            ("blind E0", P.build_blind(cfg, t0, P.seed_for(c["case_id"], "blind"))[0], C.validate_blind, "blind")]
    rows = []
    for name, payload, val, kind in reqs:
        outs = []
        for _ in range(3):
            r = C.call_with_retries(cfg["endpoint"], payload, val, max_retries=0, timeout=P.TIMEOUT_S[kind])
            outs.append((r["status"], hashlib.sha256((r.get("content") or "").encode()).hexdigest(),
                         ((r.get("diagnostics") or {}).get("usage") or {}).get("prompt_tokens")))
        same = len({o[1] for o in outs}) == 1
        all_same &= same
        rows.append({"probe": name, "statuses": [o[0] for o in outs], "byte_identical": same, "prompt_tokens": outs[0][2]})
        print(m, rows[-1], flush=True)
    report[m] = rows
out = Path(a.run_dir) / f"determinism_{'_'.join(a.models)}.json"
out.write_text(json.dumps({"all_byte_identical": all_same, "models": report}, indent=1))

#!/usr/bin/env python3
"""2B-R determinism probe: two bounded-schema blind requests (a 2B truncation input and a clean paper) x 3 repeats per model."""
import argparse, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2br"))
import protocol_br as PB, run_exp2br as RB
import client as C, models as M, protocol as P
ap = argparse.ArgumentParser(); ap.add_argument("--run-dir", required=True); ap.add_argument("--models", nargs="+", required=True)
a = ap.parse_args()
by = {it["id"]: it for it in RB.items("full")}
rep, allsame = {}, True
for m in a.models:
    rows = []
    for iid in ("p00473_num_params::E0", "2609.01675::clean"):
        it = by[iid]
        payload, _ = PB.build_blind_br(M.MODELS[m], it["text"], it["seed"])
        outs = []
        for _ in range(3):
            r = C.call_with_retries(M.MODELS[m]["endpoint"], payload, C.validate_blind, max_retries=0, timeout=P.TIMEOUT_S["blind"])
            outs.append((r["status"], hashlib.sha256((r.get("content") or "").encode()).hexdigest()))
        same = len({o[1] for o in outs}) == 1
        allsame &= same and all(o[0] == "OK" for o in outs)
        rows.append({"probe": iid, "statuses": [o[0] for o in outs], "byte_identical": same})
        print(m, rows[-1], flush=True)
    rep[m] = rows
(Path(a.run_dir) / f"determinism_{'_'.join(a.models)}.json").write_text(json.dumps({"all_ok_and_identical": allsame, "models": rep}, indent=1))

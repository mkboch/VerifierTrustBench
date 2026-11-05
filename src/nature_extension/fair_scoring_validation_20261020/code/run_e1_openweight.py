#!/usr/bin/env python3
"""E1 fair-scoring run, open-weight systems.

    python run_e1_openweight.py --phase large|small|granite

Issues only the two targeted finding-list arms on the unmodified E1 manuscript. The blind
and binary E1 cells are reused from frozen records and are never re-issued here.

Append-only JSONL, resumable. Refuses to start if the frozen E1 manifest has changed.
Touches no frozen run.
"""
from __future__ import annotations
import argparse, hashlib, json, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
RR = ROOT / "nature_extension/reviewer_response_20261016"
sys.path.insert(0, str(RR / "code"))
for p in ("exp3heldout", "exp2b", "exp2br", "exp2bbroad"):
    sys.path.insert(0, str(ROOT / p))

import design_heldout as D      # noqa: E402
import protocol as P            # noqa: E402
import models_broad as MB       # noqa: E402
import client as C              # noqa: E402
import scoring as S             # noqa: E402
import ladder_protocol as LP    # noqa: E402

MANP = OUT / "e1/E1_FAIR_SCORING_MANIFEST.json"
EXPECTED_MANIFEST = "fef612972be74de40910302b30e8ef777e36a2e4094c423d5a13392e0f863fac"
PHASES = {"large": ["qwen38_27", "qwen36_27"], "small": ["qwen3_8", "gemma4_12"],
          "granite": ["granite42_30"]}
STATE = "E1"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def healthy(ep):
    try:
        with urllib.request.urlopen(ep + "/v1/models", timeout=15):
            return True
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=list(PHASES))
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    msha = hashlib.sha256(MANP.read_bytes()).hexdigest()
    if msha != EXPECTED_MANIFEST:
        print(f"REFUSING: frozen E1 manifest changed ({msha[:16]} != "
              f"{EXPECTED_MANIFEST[:16]}). The protocol was frozen before the first request "
              f"and must not be edited mid-run.")
        return 2
    man = json.loads(MANP.read_text())
    log(f"E1 manifest {msha[:16]} ({man['label']})")

    plan = D.Plan()
    cases = {c["case_id"]: c for c in plan.cases}
    subset = man["case_ids"]

    store = OUT / "e1/e1_openweight_trials.jsonl"
    done = {}
    if store.exists():
        for line in store.open():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            done[r["key"]] = r
    log(f"resuming: {len(done)} records already present")

    n_new = 0
    for model in PHASES[a.phase]:
        cfg = MB.MODELS[model]
        if not healthy(cfg["endpoint"]):
            log(f"SKIP {model}: endpoint {cfg['endpoint']} not healthy")
            continue
        log(f"=== {model} at {cfg['endpoint']} (E1) ===")
        for cid in subset:
            case = cases[cid]
            text, valid = plan.paper_text(case, STATE)
            for arm in LP.ARMS:
                key = f"e1ladder::{model}::{cid}::{arm}"
                prev = done.get(key)
                if prev and prev["result"]["status"] == "OK":
                    continue
                seed = P.seed_for(cid, STATE)
                payload, prov = MB.apply_extra(cfg, LP.build_arm(arm, cfg, text, case, seed))
                t0 = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                res = C.call_with_retries(cfg["endpoint"], payload, C.validate_blind,
                                          max_retries=P.MAX_RETRIES, timeout=P.TIMEOUT_S["blind"])
                if res["status"] == "OK":
                    res["provenance_check"] = [
                        S.provenance(x["evidence_line_ids"], x["evidence_line_ids_malformed"],
                                     valid, case["target_lines"])
                        for x in res["parsed"]["findings"]]
                rec = {"key": key, "phase_label": man["label"],
                       "e1_manifest_sha256": msha,
                       "ladder_version": LP.LADDER_VERSION,
                       "model": model, "family_of_model": cfg["family"],
                       "reasoning_mode": cfg["reasoning_mode"],
                       "competence_class": MB.COMPETENCE_CLASS[model],
                       "experiment": "e1ladder", "arm": arm, "case_id": cid,
                       "paper": case["paper"], "domain": case["domain"],
                       "case_family": case["family"], "state": STATE,
                       "truth": case["truth"][STATE], "seed": seed,
                       "resume_round": (prev or {}).get("resume_round", 0) + 1,
                       "started": t0, "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                       "provenance": prov, "result": res}
                with store.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                done[key] = rec
                n_new += 1
                nf = len(res.get("parsed", {}).get("findings", [])) if res["status"] == "OK" else "-"
                log(f"{key} -> {res['status']} ({nf} findings)  [{n_new} new]")
                if res["status"] == "HTTP_FAILED" and not healthy(cfg["endpoint"]):
                    log(f"ABORT: {model} endpoint unhealthy")
                    return 2
                if a.limit and n_new >= a.limit:
                    log(f"limit {a.limit} reached")
                    return 0
    log(f"phase {a.phase} complete: {n_new} new requests, {len(done)} total records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

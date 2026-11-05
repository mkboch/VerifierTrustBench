#!/usr/bin/env python3
"""B4 runner: the reviewer-motivated localization ladder.

    python run_ladder.py --phase large|small|granite --out <dir>

Writes append-only JSONL, resumable, one record per request. Never touches any frozen run.
Refuses to start if the design manifest hash does not match the frozen copy.
"""
from __future__ import annotations
import argparse, hashlib, json, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OUT / "code"))
for p in ("exp3heldout", "exp2b", "exp2br", "exp2bbroad"):
    sys.path.insert(0, str(ROOT / p))

import design_heldout as D      # noqa: E402
import protocol as P            # noqa: E402
import models_broad as MB       # noqa: E402
import client as C              # noqa: E402
import scoring as S             # noqa: E402
import ladder_protocol as LP    # noqa: E402

MAN = OUT / "ladder/LADDER_DESIGN_MANIFEST.json"
PHASES = {"large": ["qwen38_27", "qwen36_27"], "small": ["qwen3_8", "gemma4_12"],
          "granite": ["granite42_30"]}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def healthy(ep):
    try:
        with urllib.request.urlopen(ep + "/v1/models", timeout=15):
            return True
    except Exception:
        return False


def load_done(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.open():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[r["key"]] = r
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=list(PHASES))
    ap.add_argument("--limit", type=int, default=0, help="stop after N new requests (smoke test)")
    a = ap.parse_args()

    man = json.loads(MAN.read_text())
    msha = hashlib.sha256(MAN.read_bytes()).hexdigest()
    log(f"design manifest {msha[:16]} ({man['label']})")

    plan = D.Plan()
    cases = {c["case_id"]: c for c in plan.cases}
    subset = man["case_ids"]

    store = OUT / "ladder/ladder_trials.jsonl"
    done = load_done(store)
    log(f"resuming: {len(done)} records already present")

    n_new = 0
    for model in PHASES[a.phase]:
        cfg = MB.MODELS[model]
        if not healthy(cfg["endpoint"]):
            log(f"SKIP {model}: endpoint {cfg['endpoint']} not healthy")
            continue
        log(f"=== {model} at {cfg['endpoint']} ===")
        for cid in subset:
            case = cases[cid]
            text, valid = plan.paper_text(case, "E0")
            for arm in LP.ARMS:
                key = f"ladder::{model}::{cid}::{arm}"
                prev = done.get(key)
                if prev and prev["result"]["status"] == "OK":
                    continue
                seed = P.seed_for(cid, "E0")
                payload, prov = MB.apply_extra(cfg, LP.build_arm(arm, cfg, text, case, seed))
                t0 = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                res = C.call_with_retries(cfg["endpoint"], payload, C.validate_blind,
                                          max_retries=P.MAX_RETRIES, timeout=P.TIMEOUT_S["blind"])
                if res["status"] == "OK":
                    res["provenance_check"] = [
                        S.provenance(x["evidence_line_ids"], x["evidence_line_ids_malformed"],
                                     valid, case["target_lines"])
                        for x in res["parsed"]["findings"]]
                rec = {"key": key, "ladder_version": LP.LADDER_VERSION, "design_manifest_sha256": msha,
                       "model": model, "family_of_model": cfg["family"],
                       "reasoning_mode": cfg["reasoning_mode"],
                       "competence_class": MB.COMPETENCE_CLASS[model],
                       "experiment": "ladder", "arm": arm, "case_id": cid, "paper": case["paper"],
                       "domain": case["domain"], "case_family": case["family"], "state": "E0",
                       "truth": case["truth"]["E0"], "seed": seed,
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

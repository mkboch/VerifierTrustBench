#!/usr/bin/env python3
"""Phase 1 runner: statistical-enrichment cases under the frozen protocol.

    python run_phase1.py --run-dir runs/natureext_phase1_<ts> --model M

Conditions per case: targeted E0, targeted E1, targeted E2 (neutral exposure) and blind E0.
Prompts, schemas, seeds, decoding and scorers are the FROZEN Experiment 2B/3 ones, unchanged.
"""
from __future__ import annotations
import argparse, hashlib, json, sys, time, traceback, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "exp3heldout"))
import design_heldout as _D          # noqa: F401  side effect: puts exp2b/exp2br/exp2bbroad on sys.path
import models_broad as MB, client as C, protocol as P, protocol_br as PBR, scoring as S, normalize as N  # noqa

PROTOCOL_VERSION = "natureext-phase1-stat-v1.0"
LED = json.loads((HERE / "ledger.json").read_text())


def log(m): print(time.strftime("%H:%M:%S"), m, flush=True)


def numbered_for(case, state):
    return N.number((ROOT / case["paths"][state]).read_text())


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run-dir", required=True); ap.add_argument("--model", required=True)
    a = ap.parse_args()
    rd = Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir
    rd.mkdir(parents=True, exist_ok=True)
    man = json.loads((HERE / "design_manifest.json").read_text())
    bad = [f for f, h in man["file_sha256"].items()
           if hashlib.sha256((ROOT / f).read_bytes()).hexdigest() != h]
    if bad: raise SystemExit("REFUSING TO RUN: frozen files changed:\n  " + "\n  ".join(bad))
    msha = hashlib.sha256((HERE / "design_manifest.json").read_bytes()).hexdigest()
    cfg = MB.MODELS[a.model]
    with urllib.request.urlopen(cfg["endpoint"] + "/v1/models", timeout=30) as r:
        d = json.loads(r.read())["data"][0]
    if d["id"] != cfg["served_name"]: raise SystemExit(f"endpoint serves {d['id']}")

    ev, bl = rd / "evidence_trials.jsonl", rd / "blind_trials.jsonl"
    done = set()
    for p in (ev, bl):
        if p.exists():
            for l in p.read_text().splitlines():
                if l.strip():
                    r = json.loads(l)
                    if r["result"]["status"] == "OK": done.add(r["key"])
    counts = {"run": 0, "skip": 0, "ok": 0, "fail": 0}
    log(f"START phase1 {a.model} cases={len(LED['cases'])} manifest={msha[:12]}")
    try:
        for case in LED["cases"]:
            for st in ("E0", "E1", "E2"):
                key = f"evidence::{a.model}::{case['case_id']}::{st}"
                if key in done: counts["skip"] += 1; continue
                text, valid = numbered_for(case, st)
                seed = P.seed_for(case["case_id"], st)
                payload, prov = MB.apply_extra(cfg, P.build_targeted(cfg, text, case["question"],
                                                                     P.exposure_text("neutral"), seed))
                res = C.call_with_retries(cfg["endpoint"], payload, C.validate_targeted,
                                          max_retries=P.MAX_RETRIES, timeout=P.TIMEOUT_S["targeted"])
                if res["status"] == "OK":
                    p_ = res["parsed"]
                    res["provenance_check"] = S.provenance(p_["evidence_line_ids"],
                                                           p_["evidence_line_ids_malformed"], valid,
                                                           case["target_lines"])
                rec = {"key": key, "protocol_version": PROTOCOL_VERSION, "model": a.model,
                       "design_manifest_sha256": msha, "experiment": "evidence", "paper": case["paper"],
                       "domain": case["domain"], "case_id": case["case_id"], "case_family": case["family"],
                       "checker": case["checker"], "state": st, "truth": case["truth"][st], "arm": "neutral",
                       "seed": seed, "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                       "provenance": prov, "result": res}
                with ev.open("a") as fh: fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                counts["run"] += 1; counts["ok" if res["status"] == "OK" else "fail"] += 1
                log(f"[{a.model}] {case['case_id']}::{st} -> {res['status']} "
                    f"{(res.get('parsed') or {}).get('verdict','')}")
            key = f"blind::{a.model}::{case['case_id']}::E0"
            if key in done: counts["skip"] += 1; continue
            text, valid = numbered_for(case, "E0")
            seed = P.seed_for(case["case_id"], "blind")
            payload, prov = MB.apply_extra(cfg, PBR.build_blind_br(cfg, text, seed))
            res = C.call_with_retries(cfg["endpoint"], payload, C.validate_blind, max_retries=P.MAX_RETRIES,
                                      timeout=P.TIMEOUT_S["blind"])
            label = None
            if res["status"] == "OK":
                label, _ = S.label_defective(res["parsed"]["findings"], case, LED, valid)
            rec = {"key": key, "protocol_version": PROTOCOL_VERSION, "model": a.model,
                   "design_manifest_sha256": msha, "experiment": "blind", "paper": case["paper"],
                   "domain": case["domain"], "case_id": case["case_id"], "case_family": case["family"],
                   "checker": case["checker"], "state": "E0", "kind": "defective", "seed": seed,
                   "scorer_label": label, "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "provenance": prov, "result": res}
            with bl.open("a") as fh: fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            counts["run"] += 1; counts["ok" if res["status"] == "OK" else "fail"] += 1
            log(f"[{a.model}] {case['case_id']}::blind -> {res['status']} {label or ''}")
    except Exception as e:  # noqa: BLE001
        log(f"EXCEPTION {e!r}\n{traceback.format_exc()}")
    (rd / f"RUN_META_{a.model}.json").write_text(json.dumps(
        {"model": a.model, "counts": counts, "design_manifest_sha256": msha,
         "protocol_version": PROTOCOL_VERSION, "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, indent=2) + "\n")
    log(f"DONE {a.model} counts={counts}")


if __name__ == "__main__":
    main()

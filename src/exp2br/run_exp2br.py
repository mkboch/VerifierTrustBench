#!/usr/bin/env python3
"""Experiment 2B-R blind-only runner.

    python exp2br/run_exp2br.py --run-dir runs/exp2br_<ts> --scope full --phase large
    python exp2br/run_exp2br.py --run-dir runs/exp2br_<ts> --scope full --phase small

Runs exactly the frozen Experiment 2B blind plan (exp2b/design.Plan('full').blind_items(): 60 defective E0 manuscripts
and 5 clean papers per model) with the bounded schema of protocol_br. Same manuscripts, seeds, models, servers, decoding
and B1 prompt. One request at a time per model; resumable (OK keys skipped, failed keys retried with the identical
request, every attempt appended). Refuses to run if a frozen file differs from exp2br/design_manifest.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2br"))
import protocol_br as PB  # noqa: E402  (inserts exp2b on sys.path)
import client as C  # noqa: E402
import design as D  # noqa: E402
import models as M  # noqa: E402
import protocol as P  # noqa: E402
import scoring as S  # noqa: E402

LOCK = threading.Lock()
PHASE_MODELS = D.PHASE_MODELS
# Validation scope: the five 2B truncation inputs, the two clean papers they come from, and one E0 manuscript from each
# of the other three papers (fixed before any 2B-R inference).
VALIDATION_IDS = ["p01675_xref_comparison_table::E0", "p01675_xref_p_alpha_table::E0", "p00473_num_params::E0",
                  "p00473_xref_coverage_table::E0", "p00473_method_tolerance::E0", "2609.00473::clean", "2609.01675::clean",
                  "p01018_xref_val_table::E0", "p03933_num_mc_reps::E0", "p04261_xref_probe::E0"]


def log(msg):
    with LOCK:
        print(time.strftime("%H:%M:%S"), msg, flush=True)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_frozen() -> str:
    mp = ROOT / "exp2br/design_manifest.json"
    if not mp.exists():
        raise SystemExit("exp2br/design_manifest.json missing: freeze first")
    man = json.loads(mp.read_text())
    bad = [r for r, h in {**man["frozen_file_sha256"], **man["reused_2b_file_sha256"]}.items() if not (ROOT / r).exists() or sha(ROOT / r) != h]
    if bad:
        raise SystemExit("REFUSING TO RUN: frozen files changed:\n  " + "\n  ".join(bad))
    return sha(mp)


def items(scope):
    all_items = D.Plan("full").blind_items()
    if scope == "validation":
        by = {it["id"]: it for it in all_items}
        return [by[i] for i in VALIDATION_IDS]
    return all_items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--scope", choices=["validation", "full"], required=True)
    ap.add_argument("--phase", choices=["large", "small"], required=True)
    a = ap.parse_args()
    rd = Path(a.run_dir)
    rd = rd if rd.is_absolute() else ROOT / rd
    rd.mkdir(parents=True, exist_ok=True)
    if (rd / "FINAL").exists():
        raise SystemExit("run is FINAL")
    msha = verify_frozen()
    meta_p = rd / "RUN_META.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {"protocol_version": PB.PROTOCOL_VERSION, "scope": a.scope,
                                                                    "design_manifest_sha256": msha, "phases": []}
    if meta["scope"] != a.scope or meta["design_manifest_sha256"] != msha:
        raise SystemExit("run directory belongs to a different scope or design")
    idents = []
    for m in PHASE_MODELS[a.phase]:
        with urllib.request.urlopen(M.MODELS[m]["endpoint"] + "/v1/models", timeout=30) as r:
            d = json.loads(r.read())["data"][0]
        if d["id"] != M.MODELS[m]["served_name"] or d["root"] != M.MODELS[m]["root"]:
            raise SystemExit(f"endpoint for {m} serves {d['id']}/{d['root']}")
        idents.append({"model": m, "root": d["root"], "max_model_len": d.get("max_model_len")})
    entry = {"phase": a.phase, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "endpoints": idents}
    meta["phases"].append(entry)
    meta_p.write_text(json.dumps(meta, indent=2) + "\n")
    path = rd / "blind_trials.jsonl"
    latest = {}
    if path.exists():
        for l in path.read_text().splitlines():
            r = json.loads(l)
            latest[r["key"]] = r
    plan = items(a.scope)
    counts = {"run": 0, "skip": 0, "ok": 0, "fail": 0}
    errors = []

    def work(model):
        cfg = M.MODELS[model]
        try:
            for it in plan:
                key = f"blind::{model}::{it['id']}"
                prev = latest.get(key)
                if prev and prev["result"]["status"] == "OK":
                    counts["skip"] += 1
                    continue
                payload, prov = PB.build_blind_br(cfg, it["text"], it["seed"])
                res = C.call_with_retries(cfg["endpoint"], payload, C.validate_blind, max_retries=P.MAX_RETRIES,
                                          timeout=P.TIMEOUT_S["blind"])
                if res["status"] == "OK":
                    res["provenance_check"] = [S.provenance(f["evidence_line_ids"], f["evidence_line_ids_malformed"], it["valid"], it.get("target_lines"))
                                               for f in res["parsed"]["findings"]]
                rec = {"key": key, "protocol_version": PB.PROTOCOL_VERSION, "scope": a.scope, "phase": a.phase,
                       "resume_round": (prev or {}).get("resume_round", 0) + 1, "design_manifest_sha256": msha,
                       "experiment": "blind", "model": model, **{k: it[k] for k in ("paper", "case_id", "family", "state", "kind", "seed")},
                       "provenance": prov, "result": res, "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
                with LOCK:
                    with path.open("a") as fh:
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    counts["run"] += 1
                    counts["ok" if res["status"] == "OK" else "fail"] += 1
                par = res.get("parsed") or {}
                usage = ((res.get("diagnostics") or {}).get("usage") or {}).get("completion_tokens")
                log(f"[{model}] {key} -> {res['status']} {len(par.get('findings', [])) if par else ''} findings ({usage} tok, attempts={res['n_attempts']})")
        except Exception as e:
            errors.append(f"{model}: {e!r}")
            log(f"[{model}] EXCEPTION {e!r}\n{traceback.format_exc()}")

    ths = [threading.Thread(target=work, args=(m,)) for m in PHASE_MODELS[a.phase]]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    entry.update({"finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "counts": counts, "errors": errors})
    meta_p.write_text(json.dumps(meta, indent=2) + "\n")
    log(f"PHASE {a.phase} DONE counts={counts} errors={errors}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

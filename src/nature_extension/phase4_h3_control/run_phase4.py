#!/usr/bin/env python3
"""Phase 4 runner: H3 length-matched control arms.

    python run_phase4.py --run-dir runs/natureext_phase4_<ts> --model M

Arms (NEW; the five original arms are reused from Experiment 3 and are NOT re-run):
  cv_irrelevant  correct verdict + length-matched IRRELEVANT rationale
  fv_irrelevant  false   verdict + length-matched IRRELEVANT rationale
  filler         length-matched neutral note, NO verdict, NO relation content

Wrapper text for the two rationale arms is the frozen exposure_text template, byte-identical to Experiment 3;
only the rationale CONTENT differs. That is the point of the control.
"""
from __future__ import annotations
import argparse, hashlib, json, sys, time, traceback, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "exp3heldout"))
import design_heldout as D          # noqa: E402  (puts exp2b/exp2br/exp2bbroad on sys.path)
import models_broad as MB           # noqa: E402
import client as C                  # noqa: E402
import protocol as P                # noqa: E402
import scoring as S                 # noqa: E402

PROTOCOL_VERSION = "natureext-phase4-v1.0"
NEW_ARMS = ("cv_irrelevant", "fv_irrelevant", "filler")
MAN = json.loads((HERE / "CONTROL_MANIFEST.json").read_text())

FILLER_TEMPLATE = ("A previous verifier ({src}) examined the manuscript and recorded this note: {note} "
                   "It returned no verdict and no allegation. Verify independently.")


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def exposure_for(arm, case, state, truth):
    """Build the INFORMATION CONDITION text for a new control arm."""
    slot = MAN["cases"][case["case_id"]]["states"][state]
    false_v = "NO_ISSUE" if truth == "ISSUE_PRESENT" else "ISSUE_PRESENT"
    if arm == "cv_irrelevant":
        return P.exposure_text("correct_rationale", prior_verdict=truth,
                               prior_rationale=slot["irrelevant_rationale"]), truth, slot["irrelevant_rationale"]
    if arm == "fv_irrelevant":
        return P.exposure_text("false_rationale", prior_verdict=false_v,
                               prior_rationale=slot["irrelevant_rationale"]), false_v, slot["irrelevant_rationale"]
    if arm == "filler":
        return FILLER_TEMPLATE.format(src=P.SOURCE_NAME, note=slot["filler"]), None, slot["filler"]
    raise ValueError(arm)


def read_latest(p: Path):
    out = {}
    if p.exists():
        for l in p.read_text().splitlines():
            if l.strip():
                r = json.loads(l); out[r["key"]] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--model", required=True)
    a = ap.parse_args()
    rd = Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir
    rd.mkdir(parents=True, exist_ok=True)
    if (rd / "FINAL").exists():
        raise SystemExit("run is FINAL")

    # frozen-file gate
    man = json.loads((HERE / "design_manifest.json").read_text())
    bad = [f for f, h in man["file_sha256"].items()
           if hashlib.sha256((ROOT / f).read_bytes()).hexdigest() != h]
    if bad:
        raise SystemExit("REFUSING TO RUN: frozen files changed:\n  " + "\n  ".join(bad))
    msha = hashlib.sha256((HERE / "design_manifest.json").read_bytes()).hexdigest()

    cfg = MB.MODELS[a.model]
    with urllib.request.urlopen(cfg["endpoint"] + "/v1/models", timeout=30) as r:
        d = json.loads(r.read())["data"][0]
    if d["id"] != cfg["served_name"] or d["root"] != cfg["root"]:
        raise SystemExit(f"endpoint serves {d['id']}/{d['root']}, expected {cfg['served_name']}/{cfg['root']}")

    plan = D.Plan()
    subset = plan.matrix_subset()
    store = rd / "h3control_trials.jsonl"
    latest = read_latest(store)
    counts = {"run": 0, "skip": 0, "ok": 0, "fail": 0}
    meta_p = rd / f"RUN_META_{a.model}.json"
    meta = {"experiment": "natureext-phase4-h3-control", "protocol_version": PROTOCOL_VERSION,
            "design_manifest_sha256": msha, "model": a.model,
            "control_manifest_sha256": hashlib.sha256((HERE / "CONTROL_MANIFEST.json").read_bytes()).hexdigest(),
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "arms": list(NEW_ARMS)}
    meta_p.write_text(json.dumps(meta, indent=2) + "\n")
    log(f"START phase4 {a.model} manifest={msha[:12]} arms={NEW_ARMS}")

    errors = []
    try:
        for c in subset:
            for st in ("E0", "E1"):
                truth = c["truth"][st]
                for arm in NEW_ARMS:
                    key = f"h3control::{a.model}::{c['case_id']}::{st}::{arm}"
                    prev = latest.get(key)
                    if prev and prev["result"]["status"] == "OK":
                        counts["skip"] += 1; continue
                    exposure, pv, injected = exposure_for(arm, c, st, truth)
                    text, valid = plan.paper_text(c, st)
                    seed = P.seed_for(c["case_id"], st)
                    payload, prov = MB.apply_extra(cfg, P.build_targeted(cfg, text, c["question"], exposure, seed))
                    t0 = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                    res = C.call_with_retries(cfg["endpoint"], payload, C.validate_targeted,
                                              max_retries=P.MAX_RETRIES, timeout=P.TIMEOUT_S["targeted"])
                    if res["status"] == "OK":
                        p = res["parsed"]
                        res["provenance_check"] = S.provenance(p["evidence_line_ids"],
                                                               p["evidence_line_ids_malformed"], valid,
                                                               c["target_lines"])
                    rec = {"key": key, "protocol_version": PROTOCOL_VERSION, "model": a.model,
                           "family_of_model": cfg["family"], "reasoning_mode": cfg["reasoning_mode"],
                           "design_manifest_sha256": msha, "experiment": "h3control",
                           "paper": c["paper"], "domain": c["domain"], "case_id": c["case_id"],
                           "case_family": c["family"], "state": st, "truth": truth, "arm": arm,
                           "prior_verdict": pv, "injected_text": injected, "seed": seed,
                           "started": t0, "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                           "provenance": prov, "result": res}
                    with store.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    latest[key] = rec
                    counts["run"] += 1
                    counts["ok" if res["status"] == "OK" else "fail"] += 1
                    log(f"[{a.model}] {c['case_id']}::{st}::{arm} -> {res['status']} "
                        f"{(res.get('parsed') or {}).get('verdict','')}")
    except Exception as e:  # noqa: BLE001
        errors.append(repr(e)); log(f"EXCEPTION {e!r}\n{traceback.format_exc()}")
    meta.update({"finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "counts": counts, "errors": errors})
    meta_p.write_text(json.dumps(meta, indent=2) + "\n")
    log(f"DONE {a.model} counts={counts} errors={errors}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Experiment 2B-broad runner: the exact frozen 2B / 2B-R protocol for one technically viable model.

    python exp2bbroad/run_broad.py --run-dir runs/exp2bbroad_<ts> --model <name> [--phases evidence blind matrix]

Phases (all use the frozen benchmark, prompts, schemas, seeds and decoding; nothing is model-specific except the technical
serving fields frozen in models_broad.py):
  evidence : 60 cases x {E0,E1,E2} targeted-neutral  = 180
  blind    : 60 defective E0 + 5 clean manuscripts with B1_minimal + the 2B-R bounded schema = 65
  matrix   : 20 matrix cases x {E0,E1} x 6 exposure arms = 240 (the neutral arm is the evidence request byte-for-byte)

No early stop for scientific weakness: a model is stopped only by a genuine technical blocker (endpoint unhealthy).
Resumable: keys whose latest record is OK are skipped; failures are retried with the identical request (MAX_RETRIES).
Refuses to run if a frozen file hash differs from exp2bbroad/design_manifest.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2bbroad"))
import models_broad as MB  # noqa: E402  (puts exp2b on sys.path)
sys.path.insert(0, str(ROOT / "exp2br"))
import client as C  # noqa: E402
import design as D  # noqa: E402
import protocol as P  # noqa: E402
import protocol_br as PBR  # noqa: E402
import scoring as S  # noqa: E402

PROTOCOL_VERSION = "2B-broad-v1.0"
PHASES = ("evidence", "blind", "matrix")


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_latest(path: Path) -> dict:
    out = {}
    if path.exists():
        for l in path.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                out[r["key"]] = r
    return out


def verify_frozen() -> str:
    mp = ROOT / "exp2bbroad/design_manifest.json"
    if not mp.exists():
        raise SystemExit("exp2bbroad/design_manifest.json missing: freeze the design first")
    man = json.loads(mp.read_text())
    bad = [r for r, h in man["file_sha256"].items() if not (ROOT / r).exists() or sha(ROOT / r) != h]
    if bad:
        raise SystemExit("REFUSING TO RUN: frozen files changed:\n  " + "\n  ".join(bad))
    return sha(mp)


class Blocker(RuntimeError):
    pass


class Runner:
    def __init__(self, rd: Path, model: str, msha: str):
        self.rd, self.model, self.msha = rd, model, msha
        self.cfg = MB.MODELS[model]
        self.plan = D.Plan("full")
        self.files = {k: rd / f"{k}_trials.jsonl" for k in PHASES}
        self.latest = {k: read_latest(p) for k, p in self.files.items()}
        self.counts = {"run": 0, "skip": 0, "ok": 0, "fail": 0}

    def healthy(self):
        try:
            with urllib.request.urlopen(self.cfg["endpoint"] + "/v1/models", timeout=15):
                return True
        except Exception:
            return False

    def run_one(self, phase, key, meta, payload, prov, validator, *, valid=None, targets=None):
        prev = self.latest[phase].get(key)
        if prev and prev["result"]["status"] == "OK":
            self.counts["skip"] += 1
            return prev
        t0 = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        timeout = P.TIMEOUT_S["blind" if phase == "blind" else "targeted"]
        result = C.call_with_retries(self.cfg["endpoint"], payload, validator, max_retries=P.MAX_RETRIES, timeout=timeout)
        if result["status"] == "OK" and valid is not None:
            p = result["parsed"]
            if "findings" in p:
                result["provenance_check"] = [S.provenance(x["evidence_line_ids"], x["evidence_line_ids_malformed"], valid, targets)
                                              for x in p["findings"]]
            else:
                result["provenance_check"] = S.provenance(p["evidence_line_ids"], p["evidence_line_ids_malformed"], valid, targets)
        rec = {"key": key, "protocol_version": PROTOCOL_VERSION, "phase": phase, "model": self.model,
               "family": self.cfg["family"], "reasoning_mode": self.cfg["reasoning_mode"],
               "competence_class": MB.COMPETENCE_CLASS[self.model],
               "resume_round": (prev or {}).get("resume_round", 0) + 1, "design_manifest_sha256": self.msha,
               "started": t0, "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **meta, "provenance": prov, "result": result}
        with self.files[phase].open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.latest[phase][key] = rec
        self.counts["run"] += 1
        self.counts["ok" if result["status"] == "OK" else "fail"] += 1
        par = result.get("parsed") or {}
        tag = par.get("verdict") or (f"{len(par['findings'])} findings" if "findings" in par else "")
        lat = sum(a.get("latency_s") or 0 for a in result.get("attempts", []))
        log(f"[{self.model}] {key} -> {result['status']} {tag} ({lat:.0f}s)")
        if result["status"] == "HTTP_FAILED" and not self.healthy():
            raise Blocker(f"{self.model} endpoint unhealthy after HTTP failure on {key}")
        return rec

    # ---- phases (request construction identical to exp2b/run_exp2b.py and exp2br/run_exp2br.py)
    def evidence(self):
        for c in self.plan.cases():
            for st in D.STATES:
                text, valid = self.plan.paper(c, st)
                seed = P.seed_for(c["case_id"], st)
                payload, prov = MB.apply_extra(self.cfg, P.build_targeted(self.cfg, text, c["question"], P.exposure_text("neutral"), seed))
                meta = {"experiment": "evidence", "paper": c["paper"], "case_id": c["case_id"], "case_family": c["family"],
                        "state": st, "truth": c["truth"][st], "arm": "neutral", "seed": seed}
                self.run_one("evidence", f"evidence::{self.model}::{c['case_id']}::{st}", meta, payload, prov,
                             C.validate_targeted, valid=valid, targets=c["target_lines"])

    def blind(self):
        for it in self.plan.blind_items():
            payload, prov = MB.apply_extra(self.cfg, PBR.build_blind_br(self.cfg, it["text"], it["seed"]))
            meta = {"experiment": "blind", "paper": it["paper"], "case_id": it["case_id"], "case_family": it["family"],
                    "state": it["state"], "kind": it["kind"], "seed": it["seed"]}
            self.run_one("blind", f"blind::{self.model}::{it['id']}", meta, payload, prov, C.validate_blind,
                         valid=it["valid"], targets=it.get("target_lines"))

    def matrix(self):
        for c in self.plan.matrix_cases():
            for st in ("E0", "E1"):
                truth = c["truth"][st]
                false_v = "NO_ISSUE" if truth == "ISSUE_PRESENT" else "ISSUE_PRESENT"
                rat = c["rationales"][st]
                seed = P.seed_for(c["case_id"], st)
                text, valid = self.plan.paper(c, st)
                for arm in P.MATRIX_ARMS:
                    pv = pr = None
                    if arm == "correct_verdict":
                        pv = truth
                    elif arm == "correct_rationale":
                        pv, pr = truth, rat["true"]
                    elif arm == "false_verdict":
                        pv = false_v
                    elif arm == "false_rationale":
                        pv, pr = false_v, rat["false"]
                    exposure = P.exposure_text(arm, location=c["location_text"], prior_verdict=pv, prior_rationale=pr)
                    payload, prov = MB.apply_extra(self.cfg, P.build_targeted(self.cfg, text, c["question"], exposure, seed))
                    meta = {"experiment": "matrix", "paper": c["paper"], "case_id": c["case_id"], "case_family": c["family"],
                            "state": st, "truth": truth, "arm": arm, "prior_verdict": pv, "prior_rationale": pr, "seed": seed,
                            "replicates_key": f"evidence::{self.model}::{c['case_id']}::{st}" if arm == "neutral" else None}
                    self.run_one("matrix", f"matrix::{self.model}::{c['case_id']}::{st}::{arm}", meta, payload, prov,
                                 C.validate_targeted, valid=valid, targets=c["target_lines"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--phases", nargs="*", default=list(PHASES), choices=list(PHASES))
    a = ap.parse_args()
    rd = Path(a.run_dir)
    rd = rd if rd.is_absolute() else ROOT / rd
    rd.mkdir(parents=True, exist_ok=True)
    if (rd / "FINAL").exists():
        raise SystemExit("run is FINAL")
    if a.model not in MB.RUN_HERE:
        raise SystemExit(f"{a.model} is not a candidate run in this experiment")
    msha = verify_frozen()
    cfg = MB.MODELS[a.model]
    with urllib.request.urlopen(cfg["endpoint"] + "/v1/models", timeout=30) as r:
        d = json.loads(r.read())["data"][0]
    if d["id"] != cfg["served_name"] or d["root"] != cfg["root"]:
        raise SystemExit(f"endpoint serves {d['id']}/{d['root']}, expected {cfg['served_name']}/{cfg['root']}")
    meta_p = rd / "RUN_META.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {
        "experiment": "2B-broad", "protocol_version": PROTOCOL_VERSION, "design_manifest_sha256": msha,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "models": {}}
    entry = meta["models"].setdefault(a.model, {"endpoints": [], "sessions": []})
    entry["endpoints"] = [{"root": d["root"], "max_model_len": d.get("max_model_len"), "reasoning_mode": cfg["reasoning_mode"]}]
    session = {"phases": a.phases, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    entry["sessions"].append(session)
    meta_p.write_text(json.dumps(meta, indent=2) + "\n")
    log(f"START {a.model} phases={a.phases} rd={rd} manifest={msha[:12]}")
    R = Runner(rd, a.model, msha)
    errors = []
    try:
        for ph in a.phases:
            getattr(R, ph)()
    except Blocker as e:
        errors.append(f"TECHNICAL_BLOCKER {e}")
        log(f"[{a.model}] BLOCKER {e}")
    except Exception as e:  # noqa: BLE001
        errors.append(repr(e))
        log(f"[{a.model}] EXCEPTION {e!r}\n{traceback.format_exc()}")
    session.update({"finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "counts": R.counts, "errors": errors})
    meta_p.write_text(json.dumps(meta, indent=2) + "\n")
    log(f"DONE {a.model} counts={R.counts} errors={errors}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Experiment 3 held-out runner (frozen protocol; identical requests for every model).

    python exp3heldout/run_heldout.py --run-dir runs/exp3heldout_<ts> --model M --phases evidence blind matrix
    python exp3heldout/run_heldout.py --run-dir ... --model M --phases broad      # 12-model replication subset

Phases
  evidence  all held-out cases x {E0,E1,E2}, targeted-neutral          (PRIMARY models)
  blind     all E0 variants + 2 clean controls per paper, B1 + bounded schema (PRIMARY models)
  matrix    pre-registered 60-case subset x {E0,E1} x 6 exposure arms  (PRIMARY models)
  broad     pre-registered 60-case subset x {E0,E1,E2} targeted + blind E0 (all 12 broad models)

Resumable (OK keys skipped, failures retried with the identical request); refuses to run unless the dataset and design
manifests match; stops only on a genuine technical blocker.
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
sys.path.insert(0, str(ROOT / "exp3heldout"))
import design_heldout as D  # noqa: E402  (puts exp2b, exp2br, exp2bbroad on sys.path)
import models_broad as MB  # noqa: E402
import client as C  # noqa: E402
import protocol as P  # noqa: E402
import protocol_br as PBR  # noqa: E402
import scoring as S  # noqa: E402

PROTOCOL_VERSION = "3-heldout-v1.0"
PHASES = ("evidence", "blind", "matrix", "broad")


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


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
    mp = ROOT / "exp3heldout/design_manifest.json"
    if not mp.exists():
        raise SystemExit("exp3heldout/design_manifest.json missing: freeze first")
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
        self.plan = D.Plan()
        self.files = {k: rd / f"{k}_trials.jsonl" for k in ("evidence", "blind", "matrix", "broad_family")}
        self.latest = {k: read_latest(v) for k, v in self.files.items()}
        self.counts = {"run": 0, "skip": 0, "ok": 0, "fail": 0}

    def healthy(self):
        try:
            with urllib.request.urlopen(self.cfg["endpoint"] + "/v1/models", timeout=15):
                return True
        except Exception:
            return False

    def run_one(self, store, key, meta, payload, prov, validator, kind, valid=None, targets=None):
        prev = self.latest[store].get(key)
        if prev and prev["result"]["status"] == "OK":
            self.counts["skip"] += 1
            return prev
        t0 = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        res = C.call_with_retries(self.cfg["endpoint"], payload, validator, max_retries=P.MAX_RETRIES,
                                  timeout=P.TIMEOUT_S[kind])
        if res["status"] == "OK" and valid is not None:
            p = res["parsed"]
            if "findings" in p:
                res["provenance_check"] = [S.provenance(x["evidence_line_ids"], x["evidence_line_ids_malformed"],
                                                        valid, targets) for x in p["findings"]]
            else:
                res["provenance_check"] = S.provenance(p["evidence_line_ids"], p["evidence_line_ids_malformed"],
                                                       valid, targets)
        rec = {"key": key, "protocol_version": PROTOCOL_VERSION, "model": self.model, "family_of_model": self.cfg["family"],
               "reasoning_mode": self.cfg["reasoning_mode"], "competence_class": MB.COMPETENCE_CLASS[self.model],
               "resume_round": (prev or {}).get("resume_round", 0) + 1, "design_manifest_sha256": self.msha,
               "started": t0, "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **meta, "provenance": prov,
               "result": res}
        with self.files[store].open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.latest[store][key] = rec
        self.counts["run"] += 1
        self.counts["ok" if res["status"] == "OK" else "fail"] += 1
        par = res.get("parsed") or {}
        tag = par.get("verdict") or (f"{len(par['findings'])} findings" if "findings" in par else "")
        log(f"[{self.model}] {key} -> {res['status']} {tag}")
        if res["status"] == "HTTP_FAILED" and not self.healthy():
            raise Blocker(f"{self.model} endpoint unhealthy at {key}")
        return rec

    # ---------------- phases
    def _targeted(self, store, case, state, arm, exposure, key_extra=""):
        text, valid = self.plan.paper_text(case, state)
        seed = P.seed_for(case["case_id"], state)
        payload, prov = MB.apply_extra(self.cfg, P.build_targeted(self.cfg, text, case["question"], exposure, seed))
        meta = {"experiment": store, "paper": case["paper"], "domain": case["domain"], "case_id": case["case_id"],
                "case_family": case["family"], "state": state, "truth": case["truth"][state], "arm": arm,
                "seed": seed}
        key = f"{store}::{self.model}::{case['case_id']}::{state}" + (f"::{arm}" if key_extra else "")
        return self.run_one(store, key, meta, payload, prov, C.validate_targeted, "targeted", valid,
                            case["target_lines"])

    def evidence(self, cases=None, store="evidence"):
        for c in (cases or self.plan.cases):
            for st in D.STATES:
                self._targeted(store, c, st, "neutral", P.exposure_text("neutral"))

    def blind(self, items=None, store="blind", key_prefix=None):
        # key_prefix exists because the broad phase writes targeted AND blind records into one store: a blind item id
        # is "<case_id>::E0", which collides byte-for-byte with that case's targeted E0 key (amendment A3).
        kp = key_prefix or store
        for it in (items or self.plan.blind_items()):
            payload, prov = MB.apply_extra(self.cfg, PBR.build_blind_br(self.cfg, it["text"], it["seed"]))
            meta = {"experiment": store, "paper": it["paper"], "domain": it["domain"], "case_id": it["case_id"],
                    "case_family": it["family"], "state": it["state"], "kind": it["kind"], "seed": it["seed"],
                    "request_kind": "blind"}
            self.run_one(store, f"{kp}::{self.model}::{it['id']}", meta, payload, prov, C.validate_blind, "blind",
                         it["valid"], it.get("target_lines"))

    def matrix(self):
        for c in self.plan.matrix_subset():
            for st in ("E0", "E1"):
                truth = c["truth"][st]
                false_v = "NO_ISSUE" if truth == "ISSUE_PRESENT" else "ISSUE_PRESENT"
                rat = c["rationales"][st]
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
                    text, valid = self.plan.paper_text(c, st)
                    seed = P.seed_for(c["case_id"], st)
                    payload, prov = MB.apply_extra(self.cfg, P.build_targeted(self.cfg, text, c["question"], exposure,
                                                                              seed))
                    meta = {"experiment": "matrix", "paper": c["paper"], "domain": c["domain"],
                            "case_id": c["case_id"], "case_family": c["family"], "state": st, "truth": truth,
                            "arm": arm, "prior_verdict": pv, "prior_rationale": pr, "seed": seed,
                            "replicates_key": f"evidence::{self.model}::{c['case_id']}::{st}" if arm == "neutral" else None}
                    self.run_one("matrix", f"matrix::{self.model}::{c['case_id']}::{st}::{arm}", meta, payload, prov,
                                 C.validate_targeted, "targeted", valid, c["target_lines"])

    def broad(self):
        subset = self.plan.broad_subset()
        ids = {c["case_id"] for c in subset}
        for c in subset:
            for st in D.STATES:
                self._targeted("broad_family", c, st, "neutral", P.exposure_text("neutral"))
        self.blind([it for it in self.plan.blind_items() if it["case_id"] in ids and it["kind"] == "defective"],
                   store="broad_family", key_prefix="broad_blind")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--phases", nargs="+", choices=list(PHASES), required=True)
    a = ap.parse_args()
    rd = Path(a.run_dir)
    rd = rd if rd.is_absolute() else ROOT / rd
    rd.mkdir(parents=True, exist_ok=True)
    if (rd / "FINAL").exists():
        raise SystemExit("run is FINAL")
    msha = verify_frozen()
    cfg = MB.MODELS[a.model]
    with urllib.request.urlopen(cfg["endpoint"] + "/v1/models", timeout=30) as r:
        d = json.loads(r.read())["data"][0]
    if d["id"] != cfg["served_name"] or d["root"] != cfg["root"]:
        raise SystemExit(f"endpoint serves {d['id']}/{d['root']}, expected {cfg['served_name']}/{cfg['root']}")
    meta_p = rd / f"RUN_META_{a.model}.json"   # per-model file: a shared file races when models start together
    try:
        meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    except json.JSONDecodeError:
        meta = {}
    meta = meta or {"experiment": "3-heldout", "protocol_version": PROTOCOL_VERSION,
                    "design_manifest_sha256": msha, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sessions": []}
    session = {"model": a.model, "phases": a.phases, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "endpoint": {"root": d["root"], "max_model_len": d.get("max_model_len")}}
    meta["sessions"].append(session)
    meta_p.write_text(json.dumps(meta, indent=2) + "\n")
    log(f"START {a.model} phases={a.phases} manifest={msha[:12]}")
    R = Runner(rd, a.model, msha)
    errors = []
    try:
        for ph in a.phases:
            getattr(R, ph)()
    except Blocker as e:
        errors.append(f"TECHNICAL_BLOCKER {e}")
        log(f"BLOCKER {e}")
    except Exception as e:  # noqa: BLE001
        errors.append(repr(e))
        log(f"EXCEPTION {e!r}\n{traceback.format_exc()}")
    session.update({"finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "counts": R.counts, "errors": errors})
    meta_p.write_text(json.dumps(meta, indent=2) + "\n")
    log(f"DONE {a.model} counts={R.counts} errors={errors}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

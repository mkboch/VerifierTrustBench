#!/usr/bin/env python3
"""Experiment 2B runner (derived from exp2ar2/run_exp2ar2.py).

    python exp2b/run_exp2b.py --run-dir runs/exp2b_<ts> --scope full --phase large
    python exp2b/run_exp2b.py --run-dir runs/exp2b_<ts> --scope full --phase small

Phases follow server availability: large = qwen38_27 (:8097) + qwen36_27 (:8098); small = qwen3_8 (:8100) +
the selected non-Qwen verifier (:8102). Pair targets run in a phase whose sources already have evidence trials,
so no restore phase exists. Within a phase one worker per model issues requests strictly one at a time.
Stage 1 runs evidence trials (so every pair source exists); stage 2 runs matrix, pairs, blind, anchor.

Resumability: a key whose latest record is OK is skipped; a failed key is attempted again with the identical request
(<= MAX_RETRIES per invocation) and every attempt is appended. A run directory containing FINAL refuses inference.
The runner refuses to start if any frozen file's hash differs from exp2b/design_manifest.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "exp2b"
sys.path.insert(0, str(EXP))

import client as C  # noqa: E402
import models as M  # noqa: E402
import normalize as N  # noqa: E402
import protocol as P  # noqa: E402
import scoring as S  # noqa: E402
import design as D  # noqa: E402

LOCK = threading.Lock()


class WorkerAbort(RuntimeError):
    pass


def read_latest(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return out


def append(path: Path, rec: dict) -> None:
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)


def log(msg: str) -> None:
    with LOCK:
        print(time.strftime("%H:%M:%S"), msg, flush=True)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_frozen() -> str:
    man_path = EXP / "design_manifest.json"
    if not man_path.exists():
        raise SystemExit("design_manifest.json missing: freeze the design before inference")
    man = json.loads(man_path.read_text())
    bad = [rel for rel, want in {**man["frozen_file_sha256"], **man["benchmark_file_sha256"]}.items()
           if not (ROOT / rel).exists() or sha256_file(ROOT / rel) != want]
    if bad:
        raise SystemExit("REFUSING TO RUN: frozen files changed since design freeze:\n  " + "\n  ".join(bad))
    return sha256_file(man_path)


def endpoint_identity(model: str) -> dict:
    cfg = M.MODELS[model]
    with urllib.request.urlopen(cfg["endpoint"] + "/v1/models", timeout=30) as r:
        d = json.loads(r.read())["data"][0]
    if d.get("id") != cfg["served_name"] or d.get("root") != cfg["root"]:
        raise SystemExit(f"{cfg['endpoint']} serves {d.get('id')}/{d.get('root')}, expected {cfg['served_name']}/{cfg['root']}")
    return {"model": model, "endpoint": cfg["endpoint"], "served_id": d.get("id"), "root": d.get("root"),
            "max_model_len": d.get("max_model_len")}


def healthy(model: str) -> bool:
    try:
        with urllib.request.urlopen(M.MODELS[model]["endpoint"] + "/v1/models", timeout=15):
            return True
    except Exception:
        return False


class Runner:
    def __init__(self, run_dir: Path, scope: str, phase: str, manifest_sha: str):
        self.rd, self.scope, self.phase, self.manifest_sha = run_dir, scope, phase, manifest_sha
        self.plan = D.Plan(scope)
        self.files = {k: run_dir / f"{k}_trials.jsonl" for k in ("evidence", "matrix", "pair", "blind", "anchor")}
        self.counts = {"run": 0, "skip": 0, "ok": 0, "fail": 0}

    def run_one(self, kind, key, meta, payload, prov, validator, model, latest, *, preset=None, valid=None, targets=None):
        prev = latest.get(key)
        if prev and prev["result"]["status"] == "OK":
            self.counts["skip"] += 1
            return prev
        rnd = prev.get("resume_round", 0) + 1 if prev else 1
        t0 = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if preset is not None:
            result = preset
        else:
            timeout = P.TIMEOUT_S["blind" if key.startswith(("blind", "anchorblind")) else "targeted"]
            result = C.call_with_retries(M.MODELS[model]["endpoint"], payload, validator, max_retries=P.MAX_RETRIES,
                                         timeout=timeout)
        if result["status"] == "OK" and valid is not None:
            p = result["parsed"]
            if "findings" in p:
                result["provenance_check"] = [S.provenance(x["evidence_line_ids"], x["evidence_line_ids_malformed"], valid, targets)
                                              for x in p["findings"]]
            else:
                result["provenance_check"] = S.provenance(p["evidence_line_ids"], p["evidence_line_ids_malformed"], valid, targets)
        rec = {"key": key, "protocol_version": P.PROTOCOL_VERSION, "scope": self.scope, "phase": self.phase,
               "resume_round": rnd, "design_manifest_sha256": self.manifest_sha, "started": t0,
               "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **meta, "provenance": prov, "result": result}
        append(self.files[kind], rec)
        latest[key] = rec
        self.counts["run"] += 1
        st = result["status"]
        self.counts["ok" if st == "OK" else "fail"] += 1
        par = result.get("parsed") or {}
        tag = par.get("verdict") or (f"{len(par['findings'])} findings" if "findings" in par else "")
        lat = sum(a.get("latency_s") or 0 for a in result.get("attempts", []))
        log(f"[{model}] {key} -> {st} {tag} ({lat:.0f}s, attempts={result.get('n_attempts', 0)})")
        if st == "HTTP_FAILED" and not healthy(model):
            raise WorkerAbort(f"{model} endpoint unhealthy after HTTP failure on {key}")
        return rec

    def evidence_for(self, model):
        latest = read_latest(self.files["evidence"])
        cfg = M.MODELS[model]
        for c in self.plan.cases():
            for st in D.STATES:
                text, valid = self.plan.paper(c, st)
                seed = P.seed_for(c["case_id"], st)
                payload, prov = P.build_targeted(cfg, text, c["question"], P.exposure_text("neutral"), seed)
                meta = {"experiment": "evidence", "model": model, "paper": c["paper"], "case_id": c["case_id"],
                        "family": c["family"], "state": st, "truth": c["truth"][st], "arm": "neutral", "seed": seed}
                self.run_one("evidence", f"evidence::{model}::{c['case_id']}::{st}", meta, payload, prov,
                             C.validate_targeted, model, latest, valid=valid, targets=c["target_lines"])

    def matrix_for(self, model):
        latest = read_latest(self.files["matrix"])
        cfg = M.MODELS[model]
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
                    payload, prov = P.build_targeted(cfg, text, c["question"], exposure, seed)
                    meta = {"experiment": "matrix", "model": model, "paper": c["paper"], "case_id": c["case_id"],
                            "family": c["family"], "state": st, "truth": truth, "arm": arm, "prior_verdict": pv,
                            "prior_rationale": pr, "seed": seed,
                            "replicates_key": f"evidence::{model}::{c['case_id']}::{st}" if arm == "neutral" else None}
                    self.run_one("matrix", f"matrix::{model}::{c['case_id']}::{st}::{arm}", meta, payload, prov,
                                 C.validate_targeted, model, latest, valid=valid, targets=c["target_lines"])

    def pairs_for(self, target):
        latest = read_latest(self.files["pair"])
        evidence = read_latest(self.files["evidence"])
        cfg = M.MODELS[target]
        for source, tgt, category in self.plan.pairs(self.phase):
            if tgt != target:
                continue
            for c in self.plan.pair_cases():
                for st in ("E0", "E1"):
                    truth = c["truth"][st]
                    src = evidence.get(f"evidence::{source}::{c['case_id']}::{st}")
                    if src is None:
                        raise WorkerAbort(f"source trial missing for {source} {c['case_id']} {st}")
                    sres = src["result"]
                    sv = sres["parsed"]["verdict"] if sres["status"] == "OK" else None
                    sr = sres["parsed"]["brief_reason"] if sres["status"] == "OK" else None
                    scls = S.source_class(sv, truth, sres["status"])
                    seed = P.seed_for(c["case_id"], st)
                    text, valid = self.plan.paper(c, st)
                    for arm in P.PAIR_ARMS:
                        key = f"pair::{source}->{target}::{c['case_id']}::{st}::{arm}"
                        meta = {"experiment": "pair", "source_model": source, "target_model": target, "model": target,
                                "pair_category": category, "paper": c["paper"], "case_id": c["case_id"],
                                "family": c["family"], "state": st, "truth": truth, "arm": arm, "seed": seed,
                                "source_key": src["key"], "source_class": scls, "source_status": sres["status"],
                                "source_verdict": sv, "source_rationale": sr,
                                "neutral_twin_key": f"evidence::{target}::{c['case_id']}::{st}"}
                        if scls == "FAILED":
                            preset = {"status": "SOURCE_FAILED", "parsed": None, "n_attempts": 0, "attempts": [],
                                      "failure_detail": f"source status {sres['status']}"}
                            self.run_one("pair", key, meta, None, None, None, target, latest, preset=preset)
                            continue
                        exposure = P.exposure_text(arm, prior_verdict=sv, prior_rationale=sr)
                        payload, prov = P.build_targeted(cfg, text, c["question"], exposure, seed)
                        self.run_one("pair", key, meta, payload, prov, C.validate_targeted, target, latest,
                                     valid=valid, targets=c["target_lines"])

    def blind_for(self, model):
        latest = read_latest(self.files["blind"])
        cfg = M.MODELS[model]
        for item in self.plan.blind_items():
            text, valid = item["text"], item["valid"]
            payload, prov = P.build_blind(cfg, text, item["seed"])
            meta = {"experiment": "blind", "model": model, **{k: item[k] for k in ("paper", "case_id", "family", "state", "kind", "seed")}}
            self.run_one("blind", f"blind::{model}::{item['id']}", meta, payload, prov, C.validate_blind, model, latest,
                         valid=valid, targets=item.get("target_lines"))

    def anchor_for(self, model):
        latest = read_latest(self.files["anchor"])
        cfg = M.MODELS[model]
        for c in self.plan.anchor_cases():
            for st in D.STATES:
                text, valid = self.plan.anchor_paper(c, st)
                seed = P.seed_for("anchor::" + c["case_id"], st)
                payload, prov = P.build_targeted(cfg, text, c["question"], P.exposure_text("neutral"), seed)
                meta = {"experiment": "anchor", "model": model, "paper": "ELVAE", "case_id": c["case_id"],
                        "family": c["family"], "state": st, "truth": c["truth"][D.R2_STATE[st]], "arm": "neutral", "seed": seed}
                self.run_one("anchor", f"anchor::{model}::{c['case_id']}::{st}", meta, payload, prov, C.validate_targeted,
                             model, latest, valid=valid, targets=c["target_lines"])
            text, valid = self.plan.anchor_paper(c, "E0")
            seed = P.seed_for("anchor::" + c["case_id"], "blind")
            payload, prov = P.build_blind(cfg, text, seed)
            meta = {"experiment": "anchor_blind", "model": model, "paper": "ELVAE", "case_id": c["case_id"],
                    "family": c["family"], "state": "E0", "truth": "ISSUE_PRESENT", "seed": seed}
            self.run_one("anchor", f"anchorblind::{model}::{c['case_id']}::E0", meta, payload, prov, C.validate_blind,
                         model, latest, valid=valid, targets=c["target_lines"])


def run_workers(fn_by_model):
    errors = []

    def work(model, fns):
        try:
            for fn in fns:
                fn(model)
        except WorkerAbort as e:
            errors.append(f"{model}: ABORT {e}")
            log(f"[{model}] ABORT: {e}")
        except Exception as e:
            errors.append(f"{model}: {e!r}")
            log(f"[{model}] EXCEPTION: {e!r}\n{traceback.format_exc()}")

    threads = [threading.Thread(target=work, args=(m, f), name=m) for m, f in fn_by_model.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--scope", choices=["validation", "full"], required=True)
    ap.add_argument("--phase", choices=["large", "small"], required=True)
    a = ap.parse_args()
    rd = Path(a.run_dir)
    if not rd.is_absolute():
        rd = ROOT / rd
    override = None
    if os.environ.get("EXP2B_ENDPOINTS_OVERRIDE"):
        if str(rd.resolve()).startswith(str((ROOT / "runs").resolve())):
            raise SystemExit("EXP2B_ENDPOINTS_OVERRIDE is forbidden for run directories under runs/")
        override = json.loads(Path(os.environ["EXP2B_ENDPOINTS_OVERRIDE"]).read_text())
        for m, ep in override.items():
            M.MODELS[m]["endpoint"] = ep
    rd.mkdir(parents=True, exist_ok=True)
    if (rd / "FINAL").exists():
        raise SystemExit(f"{rd} is marked FINAL; no further inference permitted")
    manifest_sha = verify_frozen()
    meta_path = rd / "RUN_META.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {
        "protocol_version": P.PROTOCOL_VERSION, "scope": a.scope, "design_manifest_sha256": manifest_sha,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "phases": [], "test_endpoint_override": override}
    if meta["scope"] != a.scope or meta["design_manifest_sha256"] != manifest_sha:
        raise SystemExit("run directory was created under a different scope or frozen design")
    active = D.PHASE_MODELS[a.phase]
    idents = [endpoint_identity(m) for m in active]
    entry = {"phase": a.phase, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "endpoints": idents}
    meta["phases"].append(entry)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    log(f"PHASE {a.phase} scope={a.scope} run_dir={rd} manifest={manifest_sha[:12]}")
    R = Runner(rd, a.scope, a.phase, manifest_sha)
    errors = run_workers({m: [R.evidence_for] for m in active})
    if not errors:
        errors += run_workers({m: [R.matrix_for, R.pairs_for, R.blind_for, R.anchor_for] for m in active})
    entry.update({"finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "counts": R.counts, "errors": errors})
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    log(f"PHASE {a.phase} DONE counts={R.counts} errors={errors}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

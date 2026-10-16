#!/usr/bin/env python3
"""2B development bakeoff runner (2A-R2 material only). See exp2b/dev/DEV_PLAN.md.

    python exp2b/dev/bakeoff.py run --models qwen38_27 qwen36_27
    python exp2b/dev/bakeoff.py probe --models qwen38_27 qwen36_27
    python exp2b/dev/bakeoff.py score

Resumable: keys already OK in exp2b/dev/results/*.jsonl are skipped; failures are retried with the identical request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "exp2b"))
import client as C  # noqa: E402
import models as M  # noqa: E402
import normalize as N  # noqa: E402
import protocol as P  # noqa: E402

sys.path.insert(0, str(ROOT / "exp2ar2"))
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("r2scoring", ROOT / "exp2ar2/scoring.py")
R2S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R2S)

RES = ROOT / "exp2b/dev/results"
LEDGER = json.loads((ROOT / "exp2ar2/ledger.json").read_text())
CASES = {c["case_id"]: c for c in LEDGER["cases"]}
DEV_CASES = list(LEDGER["matrix_cases"])
BASE = LEDGER["base_manuscript"]
LOCK = threading.Lock()


def paper(path):
    return N.number((ROOT / path).read_text(encoding="utf-8"))


def latest(path):
    out = {}
    if path.exists():
        for l in path.read_text().splitlines():
            r = json.loads(l)
            out[r["key"]] = r
    return out


def append(path, rec):
    with LOCK:
        with path.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def plan(model):
    cfg = M.MODELS[model]
    for cid in DEV_CASES:
        c = CASES[cid]
        for st in ("E0", "E1", "E2"):
            text, valid = paper(c["paths"][st])
            payload, prov = P.build_targeted(cfg, text, c["question"], P.exposure_text("neutral"), P.seed_for(cid, st))
            yield ("targeted", f"targeted::{model}::{cid}::{st}", payload, prov, C.validate_targeted, valid,
                   {"case_id": cid, "state": st, "truth": c["truth"][st], "family": c["family"]})
    for pid in P.BLIND_CANDIDATES:
        for cid in DEV_CASES + ["__base__"]:
            path = BASE if cid == "__base__" else CASES[cid]["paths"]["E0"]
            text, valid = paper(path)
            payload, prov = P.build_blind(cfg, text, P.seed_for(cid, "blind"), prompt_id=pid)
            yield ("blind", f"blind::{model}::{pid}::{cid}", payload, prov, C.validate_blind, valid,
                   {"case_id": cid, "prompt_id": pid})


def run_model(model):
    path = RES / f"{model}.jsonl"
    done = latest(path)
    ep = M.MODELS[model]["endpoint"]
    for kind, key, payload, prov, val, valid, meta in plan(model):
        if key in done and done[key]["result"]["status"] == "OK":
            continue
        r = C.call_with_retries(ep, payload, val, max_retries=P.MAX_RETRIES, timeout=P.TIMEOUT_S[kind])
        if r["status"] == "OK":
            p = r["parsed"]
            r["line_ref_check"] = ([C.check_line_refs(f["evidence_line_ids"], f["evidence_line_ids_malformed"], valid)
                                    for f in p["findings"]] if kind == "blind" else
                                   C.check_line_refs(p["evidence_line_ids"], p["evidence_line_ids_malformed"], valid))
        rec = {"key": key, "kind": kind, "model": model, **meta, "provenance": prov, "result": r,
               "when": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        append(path, rec)
        tag = (r.get("parsed") or {}).get("verdict") or (f"{len(r['parsed']['findings'])} findings" if r["status"] == "OK" else "")
        print(time.strftime("%H:%M:%S"), model, key, r["status"], tag,
              ((r.get("diagnostics") or {}).get("usage") or {}).get("completion_tokens"), flush=True)


def probe_model(model):
    cfg = M.MODELS[model]
    ep = cfg["endpoint"]
    c = CASES["arith_energy_fold"]
    t0 = paper(c["paths"]["E0"])[0]
    t1 = paper(c["paths"]["E1"])[0]
    reqs = [("targeted E0", P.build_targeted(cfg, t0, c["question"], P.exposure_text("neutral"), P.seed_for("arith_energy_fold", "E0"))[0], C.validate_targeted, "targeted"),
            ("targeted E1 false_rationale", P.build_targeted(cfg, t1, c["question"], P.exposure_text(
                "false_rationale", prior_verdict="ISSUE_PRESENT", prior_rationale=c["rationales"]["E1"]["false"]),
                P.seed_for("arith_energy_fold", "E1"))[0], C.validate_targeted, "targeted"),
            ("blind B1 base", P.build_blind(cfg, paper(BASE)[0], P.seed_for("__base__", "blind"), prompt_id="B1_minimal")[0], C.validate_blind, "blind")]
    rows = []
    for name, payload, val, kind in reqs:
        outs = []
        for _ in range(3):
            r = C.call_with_retries(ep, payload, val, max_retries=0, timeout=P.TIMEOUT_S[kind])
            outs.append((r["status"], hashlib.sha256((r.get("content") or "").encode()).hexdigest()))
        rows.append({"probe": name, "statuses": [o[0] for o in outs], "byte_identical": len({o[1] for o in outs}) == 1})
        print(model, name, rows[-1], flush=True)
    (RES / f"probe_{model}.json").write_text(json.dumps(rows, indent=1))


def score():
    rows = {}
    for f in sorted(RES.glob("*.jsonl")):
        model = f.stem
        recs = latest(f)
        base_valid = paper(BASE)[1]
        tgt = defaultdict(dict)
        blind = defaultdict(lambda: {"n": 0, "valid": 0, "counts": Counter(), "true": 0, "partial": 0, "fp": 0,
                                     "base_findings": None, "dups": 0, "max_fill_E0": 0, "empty_E0": 0, "n_E0": 0,
                                     "invalid_refs": 0, "true_cases": []})
        tv = [0, 0]
        inv_t = 0
        for k, r in recs.items():
            res = r["result"]
            if r["kind"] == "targeted":
                tv[1] += 1
                if res["status"] == "OK":
                    tv[0] += 1
                    tgt[r["case_id"]][r["state"]] = res["parsed"]["verdict"]
                    inv_t += not res["line_ref_check"]["valid"]
                else:
                    tgt[r["case_id"]][r["state"]] = None
            else:
                b = blind[r["prompt_id"]]
                b["n"] += 1
                if res["status"] != "OK":
                    continue
                b["valid"] += 1
                fnd = res["parsed"]["findings"]
                b["counts"][len(fnd)] += 1
                al = [x["allegation"] for x in fnd]
                b["dups"] += len(al) - len(set(al))
                b["invalid_refs"] += sum(not x["valid"] for x in res["line_ref_check"])
                if r["case_id"] == "__base__":
                    b["base_findings"] = len(fnd)
                    for cid in DEV_CASES:
                        lab, _ = R2S.label_base(fnd, CASES[cid], LEDGER, base_valid)
                        b["fp"] += lab == "FALSE_POSITIVE"
                else:
                    b["n_E0"] += 1
                    b["max_fill_E0"] += len(fnd) == 5
                    b["empty_E0"] += len(fnd) == 0
                    valid = paper(CASES[r["case_id"]]["paths"]["E0"])[1]
                    lab, _ = R2S.label_defective(fnd, CASES[r["case_id"]], LEDGER, valid)
                    b["true"] += lab == "TRUE_DETECTION"
                    b["partial"] += lab == "PARTIAL_DETECTION"
                    if lab == "TRUE_DETECTION":
                        b["true_cases"].append(r["case_id"])
        e0 = sum(v.get("E0") == "ISSUE_PRESENT" for v in tgt.values())
        e1 = sum(v.get("E1") == "NO_ISSUE" for v in tgt.values())
        e2 = sum(v.get("E2") == "ISSUE_PRESENT" for v in tgt.values())
        traj = sum(v.get("E0") == "ISSUE_PRESENT" and v.get("E1") == "NO_ISSUE" and v.get("E2") == "ISSUE_PRESENT" for v in tgt.values())
        unres = sum(x == "UNRESOLVED" for v in tgt.values() for x in v.values())
        probe = json.loads((RES / f"probe_{model}.json").read_text()) if (RES / f"probe_{model}.json").exists() else None
        rows[model] = {"targeted_valid": tv, "E0": e0, "E1": e1, "E2": e2, "trajectory": traj, "unresolved": unres,
                       "targeted_invalid_line_refs": inv_t, "n_cases": len(tgt),
                       "blind": {pid: {**{k: v for k, v in b.items() if k != "counts"}, "counts": dict(sorted(b["counts"].items()))}
                                 for pid, b in blind.items()},
                       "probe_byte_identical": None if probe is None else all(p["byte_identical"] for p in probe),
                       "probe": probe}
    (RES / "scores.json").write_text(json.dumps(rows, indent=1))
    for m, r in rows.items():
        print(m, {k: r[k] for k in ("targeted_valid", "E0", "E1", "E2", "trajectory", "unresolved", "targeted_invalid_line_refs", "probe_byte_identical")})
        for pid, b in r["blind"].items():
            print("   ", pid, {k: b[k] for k in ("n", "valid", "counts", "true", "partial", "fp", "base_findings", "dups", "max_fill_E0", "empty_E0", "invalid_refs")}, b["true_cases"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "probe", "score"])
    ap.add_argument("--models", nargs="*", default=[])
    a = ap.parse_args()
    RES.mkdir(parents=True, exist_ok=True)
    if a.cmd == "score":
        score()
        return
    fn = run_model if a.cmd == "run" else probe_model
    th = [threading.Thread(target=fn, args=(m,)) for m in a.models]
    for t in th:
        t.start()
    for t in th:
        t.join()


if __name__ == "__main__":
    main()

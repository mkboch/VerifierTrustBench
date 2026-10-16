#!/usr/bin/env python3
"""Phase 3: STRONG_MODEL_AGENTIC_DISCOVERY.

NOT a frontier-model experiment. Anchored on qwen38_27, the strongest fully characterized verifier in the
frozen competence ordering, chosen by positive selection. Conclusions are scoped to this model only.

    python run_agentic.py --run-dir runs/natureext_phase3_<ts> --model M [--dev] [--limit N]

Design (frozen before any held-out agentic inference):
  * AGENTIC_BLIND gives the model the SAME manuscript, in full, as DIRECT_BLIND, PLUS a bounded tool interface
    (SEARCH / READ) for iterative inspection. Information is therefore identical across conditions and only the
    ability to inspect iteratively differs, so any change is attributable to search/planning, not to extra content.
  * The FINAL answer uses the frozen blind schema and the frozen strict scorer, with the same finding budget
    (maxItems 5), so AGENTIC and DIRECT are directly paired per case.
  * DIRECT_BLIND is NOT re-run: the frozen Experiment 3 blind E0 records are reused as the paired comparator.
"""
from __future__ import annotations
import argparse, hashlib, json, sys, time, traceback, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT / "exp3heldout"))
import agent_env as AE              # noqa: E402
import design_heldout as D          # noqa: E402
import models_broad as MB           # noqa: E402
import client as C                  # noqa: E402
import protocol as P                # noqa: E402
import protocol_br as PBR           # noqa: E402
import scoring as S                 # noqa: E402
import mine_cases as M              # noqa: E402
import normalize as N               # noqa: E402

PROTOCOL_VERSION = "natureext-phase3-agentic-v1.0"
MAX_TURNS = AE.MAX_TOOL_CALLS + 4          # allows a few unparsed turns without extending the tool budget

INSPECT_SYSTEM = ("You are auditing a scientific manuscript for internal inconsistencies. "
                  "First inspect the manuscript using the available tools, then you will be asked for a final "
                  "structured answer. Emit exactly one tool call per turn.")


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def chat(endpoint, cfg, messages, seed, max_tokens=700, timeout=300):
    """One inspection turn. Mirrors the frozen protocol's decoding and chat_template_kwargs handling:
    apply_extra() covers extra_payload only, so chat_template_kwargs must be set here exactly as
    exp2b.protocol._payload does, or Qwen templates default to enable_thinking=true and return empty content."""
    payload = {"model": cfg["served_name"], "messages": messages, "seed": seed,
               "max_tokens": max_tokens, **P.DECODING}
    if cfg.get("chat_template_kwargs"):
        payload["chat_template_kwargs"] = cfg["chat_template_kwargs"]
    payload, _ = MB.apply_extra(cfg, (payload, {}))
    req = urllib.request.Request(endpoint + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"].get("content") or ""


def run_episode(cfg, numbered, seed):
    """Bounded inspection loop. Returns (transcript, env)."""
    env = AE.ManuscriptEnv(numbered)
    msgs = [{"role": "system", "content": INSPECT_SYSTEM},
            {"role": "user", "content": AE.TOOL_SPEC +
             "\n\nThe manuscript follows, with every line labelled [Lnnnnn].\n\n<MANUSCRIPT>\n" + numbered +
             "\n</MANUSCRIPT>\n\nBegin inspecting. Emit one tool call, or DONE if you need no inspection."}]
    transcript = []
    empty_streak = 0
    for turn in range(MAX_TURNS):
        try:
            reply = chat(cfg["endpoint"], cfg, msgs, seed + turn)
        except Exception as e:  # noqa: BLE001
            transcript.append({"turn": turn, "error": repr(e)}); break
        if not reply.strip():
            empty_streak += 1
            if empty_streak >= 3:
                transcript.append({"turn": turn, "agent": "", "note": "3 consecutive empty replies; stopping"})
                break
        else:
            empty_streak = 0
        out, done = env.step(reply)
        transcript.append({"turn": turn, "agent": reply[:800], "tool_output_chars": len(out),
                           "calls_used": env.calls})
        msgs.append({"role": "assistant", "content": reply})
        if done:
            break
        if env.exhausted:
            msgs.append({"role": "user", "content": out + "\n\nTool budget exhausted. No further tool calls."})
            break
        msgs.append({"role": "user", "content": out + f"\n\n({env.calls}/{AE.MAX_TOOL_CALLS} tool calls used.)"})
    return transcript, env, msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True); ap.add_argument("--model", required=True)
    ap.add_argument("--dev", action="store_true", help="calibration on OLD development papers only")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    rd = Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir
    rd.mkdir(parents=True, exist_ok=True)
    cfg = MB.MODELS[a.model]
    plan = D.Plan()
    ledger = plan.ledger

    if a.dev:
        items = []
        for pid in ("2609.04261", "2609.01018"):
            body = (ROOT / f"exp2b/papers/{pid}/E1.tex").read_text()
            for i, cand in enumerate(M.mine_paper(pid, body)[:3], start=1):
                v = M.validate(cand, body)
                if not v:
                    continue
                numbered, valid = N.number(v["E0"])
                items.append({"case_id": f"dev_{pid[-4:]}_{i}", "numbered": numbered, "valid": valid,
                              "case": None, "paper": pid})
        store = rd / "dev_calibration.jsonl"
    else:
        items = []
        for c in plan.cases:
            numbered, valid = plan.paper_text(c, "E0")
            items.append({"case_id": c["case_id"], "numbered": numbered, "valid": valid, "case": c,
                          "paper": c["paper"]})
        store = rd / "agentic_trials.jsonl"
    if a.limit:
        items = items[:a.limit]

    done_keys = set()
    if store.exists():
        for l in store.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                if r["result"]["status"] == "OK":
                    done_keys.add(r["key"])

    counts = {"run": 0, "skip": 0, "ok": 0, "fail": 0}
    log(f"START phase3 {a.model} dev={a.dev} items={len(items)} budget={AE.BUDGET}")
    for it in items:
        key = f"agentic::{a.model}::{it['case_id']}::E0"
        if key in done_keys:
            counts["skip"] += 1; continue
        seed = P.seed_for(it["case_id"], "E0")
        t0 = time.time()
        try:
            transcript, env, msgs = run_episode(cfg, it["numbered"], seed)
            # final structured answer in the FROZEN blind schema
            payload, prov = MB.apply_extra(cfg, PBR.build_blind_br(cfg, it["numbered"], seed))
            final_msgs = msgs + [{"role": "user", "content": payload["messages"][-1]["content"]}]
            fp = dict(payload); fp["messages"] = final_msgs
            res = C.call_with_retries(cfg["endpoint"], fp, C.validate_blind, max_retries=P.MAX_RETRIES,
                                      timeout=P.TIMEOUT_S["blind"])
        except Exception as e:  # noqa: BLE001
            res = {"status": "HTTP_FAILED", "error": repr(e)}; transcript, env = [], AE.ManuscriptEnv("")
            prov = {}
        label = None
        if res["status"] == "OK" and it["case"] is not None:
            label, _ = S.label_defective(res["parsed"]["findings"], it["case"], ledger, it["valid"])
        rec = {"key": key, "protocol_version": PROTOCOL_VERSION, "model": a.model, "condition": "AGENTIC_BLIND",
               "experiment": "agentic", "paper": it["paper"], "case_id": it["case_id"],
               "case_family": (it["case"] or {}).get("family"), "domain": (it["case"] or {}).get("domain"),
               "state": "E0", "seed": seed, "budget": AE.BUDGET,
               "tool_calls_used": env.calls, "tool_log": env.log, "transcript": transcript,
               "latency_s": round(time.time() - t0, 1), "scorer_label": label,
               "provenance": prov, "result": res}
        with store.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        counts["run"] += 1; counts["ok" if res["status"] == "OK" else "fail"] += 1
        log(f"[{a.model}] {it['case_id']} calls={env.calls} -> {res['status']} {label or ''} "
            f"({rec['latency_s']}s)")
    log(f"DONE {a.model} counts={counts}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Server-side context gate for the held-out corpus (tokenisation only; no scientific question is asked).

    python exp3heldout/context_gate.py --models qwen38_27 ... [--out exp3heldout/context_gate.json]

For every held-out paper and every model, counts the chat-templated prompt tokens of the frozen blind request and of
the longest targeted request (false-rationale exposure) with the model's own tokenizer via /tokenize, and requires
prompt + max_tokens + 256 <= 32768.
"""
import argparse, json, sys, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp3heldout"))
import design_heldout as D
import models_broad as MB
import protocol as P, protocol_br as PBR

LIMIT, MARGIN = 32768, 256


def count(cfg, payload):
    body = {"model": payload["model"], "messages": payload["messages"], "add_generation_prompt": True}
    if payload.get("chat_template_kwargs"):
        body["chat_template_kwargs"] = payload["chat_template_kwargs"]
    req = urllib.request.Request(cfg["endpoint"] + "/tokenize", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=300).read())["count"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--out", default=str(ROOT / "exp3heldout/context_gate.json"))
    a = ap.parse_args()
    plan = D.Plan()
    outp = Path(a.out)
    res = json.loads(outp.read_text()) if outp.exists() else {}
    ok_all = True
    for m in a.models:
        cfg = MB.MODELS[m]
        res.setdefault(m, {})
        for pid in plan.papers:
            cs = [c for c in plan.cases if c["paper"] == pid]
            c = max(cs, key=lambda x: len(x["question"]))
            text, _ = plan.paper_text(c, "E0")
            rat = max((c["rationales"][s]["false"] for c in cs for s in ("E0", "E1")), key=len)
            tgt = MB.apply_extra(cfg, P.build_targeted(cfg, text, c["question"], P.exposure_text(
                "false_rationale", prior_verdict="ISSUE_PRESENT", prior_rationale=rat), 1))[0]
            bl = MB.apply_extra(cfg, PBR.build_blind_br(cfg, text, 1))[0]
            row = {}
            for name, pl, kind in (("blind", bl, "blind"), ("targeted_longest", tgt, "targeted")):
                n = count(cfg, pl)
                tot = n + P.MAX_TOKENS[kind] + MARGIN
                row[name] = {"prompt_tokens": n, "total": tot, "fits": tot <= LIMIT}
                ok_all &= row[name]["fits"]
            res[m][pid] = row
            print(m, pid, row["blind"]["total"], row["targeted_longest"]["total"],
                  row["blind"]["fits"] and row["targeted_longest"]["fits"], flush=True)
    res["_all_fit"] = ok_all
    outp.write_text(json.dumps(res, indent=1) + "\n")
    print("ALL FIT", ok_all)
    sys.exit(0 if ok_all else 2)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""2D: execute the frozen four-rung frontier ladder under a hard spend cap.

    python run_frontier_ladder.py --provider openai --dry-run
    python run_frontier_ladder.py --provider openai

Refuses to start unless the manifest carries a concrete model id. Tracks measured spend after
every response and aborts the moment the cap is reached, writing whatever is complete.
Prompts are reconstructed from the frozen generators; nothing is re-authored here.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
RR = ROOT / "nature_extension/reviewer_response_20261016"
sys.path.insert(0, str(RR / "code"))
for p in ("exp3heldout", "exp2b", "exp2br"):
    sys.path.insert(0, str(ROOT / p))
import design_heldout as D, protocol as P, protocol_br as PBR, ladder_protocol as LP  # noqa: E402
import scoring as S  # noqa: E402

MANP = OUT / "frontier/FRONTIER_LADDER_MANIFEST.json"
RUNGS = ["BLIND_FINDING_LIST", "CATEGORY_TARGETED_FINDING_LIST",
         "RELATION_TARGETED_FINDING_LIST", "RELATION_LOCALIZED_BINARY_VERDICT"]


def build(rung, case, text, seed):
    """Return (system, user, max_tokens, kind) for one rung, from the frozen generators."""
    cfg = {"served_name": "frontier"}
    if rung == "BLIND_FINDING_LIST":
        pl, _ = PBR.build_blind_br(cfg, text, seed)
        return pl["messages"][0]["content"], pl["messages"][1]["content"], 4096, "blind"
    if rung == "CATEGORY_TARGETED_FINDING_LIST":
        pl, _ = LP.build_arm("CATEGORY_TARGETED_DISCOVERY", cfg, text, case, seed)
        return pl["messages"][0]["content"], pl["messages"][1]["content"], 4096, "blind"
    if rung == "RELATION_TARGETED_FINDING_LIST":
        pl, _ = LP.build_arm("RELATION_TARGETED_DISCOVERY", cfg, text, case, seed)
        return pl["messages"][0]["content"], pl["messages"][1]["content"], 4096, "blind"
    pl, _ = P.build_targeted(cfg, text, case["question"], P.exposure_text("neutral"), seed)
    return pl["messages"][0]["content"], pl["messages"][1]["content"], 2048, "targeted"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, choices=["openai", "anthropic"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--price-in", type=float, help="$ per million input tokens (required to run)")
    ap.add_argument("--price-out", type=float, help="$ per million output tokens (required to run)")
    ap.add_argument("--reasoning-effort", default=None,
                    help="OpenAI reasoning models only; the manifest records the chosen setting")
    ap.add_argument("--limit", type=int, default=0, help="stop after N new requests (smoke test)")
    a = ap.parse_args()

    man = json.loads(MANP.read_text())
    model = man["models"][a.provider]["model_id"]
    if model == "REQUIRED_AT_RUNTIME":
        print(f"REFUSING: no model id recorded for {a.provider}. Run frontier_probe.py "
              f"--write-manifest --chosen-model <id> first."); return 2
    cap = man["cost_controls"]["hard_cap_per_provider_usd"]
    if not a.dry_run and (a.price_in is None or a.price_out is None):
        print("REFUSING: --price-in and --price-out are required so spend can be tracked against "
              "the cap. Read them from the provider's current pricing page."); return 2

    plan = D.Plan(); cases = {c["case_id"]: c for c in plan.cases}
    subset = man["inherits_from"]["case_ids"]
    store = OUT / f"frontier/frontier_{a.provider}_trials.jsonl"
    done = {}
    if store.exists():
        for line in store.open():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("status") == "OK":
                done[r["key"]] = r
    print(f"{a.provider} / {model}: {len(subset)} relations x {len(RUNGS)} rungs, "
          f"{len(done)} already complete, cap ${cap:.2f}")

    if a.dry_run:
        c = cases[subset[0]]
        text, _ = plan.paper_text(c, "E0")
        for rung in RUNGS:
            sysmsg, user, mx, kind = build(rung, c, text, P.seed_for(c["case_id"], "E0"))
            print(f"\n--- {rung} (max_tokens {mx}, kind {kind}) ---")
            print(f"system: {sysmsg[:90]}...")
            print(f"user  : {user[:160]}...")
            print(f"user length: {len(user)} chars")
        print("\ndry run only; no request issued")
        return 0

    spend = 0.0
    client = None
    if a.provider == "openai":
        from openai import OpenAI
        client = OpenAI()
    else:
        import anthropic
        client = anthropic.Anthropic()

    for cid in subset:
        c = cases[cid]
        text, valid = plan.paper_text(c, "E0")
        seed = P.seed_for(cid, "E0")
        for rung in RUNGS:
            key = f"frontier::{a.provider}::{model}::{cid}::{rung}"
            if key in done:
                continue
            if spend >= cap:
                print(f"STOPPING: measured spend ${spend:.2f} reached the cap ${cap:.2f}")
                return 0
            sysmsg, user, mx, kind = build(rung, c, text, seed)
            t0 = time.time()
            try:
                if a.provider == "openai":
                    kw = dict(model=model, max_completion_tokens=mx,
                              response_format={"type": "json_object"},
                              messages=[{"role": "system", "content": sysmsg},
                                        {"role": "user", "content": user}])
                    if a.reasoning_effort:
                        kw["reasoning_effort"] = a.reasoning_effort
                    r = client.chat.completions.create(**kw)
                    content = r.choices[0].message.content
                    ti, to = r.usage.prompt_tokens, r.usage.completion_tokens
                else:
                    # This SDK/model does not accept a temperature argument; the provider
                    # default is used and the deviation is recorded in the manifest.
                    r = client.messages.create(
                        model=model, max_tokens=mx, system=sysmsg,
                        messages=[{"role": "user", "content": user}])
                    # A refusal returns stop_reason="refusal" with zero content blocks; a
                    # thinking-enabled response puts a ThinkingBlock first. Neither is an error.
                    content = next((b.text for b in r.content
                                    if getattr(b, "type", "") == "text"), None)
                    ti, to = r.usage.input_tokens, r.usage.output_tokens
                    stop = r.stop_reason
                status = "OK" if (a.provider == "openai" or content is not None) else f"REFUSAL:{stop}"
            except Exception as e:
                content, ti, to, status = None, 0, 0, f"ERROR:{type(e).__name__}"
            cost = (ti / 1e6) * a.price_in + (to / 1e6) * a.price_out
            spend += cost
            rec = {"key": key, "provider": a.provider, "model": model, "rung": rung,
                   "case_id": cid, "paper": c["paper"], "domain": c["domain"],
                   "case_family": c["family"], "state": "E0", "truth": c["truth"]["E0"],
                   "seed": seed, "status": status, "content": content,
                   "stop_reason": locals().get("stop"),
                   "input_tokens": ti, "output_tokens": to, "cost_usd": round(cost, 6),
                   "cumulative_spend_usd": round(spend, 4),
                   "latency_s": round(time.time() - t0, 2),
                   "manifest_sha256": hashlib.sha256(MANP.read_bytes()).hexdigest()}
            with store.open("a") as fh:
                fh.write(json.dumps(rec) + "\n")
            print(f"{key.split('::',3)[3][:52]:54} {status:10} in={ti:6} out={to:5} ${spend:7.3f}")
            n_new = locals().get("n_new", 0) + 1
            if a.limit and n_new >= a.limit:
                print(f"\nsmoke-test limit {a.limit} reached; measured spend ${spend:.4f}")
                return 0
    print(f"\ncomplete. measured spend ${spend:.2f} of ${cap:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

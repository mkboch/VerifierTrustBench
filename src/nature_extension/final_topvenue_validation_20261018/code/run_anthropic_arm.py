#!/usr/bin/env python3
"""Anthropic arm, adapted to a technical infeasibility discovered before any scientific scoring.

Claude Sonnet 5.5 refuses the frozen finding-list prompt deterministically, regardless of
manuscript content (a four-line synthetic manuscript is refused too), regardless of the system
message, and regardless of whether JSON or prose is requested. It answers the verdict prompt on
the same manuscripts normally, and audits the same manuscripts happily in free prose.

The finding-list rungs are therefore UNMEASURABLE for this provider under the frozen protocol.
Prompts are NOT modified to evade the refusal: that would be prompt tuning after seeing outputs,
and it would also mean working around a provider's safety boundary.

This script therefore collects:
  (a) the verdict rung on all 60 relations  -> a real frontier data point on the localized task
  (b) the three finding-list rungs on a seed-fixed stratified subset -> a systematic refusal rate

The subset for (b) is chosen by stratified sampling across defect family and domain with the
project seed, fixed here before the requests are issued, and is not outcome-dependent.
"""
from __future__ import annotations
import argparse, collections, hashlib, json, random, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
RR = ROOT / "nature_extension/reviewer_response_20261016"
sys.path.insert(0, str(OUT / "code")); sys.path.insert(0, str(RR / "code"))
for p in ("exp3heldout", "exp2b", "exp2br"):
    sys.path.insert(0, str(ROOT / p))
import design_heldout as D, protocol as P  # noqa: E402
import importlib.util  # noqa: E402
_s = importlib.util.spec_from_file_location("rfl", OUT / "code/run_frontier_ladder.py")
_m = importlib.util.module_from_spec(_s)
_argv = sys.argv[:]            # the imported module must not clobber our own arguments
sys.argv = ["rfl"]
_s.loader.exec_module(_m)
sys.argv = _argv
build, RUNGS = _m.build, _m.RUNGS

SEED = 20261016
MANP = OUT / "frontier/FRONTIER_LADDER_MANIFEST.json"
FINDING_RUNGS = [r for r in RUNGS if r != "RELATION_LOCALIZED_BINARY_VERDICT"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--price-in", type=float, required=True)
    ap.add_argument("--price-out", type=float, required=True)
    ap.add_argument("--refusal-subset", type=int, default=15)
    ap.add_argument("--cap", type=float, default=None)
    a = ap.parse_args()

    man = json.loads(MANP.read_text())
    model = man["models"]["anthropic"]["model_id"]
    cap = a.cap if a.cap is not None else man["cost_controls"]["hard_cap_per_provider_usd"]
    plan = D.Plan(); cases = {c["case_id"]: c for c in plan.cases}
    subset = man["inherits_from"]["case_ids"]

    # seed-fixed stratified subset for the refusal measurement
    by = collections.defaultdict(list)
    for cid in subset:
        c = cases[cid]
        by[(c["family"], c["domain"])].append(cid)
    rng = random.Random(SEED)
    for v in by.values():
        rng.shuffle(v)
    strata, pick, i = sorted(by), [], 0
    while len(pick) < a.refusal_subset and any(by[s] for s in strata):
        s = strata[i % len(strata)]
        if by[s]:
            pick.append(by[s].pop())
        i += 1
    pick = sorted(pick)

    store = OUT / "frontier/frontier_anthropic_trials.jsonl"
    done = set()
    if store.exists():
        for line in store.open():
            try:
                done.add(json.loads(line)["key"])
            except json.JSONDecodeError:
                pass

    work = [(cid, "RELATION_LOCALIZED_BINARY_VERDICT") for cid in subset]
    work += [(cid, r) for cid in pick for r in FINDING_RUNGS]
    print(f"anthropic / {model}: {len(subset)} verdict requests + "
          f"{len(pick)}x{len(FINDING_RUNGS)} refusal-measurement requests = {len(work)} total")
    print(f"refusal subset (seed {SEED}, stratified): {', '.join(pick)}")

    import anthropic
    cl = anthropic.Anthropic()
    spend = 0.0
    for cid, rung in work:
        key = f"frontier::anthropic::{model}::{cid}::{rung}"
        if key in done:
            continue
        if spend >= cap:
            print(f"STOPPING at cap: ${spend:.2f}"); return 0
        c = cases[cid]
        text, _ = plan.paper_text(c, "E0")
        sysmsg, user, mx, _k = build(rung, c, text, P.seed_for(cid, "E0"))
        t0 = time.time()
        try:
            r = cl.messages.create(model=model, max_tokens=mx, system=sysmsg,
                                   messages=[{"role": "user", "content": user}])
            content = next((b.text for b in r.content if getattr(b, "type", "") == "text"), None)
            ti, to, stop = r.usage.input_tokens, r.usage.output_tokens, r.stop_reason
            status = "OK" if content is not None else f"REFUSAL:{stop}"
        except Exception as e:
            content, ti, to, stop, status = None, 0, 0, None, f"ERROR:{type(e).__name__}"
        cost = ti / 1e6 * a.price_in + to / 1e6 * a.price_out
        spend += cost
        rec = {"key": key, "provider": "anthropic", "model": model, "rung": rung,
               "case_id": cid, "paper": c["paper"], "domain": c["domain"],
               "case_family": c["family"], "state": "E0", "truth": c["truth"]["E0"],
               "status": status, "stop_reason": stop, "content": content,
               "input_tokens": ti, "output_tokens": to, "cost_usd": round(cost, 6),
               "cumulative_spend_usd": round(spend, 4), "latency_s": round(time.time() - t0, 2),
               "manifest_sha256": hashlib.sha256(MANP.read_bytes()).hexdigest()}
        with store.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(f"{cid:18} {rung:38} {status:18} ${spend:7.3f}")
    print(f"\ncomplete. measured spend ${spend:.2f} of ${cap:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

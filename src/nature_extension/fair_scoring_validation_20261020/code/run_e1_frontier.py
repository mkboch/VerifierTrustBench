#!/usr/bin/env python3
"""E1 fair-scoring run, GPT-5.2 frontier ladder.

    python run_e1_frontier.py --price-in 1.75 --price-out 14.0

Same model snapshot, same four rungs, same generators, same settings as the frozen E0
frontier ladder. The only difference is that the manuscript variant is E1.

BLIND_FINDING_LIST is deduplicated to one request per paper: the blind request carries no
relation information and the E1 manuscript is shared across the relations of a paper, and
the frozen runner does not transmit the seed to the provider, so the 60 relation-level
requests would be byte-identical in groups. This mirrors the frozen open-weight blind E1
granularity and is recorded in the frozen manifest.

Append-only JSONL, resumable, hard spend cap enforced after every response.
No Anthropic request is issued in this phase.
"""
from __future__ import annotations
import argparse, hashlib, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
RR = ROOT / "nature_extension/reviewer_response_20261016"
TV = ROOT / "nature_extension/final_topvenue_validation_20261018"
sys.path.insert(0, str(RR / "code"))
sys.path.insert(0, str(TV / "code"))
for p in ("exp3heldout", "exp2b", "exp2br"):
    sys.path.insert(0, str(ROOT / p))
import design_heldout as D, protocol as P  # noqa: E402
from run_frontier_ladder import build, RUNGS  # noqa: E402  frozen generators, imported not copied

MANP = OUT / "e1/E1_FAIR_SCORING_MANIFEST.json"
EXPECTED_MANIFEST = "fef612972be74de40910302b30e8ef777e36a2e4094c423d5a13392e0f863fac"
STATE = "E1"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--price-in", type=float, required=True)
    ap.add_argument("--price-out", type=float, required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    msha = hashlib.sha256(MANP.read_bytes()).hexdigest()
    if msha != EXPECTED_MANIFEST:
        print(f"REFUSING: frozen E1 manifest changed ({msha[:16]}).")
        return 2
    man = json.loads(MANP.read_text())
    model = man["frontier_model"]["model_id"]
    cap = man["cost_controls"]["hard_cap_per_provider_usd"]
    subset = man["case_ids"]

    plan = D.Plan()
    cases = {c["case_id"]: c for c in plan.cases}

    # one request per (rung, unit): blind is per paper, the rest per relation
    units = []
    seen_paper = set()
    for cid in subset:
        c = cases[cid]
        for rung in RUNGS:
            if rung == "BLIND_FINDING_LIST":
                if c["paper"] in seen_paper:
                    continue
                units.append((rung, c["paper"], cid))
            else:
                units.append((rung, cid, cid))
        seen_paper.add(c["paper"])

    store = OUT / "e1/e1_frontier_openai_trials.jsonl"
    done = {}
    if store.exists():
        for line in store.open():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("status") == "OK":
                done[r["key"]] = r
    print(f"openai / {model} E1: {len(units)} requests planned "
          f"({sum(1 for u in units if u[0] == 'BLIND_FINDING_LIST')} deduplicated blind), "
          f"{len(done)} already complete, cap ${cap:.2f}")

    if a.dry_run:
        print("dry run only; no request issued")
        return 0

    from openai import OpenAI
    client = OpenAI()
    spend = 0.0
    n_new = 0
    expected_snapshot = json.loads((TV / "frontier/FRONTIER_LADDER_MANIFEST.json").read_text()
                                   )["models"]["openai"]["snapshot_id"]
    snapshot_seen = None

    for rung, unit, cid in units:
        c = cases[cid]
        key = f"e1frontier::openai::{model}::{unit}::{rung}"
        if key in done:
            continue
        if spend >= cap:
            print(f"STOPPING: measured spend ${spend:.2f} reached the cap ${cap:.2f}")
            return 0
        text, _valid = plan.paper_text(c, STATE)
        seed = P.seed_for(cid, STATE)
        sysmsg, user, mx, kind = build(rung, c, text, seed)
        t0 = time.time()
        try:
            r = client.chat.completions.create(
                model=model, max_completion_tokens=mx,
                response_format={"type": "json_object"},
                reasoning_effort="none",
                messages=[{"role": "system", "content": sysmsg},
                          {"role": "user", "content": user}])
            content = r.choices[0].message.content
            ti, to = r.usage.prompt_tokens, r.usage.completion_tokens
            status = "OK"
            # The frozen E0 run addressed this model by its alias. If the alias has since
            # moved, E1 would silently be a different checkpoint and the E0/E1 comparison
            # would be confounded. Abort rather than record an incomparable cell.
            if snapshot_seen is None:
                snapshot_seen = getattr(r, "model", None)
                print(f"resolved snapshot: {snapshot_seen} (E0 ran {expected_snapshot})")
                if snapshot_seen != expected_snapshot:
                    print(f"REFUSING: alias '{model}' now resolves to '{snapshot_seen}' but the "
                          f"frozen E0 ladder ran '{expected_snapshot}'. E0 and E1 would not be "
                          f"the same checkpoint. Aborting before any further request.")
                    return 3
        except Exception as e:
            content, ti, to, status = None, 0, 0, f"ERROR:{type(e).__name__}"
        cost = (ti / 1e6) * a.price_in + (to / 1e6) * a.price_out
        spend += cost
        rec = {"key": key, "provider": "openai", "model": model, "rung": rung,
               "unit": unit, "unit_kind": "paper" if rung == "BLIND_FINDING_LIST" else "relation",
               "case_id": cid, "paper": c["paper"], "domain": c["domain"],
               "case_family": c["family"], "state": STATE, "truth": c["truth"][STATE],
               "seed": seed, "status": status, "content": content,
               "input_tokens": ti, "output_tokens": to, "cost_usd": round(cost, 6),
               "cumulative_spend_usd": round(spend, 4),
               "latency_s": round(time.time() - t0, 2),
               "resolved_snapshot": snapshot_seen,
               "phase_label": man["label"], "e1_manifest_sha256": msha}
        with store.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        n_new += 1
        print(f"{rung[:34]:36}{str(unit)[:20]:22}{status:10} in={ti:6} out={to:5} ${spend:7.3f}",
              flush=True)
        if a.limit and n_new >= a.limit:
            print(f"\nsmoke-test limit {a.limit} reached; measured spend ${spend:.4f}")
            return 0
    print(f"\ncomplete. {n_new} new requests, measured spend ${spend:.2f} of ${cap:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
